"""Sugestões de evolução do currículo — por REGRA, cada uma com o dado e a evidência que a justificam.

Regra de ouro: o sistema aponta ONDE e POR QUÊ melhorar, mas nunca escreve por você responsabilidade,
número, ferramenta ou nível que não esteja no seu texto. Toda sugestão de "incluir" vem condicionada
("se você usou…", "se houver…").
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..scoring import Profile
from ..transformations.skills import Taxonomy
from .estrutura import Curriculo

ROTULO_NIVEL = {"profissional": "profissional", "projeto": "em projeto", "em_desenvolvimento": "em desenvolvimento"}


@dataclass
class Sugestao:
    tipo: str            # descrever_uso | nomear_ferramenta | resultado | valorizar_experiencia |
                         # reorganizar_competencias | projeto_para_comprovar | descrever_projeto
    prioridade: float    # demanda relativa (0–1): ordem de exibição, não nota
    texto: str
    competencia: str | None = None
    base: dict[str, Any] = field(default_factory=dict)   # números que sustentam a sugestão

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def gerar(diag: dict[str, Any], cv: Curriculo | None, profile: Profile, tax: Taxonomy) -> list[Sugestao]:
    nome = {s.id: s.nome for s in tax.skills}
    n = diag["vagas_alvo"]
    sug: list[Sugestao] = []
    if not cv:
        return [Sugestao("importar_curriculo", 1.0, "Importe o currículo para comparar o que ele demonstra com o "
                         "que as vagas-alvo pedem.")]

    # 1. Você declara no perfil, o currículo não mostra → descrever onde usou
    for d in diag["declaradas_mas_nao_demonstradas"]:
        onde = f" (no perfil: “{d['evidencias_perfil'][0]}”)" if d["evidencias_perfil"] else ""
        estado = {"sem_evidencia": "não aparece no currículo", "declarada": "aparece só na lista de competências",
                  "parcial": "aparece só de forma indireta (conceito, curso ou certificação)"}[d["nivel_curriculo"]]
        sug.append(Sugestao(
            "descrever_uso", d["pct"] / 100,
            f"Você marcou {d['nome']} como {ROTULO_NIVEL.get(d['nivel_perfil'], d['nivel_perfil'])} no perfil{onde}, "
            f"mas ela {estado}. {d['pct']:.0f}% das {n} vagas-alvo pedem {d['nome']}. Se você a usou numa experiência "
            "ou projeto, descreva ali onde e para quê.",
            d["skill_id"], {"pct_vagas": d["pct"], "vagas_alvo": n, "nivel_perfil": d["nivel_perfil"],
                            "nivel_curriculo": d["nivel_curriculo"]}))

    # 2. Aparece por conceito, mas sem o nome que as vagas usam → nomear a ferramenta
    for d in diag["competencias"]:
        evid = d["evidencias_curriculo"]
        if d["pct"] < 5 or not evid or any(e["metodo"] == "termo" and e["secao"] in ("experiencia", "projeto") for e in evid):
            continue
        conc = next((e for e in evid if e["metodo"] == "conceito" and e["secao"] in ("experiencia", "projeto")), None)
        if conc:
            termo = d["termo_mais_usado_nas_vagas"]
            sug.append(Sugestao(
                "nomear_ferramenta", d["pct"] / 100,
                f"Em “{conc['onde']}”, a frase “{conc['frase']}” indica {d['nome']}, mas o nome não aparece. "
                f"{d['pct']:.0f}% das vagas-alvo pedem {d['nome']}" + (f" (termo mais usado: “{termo}”)" if termo else "")
                + ". Se for o caso, cite a tecnologia pelo nome.",
                d["skill_id"], {"pct_vagas": d["pct"], "termo_nas_vagas": termo}))

    # 3. Experiências: resultado mensurável e destaque
    pct = {d["skill_id"]: d["pct"] for d in diag["competencias"]}
    for e in diag["experiencias"]:
        if e["relevancia"] < 10:     # soma dos % das competências da experiência: pouca relação com o objetivo
            continue
        principais = ", ".join(nome.get(s, s) for s in e["competencias"][:4])
        if not e["tem_resultado"]:
            sug.append(Sugestao(
                "resultado", min(e["relevancia"] / 200, 1.0),
                f"Nenhuma frase de “{e['onde']}” traz resultado mensurável. Se houver um que você possa comprovar "
                "(tempo, volume, custo, qualidade, usuários), inclua; não estime o que não foi medido.",
                None, {"experiencia": e["onde"], "competencias": e["competencias"]}))
        if e["linhas"] <= 2 and e["competencias"]:
            sug.append(Sugestao(
                "valorizar_experiencia", min(e["relevancia"] / 100, 1.0),
                f"“{e['onde']}” demonstra {principais}, competências pedidas em "
                f"{', '.join(f'{pct.get(s, 0):.0f}%' for s in e['competencias'][:4])} das vagas-alvo, mas tem só "
                f"{e['linhas']} linha(s) de descrição. Vale detalhar as atividades técnicas que você realmente fez.",
                None, {"experiencia": e["onde"], "linhas": e["linhas"], "relevancia": e["relevancia"]}))

    # 4. Ordem da lista de competências × demanda do objetivo
    declaradas = [a.skill_id for a in cv.competencias_declaradas]
    if len(declaradas) >= 3:
        ideal = sorted(declaradas, key=lambda s: -pct.get(s, 0))
        if ideal[:3] != declaradas[:3] and any(pct.get(s, 0) for s in ideal[:3]):
            sug.append(Sugestao(
                "reorganizar_competencias", 0.3,
                "Para este objetivo, a lista de competências ficaria mais forte nesta ordem (mais pedidas primeiro): "
                + ", ".join(f"{nome.get(s, s)} ({pct.get(s, 0):.0f}%)" for s in ideal) + ".",
                None, {"atual": declaradas, "sugerida": ideal}))

    # 5. A desenvolver que dá para provar com projeto
    for d in diag["a_desenvolver"]:
        skill = tax.por_id.get(d["skill_id"])
        if not skill or not skill.projeto:
            continue
        ponte = d.get("aparece_com") or []
        extra = (" Nas vagas-alvo, " + "; ".join(
            f"das que pedem {nome.get(p['tem'], p['tem'])} (que você já tem), {p['confianca_pct']:.0f}% também pedem "
            f"{d['nome']}" for p in ponte[:2]) + ": um projeto pode combinar as duas.") if ponte else ""
        sug.append(Sugestao(
            "projeto_para_comprovar", d["pct"] / 100,
            f"{d['nome']} é pedida em {d['pct']:.0f}% das vagas-alvo e não tem evidência forte no perfil nem no "
            f"currículo. Um projeto prático e público ajudaria a demonstrá-la.{extra}",
            d["skill_id"], {"pct_vagas": d["pct"], "aparece_com": ponte}))

    # 6. Projetos sem tecnologia identificada
    for p in cv.projetos:
        if not p.competencias:
            sug.append(Sugestao("descrever_projeto", 0.2,
                                f"No projeto “{p.titulo}”, nenhuma tecnologia foi identificada. Se ele usa ferramentas "
                                "da área, cite quais e o que você construiu com elas.", None, {"projeto": p.titulo}))

    vistos, unicas = set(), []
    for s in sorted(sug, key=lambda x: -x.prioridade):
        chave = (s.tipo, s.competencia, s.base.get("experiencia"))
        if chave not in vistos:
            vistos.add(chave)
            unicas.append(s)
    return unicas
