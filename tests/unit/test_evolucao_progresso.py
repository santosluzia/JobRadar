"""Etapa 4 — progresso e perfil efetivo (regras puras)."""
import pandas as pd
import pytest

from jobradar.evolucao.plano import _cargo, _fatores
from jobradar.evolucao.progresso import nivel_do_progresso, normalizar_status, perfil_efetivo_dict
from jobradar.scoring import Profile

PERFIL = {"objetivos": [{"id": "eng", "familias": ["engenharia_dados"]}],
          "competencias": [{"skill": "sql", "nivel": "profissional"}, {"skill": "kafka", "nivel": "nao_dominada"}]}


def _prog(*linhas):
    return pd.DataFrame([{"skill_id": s, "status": st, "evidencia": ev} for s, st, ev in linhas])


@pytest.mark.parametrize("status,evidencia,esperado", [
    ("nao_iniciada", None, None),
    ("em_estudo", None, "em_desenvolvimento"),
    ("em_pratica", None, "em_desenvolvimento"),
    ("demonstrada_em_projeto", "github.com/x/y", "projeto"),
    ("demonstrada_em_projeto", None, "em_desenvolvimento"),        # sem evidência não sobe
    ("comprovada_profissional", "Empresa X, 2025", "profissional"),
    ("comprovada_profissional", "  ", "em_desenvolvimento"),
    ("concluido", "certificado", "em_desenvolvimento"),           # curso concluído NÃO é experiência
])
def test_nivel_do_progresso(status, evidencia, esperado):
    assert nivel_do_progresso(status, evidencia) == esperado


def test_status_antigos_sao_convertidos_e_invalidos_recusados():
    assert [normalizar_status(s) for s in ("planejado", "em_andamento", "concluido", "pausado")] == \
        ["nao_iniciada", "em_estudo", "em_estudo", "pausada"]
    with pytest.raises(ValueError):
        normalizar_status("terminado")


def test_perfil_efetivo_so_sobe_nunca_rebaixa():
    d = perfil_efetivo_dict(PERFIL, _prog(("sql", "em_estudo", None), ("kafka", "em_pratica", None),
                                          ("dbt", "demonstrada_em_projeto", "github.com/x/dbt")))
    p = Profile.from_dict(d)
    assert p.nivel("sql") == "profissional"           # declarado como profissional: não rebaixa
    assert p.nivel("kafka") == "em_desenvolvimento"   # sobe de não dominada
    assert p.nivel("dbt") == "projeto" and any("github.com/x/dbt" in e for e in p.evidencias["dbt"])


def test_sem_progresso_o_hash_do_perfil_nao_muda():
    assert Profile.from_dict(perfil_efetivo_dict(PERFIL, _prog())).hash == Profile.from_dict(PERFIL).hash
    mudou = Profile.from_dict(perfil_efetivo_dict(PERFIL, _prog(("dbt", "em_estudo", None))))
    assert mudou.hash != Profile.from_dict(PERFIL).hash    # progresso muda o hash → scores recalculados


def test_fatores_relativos_e_crescimento_inconclusivo():
    topo = {"pct": 50.0, "req": 40.0, "sen": 60.0}
    f, notas = _fatores(pct=25, pct_req=20, pct_out=5, pct_sen=30, var=None, tendencia="inconclusiva",
                        esforco=0.6, projeto=True, cmax=20, topo=topo)
    assert f["frequencia"] == 0.5 and f["exigencia"] == 0.5 and f["senioridade"] == 0.5
    assert f["compatibilidade"] == pytest.approx(25 / 30, abs=1e-3) and f["crescimento"] == 0.0
    assert any("inconclusivo" in n for n in notas)
    f2, _ = _fatores(25, 20, 5, None, 10, "alta", 0.6, False, 20, topo)
    assert f2["crescimento"] == 0.5 and f2["comprovacao"] == 0.0 and f2["senioridade"] == 0.5


def test_nome_de_cargo_sem_senioridade_e_ruido():
    assert _cargo("Engenheiro(a) de Dados Sênior - Remoto") == "engenheiro de dados"


def test_efeito_no_perfil_diz_quando_o_nivel_declarado_continua_valendo():
    from jobradar.evolucao.progresso import efeito_no_perfil
    assert efeito_no_perfil(None, "profissional") is None
    assert efeito_no_perfil("em_desenvolvimento", None) == "conta no perfil como em_desenvolvimento"
    assert efeito_no_perfil("projeto", "em_desenvolvimento") == "conta no perfil como projeto"
    assert "já declara profissional" in efeito_no_perfil("em_desenvolvimento", "profissional")
    assert "já declara projeto" in efeito_no_perfil("projeto", "projeto")
