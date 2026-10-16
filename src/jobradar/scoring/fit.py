"""Score de aderência explicável (0–100).

Não é probabilidade de contratação: mede o quanto a vaga combina com o objetivo e as
evidências registradas no perfil. Cada ponto vem acompanhado do critério que o gerou.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..transformations.text import normalizar
from .profile import Profile


@dataclass
class FitResult:
    score: int
    explicacao: list[dict[str, Any]] = field(default_factory=list)
    lacunas: list[dict[str, str]] = field(default_factory=list)       # requisito que você marcou como não dominado
    sem_evidencia: list[dict[str, str]] = field(default_factory=list)  # requisito sem registro no perfil


def calcular(job: dict[str, Any], skills: list[dict[str, str]], profile: Profile,
             cfg: dict[str, Any], palavras_excludentes: list[str] | None = None) -> FitResult:
    pesos, evid = cfg["pesos"], cfg["evidencia"]
    exp: list[dict[str, Any]] = []
    total = 0.0

    # 1. Família / responsabilidades
    fam = job.get("familia") or "outra"
    frac = float(cfg["familia"].get(fam, 0))
    if profile.familias and fam in profile.familias:
        frac = max(frac, 1.0)
    pts = pesos["familia"] * frac
    exp.append({"criterio": "familia", "pontos": round(pts, 1), "maximo": pesos["familia"],
                "detalhe": f"cargo classificado como {fam}"})
    total += pts

    # 2. Competências
    req = [s for s in skills if s["importancia"] == "requisito"]
    des = [s for s in skills if s["importancia"] == "desejavel"]
    lacunas, sem_ev = [], []
    if not skills:
        pts = pesos["competencias"] * 0.5
        detalhe = "nenhuma competência identificada na descrição (pontuação neutra)"
    else:
        peso_d = float(cfg["peso_desejavel"])
        denom = len(req) + peso_d * len(des)
        cobertura = sum(float(evid[profile.nivel(s["skill_id"])]) for s in req) \
            + peso_d * sum(float(evid[profile.nivel(s["skill_id"])]) for s in des)
        pts = pesos["competencias"] * (cobertura / denom if denom else 0)
        for s in req + des:
            nivel = profile.nivel(s["skill_id"])
            item = {"skill_id": s["skill_id"], "importancia": s["importancia"]}
            if nivel == "nao_dominada":
                lacunas.append(item)
            elif nivel == "sem_evidencia":
                sem_ev.append(item)
        cobertos = sum(1 for s in req if evid[profile.nivel(s["skill_id"])] > 0)
        detalhe = f"{cobertos}/{len(req)} requisitos com evidência no perfil, {len(des)} desejáveis"
    exp.append({"criterio": "competencias", "pontos": round(pts, 1), "maximo": pesos["competencias"],
                "detalhe": detalhe})
    total += pts

    # 3. Senioridade
    sen = job.get("senioridade") or "nao_informada"
    frac = float(cfg["senioridade"].get(sen, 0.5))
    if profile.senioridades and sen in profile.senioridades:
        frac = 1.0
    pts = pesos["senioridade"] * frac
    exp.append({"criterio": "senioridade", "pontos": round(pts, 1), "maximo": pesos["senioridade"],
                "detalhe": f"senioridade {sen}"})
    total += pts

    # 4. Modalidade e local
    mod = job.get("modalidade") or "nao_informada"
    frac, det = _modalidade_local(job, mod, profile)
    pts = pesos["modalidade_local"] * frac
    exp.append({"criterio": "modalidade_local", "pontos": round(pts, 1), "maximo": pesos["modalidade_local"],
                "detalhe": det})
    total += pts

    # 5. Penalidades
    pen = cfg.get("penalidades", {})
    titulo = normalizar(job.get("titulo"))
    for palavra in palavras_excludentes or []:
        if normalizar(palavra) and normalizar(palavra) in titulo:
            total -= pen.get("palavra_excludente", 30)
            exp.append({"criterio": "penalidade", "pontos": -pen.get("palavra_excludente", 30), "maximo": 0,
                        "detalhe": f"título contém '{palavra}'"})
            break
    if fam == "outra":
        total -= pen.get("familia_outra", 20)
        exp.append({"criterio": "penalidade", "pontos": -pen.get("familia_outra", 20), "maximo": 0,
                    "detalhe": "cargo fora das famílias de dados"})

    return FitResult(max(0, min(100, round(total))), exp, lacunas, sem_ev)


def _modalidade_local(job: dict[str, Any], mod: str, profile: Profile) -> tuple[float, str]:
    if mod == "nao_informada":
        return 0.5, "modalidade não informada (pontuação neutra)"
    if profile.modalidades and mod not in profile.modalidades:
        return 0.0, f"{mod} fora das modalidades do perfil"
    if mod == "remoto":
        return 1.0, "remoto"
    uf, cidade = job.get("uf"), normalizar(job.get("cidade"))
    if not (profile.ufs or profile.cidades):
        return 1.0, mod
    if (cidade and cidade in profile.cidades) or (uf and uf in profile.ufs):
        return 1.0, f"{mod} em {job.get('cidade') or uf}"
    if not uf and not cidade:
        return 0.5, f"{mod}, local não informado"
    return 0.2, f"{mod} fora da região preferida ({job.get('cidade') or uf})"
