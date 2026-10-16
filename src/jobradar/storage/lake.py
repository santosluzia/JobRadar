"""Lake em disco: Parquet por tabela + bronze em JSON.gz particionado.

O diretório do lake é, em produção, um clone do repositório privado `jobradar-data`.
Este módulo não sabe nada de git: só lê e grava arquivos. Quem sincroniza é o workflow,
o que mantém a persistência trocável (ex.: Cloudflare R2) sem tocar no domínio.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .schemas import TABLES


class Lake:
    def __init__(self, root: Path):
        self.root = Path(root)

    # -------- tabelas --------
    def path(self, table: str) -> Path:
        if table not in TABLES:
            raise KeyError(f"tabela desconhecida: {table}")
        return self.root / f"{table}.parquet"

    def read(self, table: str) -> pd.DataFrame:
        p = self.path(table)
        schema = TABLES[table]
        if not p.exists():
            return schema.empty_table().to_pandas()
        df = pq.read_table(p).to_pandas()
        for campo in schema.names:  # evolução de schema: coluna nova aparece como nula
            if campo not in df.columns:
                df[campo] = None
        return df[schema.names]

    def write(self, table: str, df: pd.DataFrame) -> None:
        p = self.path(table)
        p.parent.mkdir(parents=True, exist_ok=True)
        schema = TABLES[table]
        df = df.reindex(columns=schema.names)
        tabela = pa.Table.from_pandas(df, schema=schema, preserve_index=False, safe=False)
        tmp = p.with_suffix(".parquet.tmp")
        pq.write_table(tabela, tmp, compression="zstd")
        os.replace(tmp, p)  # troca atômica: um crash nunca deixa meia tabela

    def append(self, table: str, df: pd.DataFrame) -> None:
        if df.empty:
            return
        atual = self.read(table)
        self.write(table, pd.concat([atual, df], ignore_index=True) if not atual.empty else df)

    # -------- bronze --------
    def bronze_path(self, source: str, dia: date, run_id: str) -> Path:
        return self.root / "bronze" / f"source={source}" / f"dt={dia.isoformat()}" / f"run={run_id}.json.gz"

    def write_bronze(self, source: str, dia: date, run_id: str, envelope: dict[str, Any]) -> Path:
        p = self.bronze_path(source, dia, run_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(p, "wt", encoding="utf-8") as f:
            json.dump(envelope, f, ensure_ascii=False, default=str)
        return p

    def read_bronze(self, path: Path) -> dict[str, Any]:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)

    def prune_bronze(self, hoje: date, dias: int) -> int:
        """Retenção: apaga partições dt= mais antigas que `dias`."""
        limite = hoje - timedelta(days=dias)
        removidas = 0
        for d in (self.root / "bronze").glob("source=*/dt=*"):
            try:
                dia = date.fromisoformat(d.name.removeprefix("dt="))
            except ValueError:
                continue
            if dia < limite:
                shutil.rmtree(d)
                removidas += 1
        return removidas

    def ensure_layout(self) -> None:
        for sub in ("bronze", "silver", "gold", "meta", "private"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        readme = self.root / "README.md"
        if not readme.exists():
            readme.write_text(
                "# jobradar-data (PRIVADO)\n\nHistórico do JobRadar. Gerado pelo pipeline; não edite à mão,\n"
                "exceto `private/profile.yaml`. Não torne este repositório público.\n", encoding="utf-8")


def utcnow() -> datetime:
    from datetime import timezone
    return datetime.now(timezone.utc)
