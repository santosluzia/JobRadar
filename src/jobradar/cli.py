"""Linha de comando do JobRadar.

    jobradar run                     coleta + bronze/silver/gold
    jobradar publish --out DIR       gera, VALIDA e grava os JSON públicos v1
    jobradar notify [--dry-run]      e-mail com vagas ainda não notificadas
    jobradar status                  últimas execuções e saúde das fontes
    jobradar empresas listar         catálogo de empresas (config/empresas.yaml) e última coleta de cada uma
    jobradar recomendacoes           prioridades de estudo (privado)
    jobradar candidatura ID STATUS   registra status de candidatura (privado)
    jobradar estudo SKILL STATUS     registra progresso de estudo (privado)
    jobradar contract export         regrava os JSON Schema do contrato
    jobradar reextrair [--todas]     reaplica a taxonomia atual ao histórico (gold e scores inclusos)
    jobradar enriquecer [--todas]    camada semântica local (embeddings) nas vagas pendentes
    jobradar competencias candidatas fila de curadoria: termos que a taxonomia não cobre
    jobradar avaliacao amostrar      sorteia vagas para o conjunto-ouro (privado)
    jobradar avaliacao medir         precisão/recall da extração contra o conjunto-ouro
    jobradar coocorrencia [--skill]  competências que aparecem juntas (suporte, confiança, lift, Jaccard)
    jobradar curriculo ...           currículo PRIVADO, só local: importar, versoes, mostrar, comparar,
                                     exportar, apagar, diagnostico, historico
    jobradar evolucao plano|progresso|historico   Minha Evolução Profissional (privado)
    jobradar radar [--dry-run]       JobRadar — Seu Radar Profissional (e-mail diário)
    jobradar semanal [--dry-run]     JobRadar — Relatório Semanal de Evolução Profissional
    jobradar mensal [--dry-run]      Diagnóstico Mensal de Career Intelligence (retrato + e-mail)
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
    """Resumo da execução no GitHub (PÚBLICO no repositório público): só agregados, e mascarado."""
    from .seguranca import mascarar
    destino = os.getenv("GITHUB_STEP_SUMMARY")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write(mascarar(texto) + "\n")


def _sem_perfil(s) -> None:
    """Workflow público com a parte pessoal no privado: o perfil sai da memória antes de qualquer etapa."""
    s.profile = {}
    s.profile_path = None


def cmd_run(a, s) -> int:
    from .validacoes import validar_configuracoes
    if a.sem_pontuacao:
        _sem_perfil(s)
    rep = pipeline.run(s, build_collectors(s), run_id=a.run_id, pontuar=not a.sem_pontuacao)
    validar_configuracoes(s, Lake(s.lake), rep.run_id, incluir_privadas=not a.sem_pontuacao)
    if a.report:
        Path(a.report).write_text(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2, default=str))
    linhas = ["### JobRadar — execução " + rep.run_id, "", f"Status: **{rep.status}** em {rep.duracao_s}s", "",
              "| Fonte | OK | Coletados | Válidos | Inválidos | Duplicatas | Novas | Retentativas |",
              "|---|---|---|---|---|---|---|---|"]
    linhas += [f"| {f.source} | {'✅' if f.ok else '❌ ' + '; '.join(f.erros)[:80]} | {f.coletados} | {f.validos} | "
               f"{f.invalidos} | {f.duplicatas_fonte} | {f.novas} | {f.retentativas} |" for f in rep.fontes]
    linhas += ["", f"Observadas: {rep.observadas} · novas: {rep.novas} · duplicatas entre fontes: "
               f"{rep.duplicatas_entre_fontes} · requisitos alterados: {rep.requisitos_alterados} · "
               f"encerradas (saíram do quadro): {rep.encerradas_fora_do_quadro}"]
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
    from .publishing.contract import SCHEMA_VERSION
    from .validacoes import registrar
    try:
        destino = publicar(construir(s, agora, run_id), Path(a.out), run_id, agora)
    except ContractError as e:
        print(e, file=sys.stderr)
        registrar(Lake(s.lake), run_id, "contrato_publico", SCHEMA_VERSION, False, str(e).count("\n  ") or 1,
                  str(e).splitlines()[0], agora)
        return EXIT_CONTRATO
    registrar(Lake(s.lake), run_id, "contrato_publico", SCHEMA_VERSION, True, 0, None, agora)
    print(f"contrato v1 validado e gravado em {destino}")
    return 0


def _turno(valor: str | None) -> int | None:
    if valor in (None, ""):
        return None
    nomes = ["madrugada", "manha", "tarde", "noite"]
    return nomes.index(valor) if valor in nomes else int(valor) % 4


def cmd_radar(a, s) -> int:
    from .notifications import radar
    agora = utcnow()
    try:
        r = radar.enviar(s, agora, a.run_id or agora.strftime("%Y%m%dT%H%M%SZ"), turno=_turno(a.turno),
                         dry_run=a.dry_run, forcar=a.forcar, html_out=Path(a.html_out or "radar.html") if a.dry_run else None)
    except Exception as e:
        print(f"falha no Radar: {type(e).__name__}", file=sys.stderr)
        return EXIT_NOTIFICACAO
    # só contagens: o conteúdo do Radar é privado e não vai para o log
    print(f"Radar: {r['motivo']}" + (f" · vagas {r['vagas']}, tendências {r['tendencias']}, oportunidade "
                                     f"{'sim' if r['oportunidade'] else 'não'}, ação {'sim' if r['acao'] else 'não'}"
                                     if "vagas" in r else ""))
    if a.dry_run:
        print(f"prévia em {a.html_out or 'radar.html'}")
    return 0


def cmd_semanal(a, s) -> int:
    from .notifications import semanal
    agora = utcnow()
    try:
        r = semanal.enviar(s, agora, a.run_id or agora.strftime("%Y%m%dT%H%M%SZ"), turno=_turno(a.turno),
                           dry_run=a.dry_run, forcar=a.forcar,
                           html_out=(a.html_out or "relatorio_semanal.html") if a.dry_run else None)
    except Exception as e:
        print(f"falha no Relatório Semanal: {type(e).__name__}", file=sys.stderr)
        return EXIT_NOTIFICACAO
    print(f"Relatório semanal: {r['motivo']}" + (f" · {r['oportunidades']} oportunidade(s)" if "oportunidades" in r else ""))
    if a.dry_run:
        print(f"prévia em {a.html_out or 'relatorio_semanal.html'}")
    return 0


def cmd_mensal(a, s) -> int:
    from .notifications import mensal
    agora = utcnow()
    try:
        r = mensal.enviar(s, agora, a.run_id or agora.strftime("%Y%m%dT%H%M%SZ"), turno=_turno(a.turno),
                          dry_run=a.dry_run, forcar=a.forcar,
                          html_out=(a.html_out or "diagnostico_mensal.html") if a.dry_run else None)
    except Exception as e:
        print(f"falha no Diagnóstico Mensal: {type(e).__name__}", file=sys.stderr)
        return EXIT_NOTIFICACAO
    print(f"Diagnóstico mensal: {r['motivo']}" + (f" · {r['objetivos']} objetivo(s)" if "objetivos" in r else ""))
    if a.dry_run:
        print(f"prévia em {a.html_out or 'diagnostico_mensal.html'}")
    return 0


def cmd_notify(a, s) -> int:
    from .analytics import market
    from .notifications import enviar_smtp, registrar, renderizar, selecionar
    from .transformations.skills import Taxonomy
    agora = utcnow()
    lake = Lake(s.lake)
    # No turno configurado em private/radar.yaml, o Radar substitui o e-mail de vagas (e já leva as vagas novas).
    turno = _turno(getattr(a, "turno", None))   # sem turno (chamada antiga): comportamento de antes
    if turno is not None and not a.dry_run:
        # Relatório Semanal: e-mail à parte, no turno/dia dele; não substitui o Radar nem o alerta de vagas.
        from .notifications import semanal
        try:
            rs = semanal.enviar(s, agora, a.run_id or agora.strftime("%Y%m%dT%H%M%SZ"), turno=turno)
            print(f"Relatório semanal: {'enviado' if rs['enviado'] else rs['motivo']}")
            if rs["enviado"]:
                _resumo_github("Relatório Semanal de Evolução Profissional enviado")
        except Exception as e:      # falha do semanal não impede o e-mail do turno; fica registrada para a próxima
            print(f"falha no Relatório Semanal: {type(e).__name__}", file=sys.stderr)
        # Diagnóstico mensal: grava o retrato do mês (histórico) e envia o e-mail, no dia/turno dele
        from .notifications import mensal
        try:
            rm = mensal.enviar(s, agora, a.run_id or agora.strftime("%Y%m%dT%H%M%SZ"), turno=turno)
            print(f"Diagnóstico mensal: {'gerado' if rm.get('gerado') else rm['motivo']}")
        except Exception as e:
            print(f"falha no Diagnóstico Mensal: {type(e).__name__}", file=sys.stderr)
        from .notifications import radar
        try:
            r = radar.enviar(s, agora, a.run_id or agora.strftime("%Y%m%dT%H%M%SZ"), turno=turno)
        except Exception as e:
            print(f"falha no envio do Radar: {type(e).__name__}", file=sys.stderr)
            return EXIT_NOTIFICACAO
        if r["enviado"]:
            print(f"Radar enviado: {r['vagas']} vaga(s), ação do dia: {'sim' if r['acao'] else 'não'}")
            _resumo_github(f"Radar Profissional enviado ({r['vagas']} vaga(s))")
            return 0
        print(f"Radar não enviado neste turno: {r['motivo']}")
    vagas, excedentes = selecionar(s, agora)
    nomes = {k.id: k.nome for k in Taxonomy(s.skills).skills}
    cartoes = int(s.sources.get("notificacoes", {}).get("cartoes", 10))
    assunto, corpo, texto = renderizar(vagas, agora, nomes, market.fontes(market.carregar(lake)),
                                       cartoes=cartoes, excedentes=excedentes)
    if a.dry_run:
        out = Path(a.html_out or "jobradar-email.html")
        out.write_text(corpo, encoding="utf-8")
        print(f"{assunto}\n(prévia em {out}; nada enviado nem registrado)")
        return 0
    # --pular-se-vazio: os turnos fora da manhã só mandam e-mail se houver vaga nova; o e-mail
    # vazio da manhã basta como alarme de coleta parada.
    if not vagas and (a.pular_se_vazio or not s.sources.get("notificacoes", {}).get("enviar_quando_vazio", True)):
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
    snap = market.carregar(Lake(s.lake))   # só execuções e fontes: competências não importam aqui
    print(snap.runs.sort_values("iniciada_em").tail(a.n)[["run_id", "status", "duracao_s"]].to_string(index=False)
          if not snap.runs.empty else "nenhuma execução registrada")
    for f in market.fontes(snap):
        print(f)
    return 0


def cmd_empresas(a, s) -> int:
    """Catálogo + situação medida (meta/board_runs). Só dados públicos e operacionais."""
    from .empresas import carregar_catalogo, situacao
    tab = situacao(carregar_catalogo(s.empresas), Lake(s.lake))
    if a.status:
        tab = tab[tab["status"] == a.status]
    if a.ats:
        tab = tab[tab["ats"] == a.ats]
    if tab.empty:
        print("nenhuma empresa no catálogo com esse filtro")
        return 0
    import pandas as pd
    for col in ("ultima_coleta_ok", "ultima_tentativa"):
        tab[col] = pd.to_datetime(tab[col], utc=True).dt.strftime("%Y-%m-%d %H:%M")
    cols = ["id", "nome", "pais", "segmento", "ats", "status", "verificada_em", "ultima_coleta_ok",
            "falhas_seguidas", "vagas_listadas", "vagas_mantidas"]
    print(tab[cols].astype(object).where(tab[cols].notna(), "—").to_string(index=False))
    ativas = tab[tab["status"] == "ativa"]
    print(f"\n{len(tab)} empresas · {len(ativas)} ativas · "
          f"{int((ativas['falhas_seguidas'] > 0).sum())} ativas com falha na última tentativa")
    return 0


def cmd_recomendacoes(a, s) -> int:
    from .analytics import market
    from .recommendations import recomendar
    from .scoring import Profile
    from .transformations.skills import Taxonomy
    tax = Taxonomy(s.skills)
    snap = market.carregar(Lake(s.lake), tax.config.extracao.gold_hibrida)
    perfil = Profile.from_dict(s.profile)
    for p in ([perfil.para(a.objetivo)] if a.objetivo else perfil.por_objetivo()):
        nome = next((o.nome for o in p.objetivos if o.id == p.objetivo_id), p.objetivo_id)
        print(f"=== objetivo: {nome} ({', '.join(p.familias) or 'famílias dos filtros'})")
        for r in recomendar(snap, p, tax, s.scoring["recomendacoes"], s.filtros, utcnow())[: a.n]:
            print(f"[{r.classe}] {r.nome} (prioridade {r.prioridade}): {r.justificativa}")
    return 0


def cmd_candidatura(a, s) -> int:
    atualizar_candidatura(Lake(s.lake), a.job_id, a.status, a.nota)
    print(f"{a.job_id}: {a.status}")
    return 0


def cmd_estudo(a, s) -> int:
    r = atualizar_estudo(Lake(s.lake), a.skill, a.status, a.inicio, a.conclusao, a.evidencia)
    from .evolucao.progresso import efeito_no_perfil
    from .scoring import Profile
    efeito = efeito_no_perfil(r["nivel_no_perfil"], Profile.from_dict(s.profile).niveis.get(a.skill))
    print(f"{a.skill}: {r['status']}" + (f" ({efeito})" if efeito else ""))
    if r["aviso"]:
        print(f"⚠️ {r['aviso']}")
    print("Grave no jobradar-data (commit/push) para a próxima execução recalcular os scores.")
    return 0


def cmd_contract(a, s) -> int:
    from .publishing import exportar_schemas
    exportar_schemas(ROOT / "docs" / "contracts" / "v1", ROOT / "src" / "jobradar" / "publishing" / "schemas")
    print("schemas exportados")
    return 0


def cmd_pontuar(a, s) -> int:
    from .validacoes import validar_configuracoes
    agora = utcnow()
    run_id = a.run_id or agora.strftime("%Y%m%dT%H%M%SZ")
    validar_configuracoes(s, Lake(s.lake), run_id, incluir_privadas=True, agora=agora)
    print(f"vagas pontuadas: {pipeline.pontuar(s, agora)}")
    return 0


def cmd_reextrair(a, s) -> int:
    if a.sem_pontuacao:
        _sem_perfil(s)
    r = pipeline.reextrair(s, todas=a.todas, pontuar=not a.sem_pontuacao)
    por_skill = r.pop("por_skill")
    for k, v in r.items():
        print(f"{k}: {v}")
    mudou = por_skill[por_skill["diferenca"] != 0]
    if not mudou.empty:
        print("\nvagas por competência (antes → depois), só as que mudaram:")
        print(mudou.to_string())
    return 0


def cmd_enriquecer(a, s) -> int:
    from .semantic import enriquecer, pendentes
    from .transformations.skills import Taxonomy
    tax = Taxonomy(s.skills)
    if not tax.config.extracao.semantica.ativa and not a.forcar:
        print("camada semântica desligada (extracao.semantica.ativa: false em config/skills.yaml); "
              "use --forcar para rodar mesmo assim", file=sys.stderr)
        return 1
    lake = Lake(s.lake)
    jobs = lake.read("silver/jobs")
    sem = lake.read("silver/job_skills_semantica")
    alvo = jobs[jobs["is_canonica"].fillna(False) & jobs["descricao"].notna()] if a.todas else pendentes(jobs, sem, tax)
    agora = utcnow()
    n = enriquecer(lake, tax, alvo, lake.read("silver/job_skills"), "enriquecer-" + agora.strftime("%Y%m%dT%H%M%SZ"), agora)
    novo = lake.read("silver/job_skills_semantica")
    print(f"{n} vaga(s) processada(s); achados na tabela: {int(novo['skill_id'].notna().sum())}")
    return 0


def cmd_candidatas(a, s) -> int:
    import pandas as pd
    from .analytics.candidatas import candidatas
    from .transformations.skills import Taxonomy
    familias = [f for f in s.filtros.get("familias", []) if f != "outra"]
    df = candidatas(Lake(s.lake).read("silver/jobs"), Taxonomy(s.skills), familias, utcnow(), dias=a.dias,
                    min_vagas=a.min_vagas, limite=a.n)
    if df.empty:
        print("nenhum candidato com os filtros atuais")
        return 0
    with pd.option_context("display.width", 200, "display.max_colwidth", 90):
        print(df.to_string(index=False))
    print("\nAprovar = acrescentar padrão/conceito em config/skills.yaml (e subir `versao`); "
          "recusar = acrescentar em candidatas.ignorar.")
    return 0


def cmd_avaliacao(a, s) -> int:
    from .avaliacao import amostrar, avaliar, carregar_ouro, relatorio, salvar_ouro
    from .transformations.skills import Taxonomy
    tax = Taxonomy(s.skills)
    if a.acao == "amostrar":
        familias = [f for f in s.filtros.get("familias", []) if f != "outra"]
        conjunto = amostrar(Lake(s.lake), tax.versao, familias, a.completas, a.trechos, a.semente,
                            carregar_ouro(s.lake), a.lote or "ajuste")
        print(f"conjunto-ouro com {len(conjunto.itens)} vaga(s) em {salvar_ouro(s.lake, conjunto)}; "
              "anote `competencias` e marque `revisado: true` (regras em docs/avaliacao.md)")
        return 0
    conjunto = carregar_ouro(s.lake)
    itens = conjunto.anotados(a.incluir_rascunhos, a.lote) if conjunto else []
    if not itens:
        print("nenhuma vaga anotada" + ("" if a.incluir_rascunhos else " e revisada (use --incluir-rascunhos)"))
        return 1
    extratores = [("regras", lambda i: tax.extrair(i.titulo, i.descricao))]
    if a.base:
        import yaml
        base = Taxonomy(yaml.safe_load(Path(a.base).read_text(encoding="utf-8")))
        extratores.insert(0, (f"regras {base.versao} (base)", lambda i: base.extrair(i.titulo, i.descricao)))
    if a.semantica:
        from .semantic import ExtratorSemantico
        from .semantic.modelo import carregar_codificador
        from .transformations.skills import SkillMatch
        cfg = tax.config.extracao.semantica
        sem = ExtratorSemantico(tax, carregar_codificador(cfg), cfg.limiar, cfg.limiar_media, tuple(cfg.tipos))

        def hibrido(i):
            regras = tax.extrair(i.titulo, i.descricao)
            extra = sem.extrair(i.titulo, i.descricao, {m.skill_id for m in regras})
            return regras + [SkillMatch(x.skill_id, x.importancia, "", "embedding", x.evidencia, x.confianca, x.tipo)
                             for x in extra]
        extratores.append((f"híbrido (limiar {cfg.limiar})", hibrido))
    print("## Competências técnicas\n" + relatorio([avaliar(n, itens, f, tax) for n, f in extratores]))
    print("\n## Comportamentais e idioma\n" + relatorio(
        [avaliar(n, itens, f, tax, tipos=("comportamental", "idioma")) for n, f in extratores[-1:]]))
    return 0


def cmd_coocorrencia(a, s) -> int:
    from datetime import timedelta

    import pandas as pd
    from .analytics import coocorrencia, market
    from .transformations.skills import Taxonomy
    tax = Taxonomy(s.skills)
    snap = market.carregar(Lake(s.lake), tax.config.extracao.gold_hibrida)
    c = snap.canonicas
    familias = a.familia or [f for f in s.filtros.get("familias", []) if f != "outra"]
    m = c["familia"].isin(familias) & (pd.to_datetime(c["primeira_observacao"], utc=True)
                                       >= utcnow() - timedelta(days=a.dias))
    if a.senioridade:
        m &= c["senioridade"].isin(a.senioridade)
    cfg = s.scoring.get("coocorrencia", {})
    min_n = int(s.scoring["recomendacoes"]["min_vagas_janela"])
    tab = coocorrencia.janela(c, snap.skills, m, int(cfg.get("min_vagas_par", 10)), min_n)
    base = int(tab["base"].iloc[0]) if not tab.empty else 0
    nomes = {k.id: k.nome for k in tax.skills}
    print(f"base: {base} vagas com ao menos uma competência técnica ({a.dias} dias; famílias: {', '.join(familias)}"
          + (f"; senioridade: {', '.join(a.senioridade)}" if a.senioridade else "") + ")")
    if base < min_n:
        print(f"⚠️ amostra pequena (menos de {min_n} vagas): leia como indício, não como padrão")
    with pd.option_context("display.width", 200):
        if a.skill:
            rel = coocorrencia.relacionadas(tab, a.skill, a.incluir_pequenas)
            rel.insert(0, "competencia", rel["skill_id"].map(nomes))
            print(f"das vagas que pedem {nomes.get(a.skill, a.skill)}, quantas também pedem:")
            print(rel.drop(columns="skill_id").head(a.n).to_string(index=False) if not rel.empty else "nenhum par")
        else:
            t = tab if a.incluir_pequenas else tab[~tab["amostra_pequena"]]
            t = t.sort_values(a.ordem, ascending=False)
            print(t[["skill_a", "skill_b", "vagas_par", "confianca_a_b_pct", "confianca_b_a_pct", "lift", "jaccard"]]
                  .head(a.n).to_string(index=False) if not t.empty else "nenhum par")
    print("\nAssociação na amostra coletada, não causa. Intervalos de confiança: 95% (Wilson).")
    return 0


def cmd_saude(a, s) -> int:
    from .analytics import saude
    ind = saude.indicadores(Lake(s.lake), cfg=s.sources.get("saude"))
    al = saude.alertas(ind, s.sources.get("saude"))
    if a.json:
        print(json.dumps({"indicadores": ind, "alertas": al}, ensure_ascii=False, indent=2, default=str))
    else:
        print(saude.markdown(ind, al))
    if a.resumo_github:
        _resumo_github(saude.markdown(ind, al))
    return 0


def cmd_privacidade(a, s) -> int:
    from . import retencao
    if a.acao == "limpar":
        r = retencao.limpar(cfg=s.scoring.get("privacidade"))
        print(f"versões de currículo removidas: {r['versoes_curriculo']} · diagnósticos: {r['diagnosticos']} · "
              f"planos: {r['planos']}")
        return 0
    if not a.confirmar:
        print("apagar-tudo remove a pasta privada local inteira (currículos, diagnósticos, planos) e o resumo "
              "do currículo no lake. Não tem volta. Repita com --confirmar.", file=sys.stderr)
        return 1
    r = retencao.apagar_tudo(s.lake)
    print(f"{r['arquivos_locais']} arquivo(s) apagados em {r['pasta']}; resumo no lake: "
          f"{'removido' if r['resumo_no_lake'] else 'não havia'}")
    print("Para tirar o resumo também do histórico do git do jobradar-data, veja docs/privacidade.md.")
    return 0


def cmd_curriculo(a, s) -> int:
    from .curriculo import servico, versoes
    from .transformations.skills import Taxonomy
    tax = Taxonomy(s.skills)
    nomes = {k.id: k.nome for k in tax.skills}
    if a.acao == "importar":
        if not a.arquivo:
            print("informe o arquivo: jobradar curriculo importar CAMINHO", file=sys.stderr)
            return 1
        caminho = Path(a.arquivo)
        cv = servico.importar(caminho.read_bytes(), caminho.name, tax, nota=a.nota or "",
                              guardar_original=a.guardar_original, retencao=s.scoring.get("privacidade"))
        print(f"versão {cv.versao_id} salva em {versoes.pasta()} (fora do git)")
        print(f"{len(cv.experiencias)} experiência(s), {len(cv.projetos)} projeto(s), "
              f"{len(cv.certificacoes)} certificação(ões), {len(cv.niveis())} competência(s) com evidência")
        revisar = [i + 1 for i, e in enumerate(cv.experiencias) if e.revisar]
        if revisar:
            print(f"⚠️ revise empresa/cargo das experiências {revisar} (painel → Meu currículo, ou exportar/editar/importar)")
        return 0
    if a.acao == "versoes":
        for v in versoes.listar():
            print(f"{v['versao_id']}  {v['criado_em']:%Y-%m-%d %H:%M}  {v['experiencias']} exp · "
                  f"{v['competencias']} competências  {v['arquivo']}  {v['nota']}")
        return 0
    if a.acao in ("mostrar", "exportar"):
        cv = versoes.carregar(a.versao)
        if not cv:
            print("nenhuma versão encontrada", file=sys.stderr)
            return 1
        if a.acao == "exportar":
            print(cv.model_dump_json(indent=2))     # edite e reimporte: `curriculo importar arquivo.json`
            return 0
        print(f"versão {cv.versao_id} ({cv.origem.get('nome', '')})")
        for e in cv.experiencias:
            print(f"- {e.cargo or '?'} · {e.empresa or '?'} ({e.inicio or '?'} – {'atual' if e.atual else e.fim or '?'})"
                  + (" ⚠️ revisar" if e.revisar else ""))
            print("  competências: " + (", ".join(f"{nomes.get(c.skill_id, c.skill_id)} [{c.nivel}]" for c in e.competencias) or "—"))
        print("níveis no currículo: " + ", ".join(f"{nomes.get(k, k)}={v}" for k, v in sorted(cv.niveis().items())))
        return 0
    if a.acao == "comparar":
        ids = [v["versao_id"] for v in versoes.listar()]
        de, para = (a.versao, a.versao2) if a.versao and a.versao2 else (ids[-2:] if len(ids) >= 2 else (None, None))
        if not de:
            print("é preciso ter duas versões", file=sys.stderr)
            return 1
        print(json.dumps(versoes.comparar(versoes.carregar(de), versoes.carregar(para)), ensure_ascii=False, indent=2))
        return 0
    if a.acao == "apagar":
        if not (a.versao or a.tudo):
            print("informe a versão ou --tudo", file=sys.stderr)
            return 1
        print(f"{versoes.apagar(a.versao, tudo=a.tudo)} arquivo(s) apagado(s) de {versoes.pasta()}")
        return 0
    if a.acao == "compartilhar-resumo":
        from .evolucao import resumo_cv
        cv = versoes.carregar(a.versao)
        if not cv:
            print("nenhuma versão do currículo", file=sys.stderr)
            return 1
        destino = resumo_cv.gravar(s.lake, cv.versao_id, cv.criado_em.isoformat(), cv.taxonomia_versao, cv.niveis())
        print(f"resumo gravado em {destino}: só competência → nível ({len(cv.niveis())} competências), sem texto. "
              "Faça commit/push do jobradar-data para o Radar usar.")
        return 0
    if a.acao == "remover-resumo":
        from .evolucao import resumo_cv
        print("resumo removido" if resumo_cv.remover(s.lake) else "não havia resumo")
        return 0
    if a.acao == "historico":
        for d in versoes.historico(objetivo_id=a.objetivo):
            ad = d["aderencia"]
            print(f"{d['gerado_em'][:16]}  {d['objetivo']:<25} versão {d['versao_id'] or '—'}  perfil {ad['perfil']['valor']}"
                  f"  currículo {ad['curriculo']['valor'] if ad['curriculo'] else '—'}  sugestões {len(d.get('sugestoes', []))}")
        return 0
    # diagnostico
    for d in servico.diagnostico(s, a.objetivo, a.versao, salvar=a.salvar):
        ad = d["aderencia"]
        print(f"=== {d['objetivo']} — {d['vagas_alvo']} vagas-alvo em {d['janela_dias']} dias"
              + (" ⚠️ amostra pequena" if d["amostra_pequena"] else ""))
        print(f"aderência do perfil: {ad['perfil']['valor']} · do currículo: {ad['curriculo']['valor'] if ad['curriculo'] else '— (importe o currículo)'}")
        print("compatíveis: " + ", ".join(x["nome"] for x in d["compativeis"][:10]))
        print("declaradas no perfil e não demonstradas no currículo: "
              + (", ".join(x["nome"] for x in d["declaradas_mas_nao_demonstradas"]) or "—"))
        print("requisitos recorrentes ausentes: " + (", ".join(f"{x['nome']} ({x['pct']:.0f}%)" for x in d["requisitos_recorrentes_ausentes"]) or "—"))
        for sg in d["sugestoes"][: a.n]:
            print(f"  • {sg['texto']}")
        print(d["aviso"])
    if a.salvar:
        print(f"diagnóstico salvo no histórico ({versoes.pasta() / 'diagnosticos'})")
    return 0


def cmd_evolucao(a, s) -> int:
    from .evolucao import servico
    from .evolucao.plano import CLASSES
    if a.acao == "progresso":
        if not (a.skill and a.status):
            print("uso: jobradar evolucao progresso SKILL STATUS [--evidencia ...]", file=sys.stderr)
            return 1
        return cmd_estudo(argparse.Namespace(skill=a.skill, status=a.status, inicio=None, conclusao=None,
                                             evidencia=a.evidencia), s)
    if a.acao == "historico":
        for h in servico.historico(a.objetivo):
            print(f"{h['gerado_em'][:16]}  {h['objetivo']:<25} perfil {h['aderencia_perfil']}  currículo "
                  f"{h['aderencia_curriculo'] if h['aderencia_curriculo'] is not None else '—'}  prioritárias: "
                  f"{', '.join(h['prioritarias']) or '—'}")
        return 0
    for p in servico.planos(s, a.objetivo, salvar=a.salvar):
        print(f"=== {p['objetivo']} — {p['vagas_alvo']} vagas-alvo" + (" ⚠️ amostra pequena" if p["amostra_pequena"] else ""))
        for chave, titulo in CLASSES.items():
            itens = p["classes"][chave]
            if not itens:
                continue
            print(f"\n{titulo} ({len(itens)})")
            for i in itens[: a.n]:
                linha = f"  - {i['nome']} ({i['pct']:.0f}% das vagas-alvo"
                linha += f"; prioridade {i['prioridade']:.2f})" if chave in ("prioritaria", "em_desenvolvimento") else ")"
                if i.get("motivo"):
                    linha += f" — {i['motivo']}"
                if i.get("proximo_passo"):
                    linha += f" — próximo passo: {i['proximo_passo']}"
                print(linha)
                r = i.get("recomendacao")
                if chave == "prioritaria" and r:
                    print(f"      por quê: {r['por_que']}")
                    print("      fatores: " + ", ".join(f"{k} {v:.2f}" for k, v in i["decomposicao"].items()))
                    if r["tecnologias_associadas"]:
                        print("      aparece com: " + ", ".join(f"{j['nome']} ({j['confianca_pct']:.0f}%)" for j in r["tecnologias_associadas"]))
                    if r["estudar"]:
                        print("      estudar (sugestão): " + "; ".join(r["estudar"]))
                    if r["projeto"]:
                        print(f"      projeto (sugestão): {r['projeto']}")
                    if r["evidencia_curriculo"]:
                        print(f"      no currículo: {r['evidencia_curriculo']}")
        print("\n" + p["aviso"])
    if a.salvar:
        print("plano salvo no histórico local (fora do git)")
    return 0


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="jobradar", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lake", help="pasta do histórico (padrão: $JOBRADAR_LAKE ou ./lake)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run"); r.add_argument("--run-id"); r.add_argument("--report")
    r.add_argument("--sem-pontuacao", action="store_true",
                   help="não lê o perfil (o score roda no workflow privado: jobradar pontuar)")
    r.set_defaults(f=cmd_run)
    pt = sub.add_parser("pontuar", help="score por vaga e objetivo (workflow privado)")
    pt.add_argument("--run-id"); pt.set_defaults(f=cmd_pontuar)
    pb = sub.add_parser("publish"); pb.add_argument("--out", default="public_out"); pb.add_argument("--run-id")
    pb.set_defaults(f=cmd_publish)
    n = sub.add_parser("notify"); n.add_argument("--dry-run", action="store_true"); n.add_argument("--html-out")
    n.add_argument("--run-id"); n.add_argument("--pular-se-vazio", action="store_true")
    n.add_argument("--turno", help="madrugada|manha|tarde|noite: no turno do Radar, envia o Radar no lugar")
    n.set_defaults(f=cmd_notify)
    rd = sub.add_parser("radar", help="JobRadar — Seu Radar Profissional (e-mail diário)")
    rd.add_argument("--dry-run", action="store_true", help="gera a prévia em HTML; não envia nem registra")
    rd.add_argument("--html-out"); rd.add_argument("--forcar", action="store_true", help="ignora horário/dia/duplicidade")
    rd.add_argument("--turno"); rd.add_argument("--run-id"); rd.set_defaults(f=cmd_radar)
    sm = sub.add_parser("semanal", help="JobRadar — Relatório Semanal de Evolução Profissional")
    sm.add_argument("--dry-run", action="store_true"); sm.add_argument("--html-out")
    sm.add_argument("--forcar", action="store_true"); sm.add_argument("--turno"); sm.add_argument("--run-id")
    sm.set_defaults(f=cmd_semanal)
    me = sub.add_parser("mensal", help="Diagnóstico Mensal de Career Intelligence")
    me.add_argument("--dry-run", action="store_true"); me.add_argument("--html-out")
    me.add_argument("--forcar", action="store_true"); me.add_argument("--turno"); me.add_argument("--run-id")
    me.set_defaults(f=cmd_mensal)
    st = sub.add_parser("status"); st.add_argument("-n", type=int, default=10); st.set_defaults(f=cmd_status)
    em = sub.add_parser("empresas", help="catálogo de empresas monitoradas e situação da coleta")
    em.add_argument("acao", choices=["listar"])
    em.add_argument("--status", choices=["candidata", "ativa", "pausada", "descartada"])
    em.add_argument("--ats")
    em.set_defaults(f=cmd_empresas)
    rc = sub.add_parser("recomendacoes"); rc.add_argument("-n", type=int, default=15)
    rc.add_argument("--objetivo", help="id do objetivo do perfil (padrão: todos, separados)")
    rc.set_defaults(f=cmd_recomendacoes)
    c = sub.add_parser("candidatura"); c.add_argument("job_id"); c.add_argument("status", choices=APPLICATION_STATUSES)
    c.add_argument("--nota"); c.set_defaults(f=cmd_candidatura)
    e = sub.add_parser("estudo"); e.add_argument("skill"); e.add_argument("status", choices=STUDY_STATUSES)
    e.add_argument("--inicio"); e.add_argument("--conclusao"); e.add_argument("--evidencia"); e.set_defaults(f=cmd_estudo)
    ct = sub.add_parser("contract"); ct.add_argument("acao", choices=["export"]); ct.set_defaults(f=cmd_contract)
    rx = sub.add_parser("reextrair", help="reaplica a taxonomia atual ao histórico")
    rx.add_argument("--todas", action="store_true", help="inclusive vagas já na versão atual")
    rx.add_argument("--sem-pontuacao", action="store_true"); rx.set_defaults(f=cmd_reextrair)
    en = sub.add_parser("enriquecer", help="camada semântica local nas vagas pendentes")
    en.add_argument("--todas", action="store_true"); en.add_argument("--forcar", action="store_true",
                                                                     help="roda mesmo com a camada desligada")
    en.set_defaults(f=cmd_enriquecer)
    cp = sub.add_parser("competencias"); cp_sub = cp.add_subparsers(dest="acao", required=True)
    cd = cp_sub.add_parser("candidatas", help="termos frequentes que a taxonomia não cobre")
    cd.add_argument("--dias", type=int, default=90); cd.add_argument("--min-vagas", type=int, default=5)
    cd.add_argument("-n", type=int, default=40); cd.set_defaults(f=cmd_candidatas)
    av = sub.add_parser("avaliacao"); av.add_argument("acao", choices=["amostrar", "medir"])
    av.add_argument("--completas", type=int, default=25); av.add_argument("--trechos", type=int, default=15)
    av.add_argument("--semente", type=int, default=42); av.add_argument("--lote", default=None,
                                                                        help="amostrar: nome do lote (padrão ajuste); medir: filtra")
    av.add_argument("--incluir-rascunhos", action="store_true"); av.add_argument("--base", help="YAML de outra taxonomia para comparar")
    av.add_argument("--semantica", action="store_true", help="mede também o híbrido (requer .[semantica])")
    av.set_defaults(f=cmd_avaliacao)
    co = sub.add_parser("coocorrencia", help="competências que aparecem juntas")
    co.add_argument("--skill", help="id da competência (ex.: airflow): mostra as que aparecem com ela")
    co.add_argument("--familia", action="append", help="pode repetir; padrão: famílias de dados")
    co.add_argument("--senioridade", action="append", help="pode repetir")
    co.add_argument("--dias", type=int, default=90); co.add_argument("-n", type=int, default=20)
    co.add_argument("--ordem", choices=["jaccard", "lift", "vagas_par"], default="jaccard")
    co.add_argument("--incluir-pequenas", action="store_true", help="mostra também pares abaixo do mínimo")
    co.set_defaults(f=cmd_coocorrencia)
    cv = sub.add_parser("curriculo", help="currículo privado (só local, fora do git)")
    cv.add_argument("acao", choices=["importar", "versoes", "mostrar", "exportar", "comparar", "apagar",
                                     "diagnostico", "historico", "compartilhar-resumo", "remover-resumo"])
    cv.add_argument("arquivo", nargs="?", help="importar: PDF, DOCX, TXT ou JSON exportado e editado")
    cv.add_argument("--versao"); cv.add_argument("--versao2"); cv.add_argument("--objetivo")
    cv.add_argument("--nota", help="descrição da versão"); cv.add_argument("--guardar-original", action="store_true")
    cv.add_argument("--tudo", action="store_true", help="apagar: remove TODA a pasta de currículo")
    cv.add_argument("--salvar", action="store_true", help="diagnostico: guarda no histórico local")
    cv.add_argument("-n", type=int, default=8)
    cv.set_defaults(f=cmd_curriculo)
    sd = sub.add_parser("saude", help="indicadores e alertas da operação (só agregados)")
    sd.add_argument("--json", action="store_true"); sd.add_argument("--resumo-github", action="store_true")
    sd.set_defaults(f=cmd_saude)
    pv = sub.add_parser("privacidade", help="retenção e apagamento dos dados pessoais locais")
    pv.add_argument("acao", choices=["limpar", "apagar-tudo"])
    pv.add_argument("--confirmar", action="store_true", help="apagar-tudo: confirma (não tem volta)")
    pv.set_defaults(f=cmd_privacidade)
    ev = sub.add_parser("evolucao", help="Minha Evolução Profissional (privado)")
    ev.add_argument("acao", choices=["plano", "progresso", "historico"])
    ev.add_argument("skill", nargs="?"); ev.add_argument("status", nargs="?", choices=STUDY_STATUSES)
    ev.add_argument("--objetivo"); ev.add_argument("--evidencia", help="onde demonstrou (link, projeto, empresa)")
    ev.add_argument("--salvar", action="store_true"); ev.add_argument("-n", type=int, default=8)
    ev.set_defaults(f=cmd_evolucao)

    a = p.parse_args(argv)
    # No Windows, saída redirecionada (arquivo, pipe, agendador) usa cp1252 e quebra nos ✅/❌ do relatório.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from .seguranca import instalar_filtro
    instalar_filtro()   # segunda barreira: chave, senha ou token nunca aparecem no log
    # O httpx registra a URL completa de cada requisição, e a da Adzuna leva app_key na query.
    if not a.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    s = carregar(lake=a.lake)
    sys.exit(a.f(a, s))


if __name__ == "__main__":
    main()
