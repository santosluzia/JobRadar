"""Relatório diário por e-mail (HTML + texto), com idempotência por vaga.

Idempotência: o registro meta/notifications guarda (job_id, canal). Uma vaga só é enviada
uma vez por canal, mesmo que o workflow seja reexecutado. Se o envio falhar, nada é
registrado e a vaga volta a ser candidata na próxima execução (dentro da janela).
"""
from __future__ import annotations

import html
import json
import logging
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from ..analytics.selection import relevantes
from ..settings import Settings
from ..storage import Lake

log = logging.getLogger(__name__)
CANAL = "email"
FUSO = ZoneInfo("America/Sao_Paulo")
ROTULO = {"remoto": "Remoto", "hibrido": "Híbrido", "presencial": "Presencial", "nao_informada": "Modalidade n/i",
          "junior": "Júnior", "pleno": "Pleno", "senior": "Sênior", "estagio": "Estágio",
          "lideranca": "Liderança"}


@dataclass
class Candidata:
    job: dict[str, Any]
    score: int
    explicacao: list[dict]
    lacunas: list[dict]
    sem_evidencia: list[dict]
    requisitos: list[str]


def candidatas(s: Settings, agora: datetime) -> list[Candidata]:
    lake = Lake(s.lake)
    jobs, skills = lake.read("silver/jobs"), lake.read("silver/job_skills")
    if jobs.empty:
        return []
    cfg = s.sources.get("notificacoes", {})
    mask = relevantes(jobs, skills, s.filtros, agora, int(s.sources["busca"].get("max_dias_publicacao", 30)))
    primeira = pd.to_datetime(jobs["primeira_observacao"], utc=True)
    mask &= primeira >= agora - timedelta(days=int(cfg.get("janela_dias", 7)))
    ja = set(lake.read("meta/notifications").query("canal == @CANAL")["job_id"])
    mask &= ~jobs["job_id"].isin(ja)
    sel = jobs[mask].merge(lake.read("gold/job_scores"), on="job_id", how="left")
    sel = sel[sel["score"].fillna(0) >= int(s.filtros.get("score_minimo", 0))]
    sel = sel.sort_values(["score", "publicada_em"], ascending=[False, False]).head(int(cfg.get("limite", 20)))
    sel = sel.astype(object).where(sel.notna(), None)  # NaN do pandas → None
    req = skills[skills["importancia"] == "requisito"].groupby("job_id")["skill_id"].apply(list).to_dict()
    return [Candidata(j, int(j["score"]), json.loads(j["explicacao"] or "[]"), json.loads(j["lacunas"] or "[]"),
                      json.loads(j["sem_evidencia"] or "[]"), sorted(req.get(j["job_id"], [])))
            for j in sel.to_dict("records")]


def _data(v: Any) -> str:
    if v is None or pd.isna(v):
        return "não informada"
    return pd.Timestamp(v).tz_convert(FUSO).strftime("%d/%m/%Y")


def renderizar(vagas: list[Candidata], agora: datetime, nomes: dict[str, str],
               fontes: list[dict[str, Any]]) -> tuple[str, str, str]:
    dia = agora.astimezone(FUSO).strftime("%d/%m/%Y")
    assunto = f"JobRadar {dia}: {len(vagas)} vaga(s) nova(s) de dados" if vagas else f"JobRadar {dia}: sem vagas novas"
    e = html.escape
    cards, texto = [], [assunto, ""]
    for i, v in enumerate(vagas, 1):
        j = v.job
        local = j.get("cidade") or j.get("uf") or ""
        meta = " · ".join(x for x in [e(j.get("empresa") or "Empresa não informada"), ROTULO.get(j["modalidade"], ""),
                                      e(local), ROTULO.get(j["senioridade"], "")] if x)
        req = ", ".join(nomes.get(k, k) for k in v.requisitos) or "nenhuma identificada"
        gaps = ", ".join(nomes.get(x["skill_id"], x["skill_id"]) for x in v.lacunas if x["importancia"] == "requisito")
        sem = ", ".join(nomes.get(x["skill_id"], x["skill_id"]) for x in v.sem_evidencia if x["importancia"] == "requisito")
        crit = "; ".join(f"{c['criterio']} {c['pontos']:g}/{c['maximo']}" for c in v.explicacao if c["criterio"] != "penalidade")
        cards.append(f"""
<tr><td style="padding:16px 20px;border-bottom:1px solid #e7e2d6">
  <div style="font-size:12px;color:#8a8170">{i:02d} · Score de aderência <b style="color:#1c1a17">{v.score}</b>/100 · {e(j['source'])}</div>
  <div style="font-size:17px;font-weight:600;margin:4px 0 2px"><a href="{e(j['url'], quote=True)}" style="color:#1c1a17;text-decoration:none">{e(j['titulo'])}</a></div>
  <div style="font-size:14px;color:#4a453c">{meta}</div>
  <div style="font-size:13px;color:#4a453c;margin-top:8px">Publicada: {_data(j.get('publicada_em'))} · Coletada: {_data(j.get('primeira_observacao'))}</div>
  <div style="font-size:13px;margin-top:6px"><b>Competências pedidas:</b> {e(req)}</div>
  {f'<div style="font-size:13px;margin-top:4px;color:#9a3412"><b>Lacunas:</b> {e(gaps)}</div>' if gaps else ''}
  {f'<div style="font-size:13px;margin-top:4px;color:#6b6457"><b>Sem evidência no perfil:</b> {e(sem)}</div>' if sem else ''}
  <div style="font-size:12px;color:#8a8170;margin-top:6px">{e(crit)}</div>
  <div style="margin-top:10px"><a href="{e(j['url'], quote=True)}" style="display:inline-block;background:#1c1a17;color:#f5f1e8;padding:8px 14px;border-radius:6px;text-decoration:none;font-size:13px">Abrir vaga para se candidatar</a></div>
</td></tr>""")
        texto += [f"{i}. {j['titulo']} — {j.get('empresa') or 'empresa n/i'} ({ROTULO.get(j['modalidade'], '')})",
                  f"   Score {v.score}/100 · publicada {_data(j.get('publicada_em'))} · requisitos: {req}",
                  f"   Lacunas: {gaps or '-'} · Sem evidência: {sem or '-'}", f"   {j['url']}", ""]
    saude = " | ".join(f"{f['fonte']}: {f['status_ultima_execucao']}" for f in fontes) or "sem execuções"
    corpo = f"""<!doctype html><html><body style="margin:0;background:#f5f1e8;font-family:Arial,Helvetica,sans-serif;color:#1c1a17">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;margin:0 auto;background:#fffdf8">
<tr><td style="padding:20px;background:#1c1a17;color:#f5f1e8">
  <div style="font-size:12px;letter-spacing:.08em;color:#c9a227">JOBRADAR</div>
  <div style="font-size:20px;font-weight:600">{e(assunto)}</div></td></tr>
{''.join(cards) or '<tr><td style="padding:20px">Nenhuma vaga nova acima do score mínimo nesta execução.</td></tr>'}
<tr><td style="padding:16px 20px;font-size:12px;color:#8a8170">
  Fontes: {e(saude)}<br>O score mede compatibilidade com o seu perfil; não é probabilidade de contratação.
  "Sem evidência" significa que a competência não está registrada no perfil, não que você não a tenha.
</td></tr></table></body></html>"""
    texto.append(f"Fontes: {saude}")
    return assunto, corpo, "\n".join(texto)


def enviar_smtp(s: Settings, assunto: str, corpo_html: str, corpo_texto: str) -> None:
    host, user, pwd = s.env("SMTP_HOST"), s.env("SMTP_USER"), s.env("SMTP_PASSWORD")
    para = s.env("EMAIL_TO")
    if not (host and user and pwd and para):
        raise RuntimeError("defina SMTP_HOST, SMTP_USER, SMTP_PASSWORD e EMAIL_TO (ou use --dry-run)")
    porta = int(s.env("SMTP_PORT") or 587)
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = assunto, s.env("EMAIL_FROM") or user, para
    msg.set_content(corpo_texto)
    msg.add_alternative(corpo_html, subtype="html")
    ctx = ssl.create_default_context()
    if porta == 465:
        with smtplib.SMTP_SSL(host, porta, context=ctx, timeout=30) as smtp:
            smtp.login(user, pwd)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, porta, timeout=30) as smtp:
            smtp.starttls(context=ctx)
            smtp.login(user, pwd)
            smtp.send_message(msg)


def registrar(lake: Lake, vagas: list[Candidata], run_id: str, agora: datetime) -> None:
    lake.append("meta/notifications", pd.DataFrame(
        [{"job_id": v.job["job_id"], "canal": CANAL, "enviada_em": agora, "run_id": run_id} for v in vagas]))
