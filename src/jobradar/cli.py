"""Linha de comando do JobRadar.

    jobradar run                     coleta + bronze/silver/gold
    jobradar publish --out DIR       gera, VALIDA e grava os JSON públicos v1
    jobradar notify [--dry-run]      e-mail com vagas ainda não notificadas
    jobradar status                  últimas execuções e saúde das fontes
    jobradar recomendacoes           prioridades de estudo (privado)
    jobradar candidatura ID STATUS   registra status de candidatura (privado)
    jobradar estudo SKILL STATUS     registra progresso de estudo (privado)
    jobradar contract export         regrava os JSON Schema do contrato
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import pipeline
from .applications import STUDY_STATUSES, atualizar_candidatura, atualizar_estudo
from .collectors import build_collectors
from .models import APPLICATION_STATUSES
from .settings import ROOT, carregar
from .storage import Lake, utcnow

EXIT_FALHA_COLETA, EXIT_CONTRATO, EXIT_NOTIFICACAO = 2, 3, 4


def _resumo_github(texto: str) -> None:
    destino = os.getenv("GITHUB_STEP_SUMMARY")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write(texto + "\n")


def cmd_run(a, s) -> int:
    rep = pipeline.run(s, build_collectors(s), run_id=a.run_id)
    if a.report:
        Path(a.report).write_text(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2, default=str))
    linhas = ["### JobRadar — execução " + rep.run_id, "", f"Status: **{rep.status}** em {rep.duracao_s}s", "",
              "| Fonte | OK | Coletados | Válidos | Inválidos | Duplicatas | Novas | Retentativas |",
              "|---|---|---|---|---|---|---|---|"]
    linhas += [f"| {f.source} | {'✅' if f.ok else '❌ ' + '; '.join(f.erros)[:80]} | {f.coletados} | {f.validos} | "
               f"{f.invalidos} | {f.duplicatas_fonte} | {f.novas} | {f.retentativas} |" for f in rep.fontes]
    linhas += ["", f"Observadas: {rep.observadas} · novas: {rep.novas} · duplicatas entre fontes: "
               f"{rep.duplicatas_entre_fontes} · requisitos alterados: {rep.requisitos_alterados}"]
    texto = "\n".join(linhas)
    print(texto)
    _resumo_github(texto)
    saida = os.getenv("GITHUB_OUTPUT")
    if saida:  # sinaliza ao workflow que a execução terminou de forma limpa (lake consistente)
        with open(saida, "a", encoding="utf-8") as f:
            f.write(f"status={rep.status}\nnovas={rep.novas}\n")
    return EXIT_FALHA_COLETA if rep.status == "falha" else 0


def cmd_publish(a, s) -> int:
    from .publishing import ContractError, construir, publicar
    agora = utcnow()
    run_id = a.run_id or agora.strftime("%Y%m%dT%H%M%SZ")
    try:
        destino = publicar(construir(s, agora, run_id), Path(a.out), run_id, agora)
    except ContractError as e:
        print(e, file=sys.stderr)
        return EXIT_CONTRATO
    print(f"contrato v1 validado e gravado em {destino}")
    return 0


def cmd_notify(a, s) -> int:
    from .analytics import market
    from .notifications import candidatas, enviar_smtp, registrar, renderizar
    from .transformations.skills import Taxonomy
    agora = utcnow()
    lake = Lake(s.lake)
    vagas = candidatas(s, agora)
    nomes = {k.id: k.nome for k in Taxonomy(s.skills).skills}
    assunto, corpo, texto = renderizar(vagas, agora, nomes, market.fontes(market.carregar(lake)))
    if a.dry_run:
        out = Path(a.html_out or "jobradar-email.html")
        out.write_text(corpo, encoding="utf-8")
        print(f"{assunto}\n(prévia em {out}; nada enviado nem registrado)")
        return 0
    if not vagas and not s.sources.get("notificacoes", {}).get("enviar_quando_vazio", False):
        print("nenhuma vaga nova para notificar")
        _resumo_github("Notificações: 0 (nenhuma vaga nova)")
        return 0
    try:
        enviar_smtp(s, assunto, corpo, texto)
    except Exception as e:  # nada é registrado: as vagas voltam na próxima execução
        print(f"falha no envio: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_NOTIFICACAO
    registrar(lake, vagas, a.run_id or agora.strftime("%Y%m%dT%H%M%SZ"), agora)
    print(f"e-mail enviado com {len(vagas)} vaga(s)")
    _resumo_github(f"Notificações enviadas: {len(vagas)}")
    return 0


def cmd_status(a, s) -> int:
    from .analytics import market
    snap = market.carregar(Lake(s.lake))
    print(snap.runs.sort_values("iniciada_em").tail(a.n)[["run_id", "status", "duracao_s"]].to_string(index=False)
          if not snap.runs.empty else "nenhuma execução registrada")
    for f in market.fontes(snap):
        print(f)
    return 0


def cmd_recomendacoes(a, s) -> int:
    from .analytics import market
    from .recommendations import recomendar
    from .scoring import Profile
    from .transformations.skills import Taxonomy
    recs = recomendar(market.carregar(Lake(s.lake)), Profile.from_dict(s.profile), Taxonomy(s.skills),
                      s.scoring["recomendacoes"], s.filtros, utcnow())
    for r in recs[: a.n]:
        print(f"[{r.classe}] {r.nome} (prioridade {r.prioridade}): {r.justificativa}")
    return 0


def cmd_candidatura(a, s) -> int:
    atualizar_candidatura(Lake(s.lake), a.job_id, a.status, a.nota)
    print(f"{a.job_id}: {a.status}")
    return 0


def cmd_estudo(a, s) -> int:
    atualizar_estudo(Lake(s.lake), a.skill, a.status, a.inicio, a.conclusao, a.evidencia)
    print(f"{a.skill}: {a.status}")
    return 0


def cmd_contract(a, s) -> int:
    from .publishing import exportar_schemas
    exportar_schemas(ROOT / "docs" / "contracts" / "v1", ROOT / "src" / "jobradar" / "publishing" / "schemas")
    print("schemas exportados")
    return 0


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="jobradar", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lake", help="pasta do histórico (padrão: $JOBRADAR_LAKE ou ./lake)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run"); r.add_argument("--run-id"); r.add_argument("--report"); r.set_defaults(f=cmd_run)
    pb = sub.add_parser("publish"); pb.add_argument("--out", default="public_out"); pb.add_argument("--run-id")
    pb.set_defaults(f=cmd_publish)
    n = sub.add_parser("notify"); n.add_argument("--dry-run", action="store_true"); n.add_argument("--html-out")
    n.add_argument("--run-id"); n.set_defaults(f=cmd_notify)
    st = sub.add_parser("status"); st.add_argument("-n", type=int, default=10); st.set_defaults(f=cmd_status)
    rc = sub.add_parser("recomendacoes"); rc.add_argument("-n", type=int, default=15); rc.set_defaults(f=cmd_recomendacoes)
    c = sub.add_parser("candidatura"); c.add_argument("job_id"); c.add_argument("status", choices=APPLICATION_STATUSES)
    c.add_argument("--nota"); c.set_defaults(f=cmd_candidatura)
    e = sub.add_parser("estudo"); e.add_argument("skill"); e.add_argument("status", choices=STUDY_STATUSES)
    e.add_argument("--inicio"); e.add_argument("--conclusao"); e.add_argument("--evidencia"); e.set_defaults(f=cmd_estudo)
    ct = sub.add_parser("contract"); ct.add_argument("acao", choices=["export"]); ct.set_defaults(f=cmd_contract)

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = carregar(lake=a.lake)
    sys.exit(a.f(a, s))


if __name__ == "__main__":
    main()
