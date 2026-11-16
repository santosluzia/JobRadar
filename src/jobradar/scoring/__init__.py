import pandas as pd

from .fit import FitResult, calcular
from .profile import NIVEIS, Objetivo, Profile


def melhor_por_vaga(scores: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por vaga: a do objetivo em que ela pontua mais (para listas e e-mail).
    A análise por objetivo usa a tabela inteira, filtrando `objetivo_id`."""
    if scores.empty:
        return scores
    return (scores.sort_values(["score", "objetivo_id"], ascending=[False, True], na_position="last")
            .drop_duplicates("job_id").reset_index(drop=True))


__all__ = ["NIVEIS", "Objetivo", "Profile", "FitResult", "calcular", "melhor_por_vaga"]
