from datetime import datetime, timezone

import pandas as pd

from jobradar.analytics.selection import inicio_periodo, publicadas_no_periodo

# 17/10/2026 06:47 em São Paulo (UTC-3)
AGORA = datetime(2026, 10, 17, 9, 47, tzinfo=timezone.utc)


def test_inicio_do_periodo_e_meia_noite_de_sao_paulo():
    assert inicio_periodo("hoje", AGORA).isoformat() == "2026-10-17T00:00:00-03:00"
    assert inicio_periodo("ontem_e_hoje", AGORA).isoformat() == "2026-10-16T00:00:00-03:00"
    assert inicio_periodo("7_dias", AGORA).isoformat() == "2026-10-11T00:00:00-03:00"
    assert inicio_periodo("qualquer_data", AGORA) is None


def test_publicadas_no_periodo_usa_o_dia_de_sao_paulo():
    jobs = pd.DataFrame({"publicada_em": [
        "2026-10-17T05:00:00Z",   # 02:00 de hoje em SP
        "2026-10-17T01:00:00Z",   # 22:00 de ontem em SP (já é 17/10 em UTC)
        "2026-10-16T02:59:00Z",   # 23:59 de anteontem em SP
        None,
    ]})
    assert publicadas_no_periodo(jobs, "hoje", AGORA).tolist() == [True, False, False, False]
    assert publicadas_no_periodo(jobs, "ontem_e_hoje", AGORA).tolist() == [True, True, False, False]
    assert publicadas_no_periodo(jobs, "qualquer_data", AGORA).tolist() == [True, True, True, True]
