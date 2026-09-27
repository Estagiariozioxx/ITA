"""Camada de dados: lê o extrato de um cliente do BigQuery (ou de um CSV local)."""
from __future__ import annotations

import time
from functools import lru_cache

import pandas as pd

from .. import config

COLUNAS = [
    "id_usuario", "anomesdia", "anomes", "tipo", "descr", "vlr",
    "nom_cate_macro", "nom_cate_micro", "saldo_apos",
    "parcela_atual", "parcela_total",
]


class ClienteNaoEncontrado(Exception):
    pass


class BigQueryRepo:
    def __init__(self) -> None:
        from google.cloud import bigquery  # import tardio: testes locais não precisam

        self._bq = bigquery
        self.client = bigquery.Client(project=config.PROJECT_ID)
        self._cache: dict[str, tuple[float, pd.DataFrame]] = {}

    def extrato(self, id_usuario: str) -> pd.DataFrame:
        hit = self._cache.get(id_usuario)
        if hit and time.time() - hit[0] < config.CACHE_TTL:
            return hit[1]
        sql = f"""
            SELECT {", ".join(COLUNAS)}
            FROM `{config.BQ_TABLE}`
            WHERE id_usuario = @u
            ORDER BY anomesdia
        """
        job = self.client.query(
            sql,
            job_config=self._bq.QueryJobConfig(
                query_parameters=[
                    self._bq.ScalarQueryParameter("u", "STRING", id_usuario)
                ]
            ),
        )
        df = job.to_dataframe()
        if df.empty:
            raise ClienteNaoEncontrado(id_usuario)
        self._cache[id_usuario] = (time.time(), df)
        return df

    def extratos(self, ids: list[str]) -> dict[str, pd.DataFrame]:
        """Extratos de vários clientes numa única query (e já guarda no cache)."""
        agora = time.time()
        faltam = [u for u in ids if not (u in self._cache and agora - self._cache[u][0] < config.CACHE_TTL)]
        if faltam:
            sql = f"""
                SELECT {", ".join(COLUNAS)}
                FROM `{config.BQ_TABLE}`
                WHERE id_usuario IN UNNEST(@ids)
                ORDER BY id_usuario, anomesdia
            """
            job = self.client.query(sql, job_config=self._bq.QueryJobConfig(
                query_parameters=[self._bq.ArrayQueryParameter("ids", "STRING", faltam)]))
            for uid, df in job.to_dataframe().groupby("id_usuario"):
                self._cache[uid] = (agora, df.reset_index(drop=True))
        return {u: self._cache[u][1] for u in ids if u in self._cache}

    def usuarios(self, limite: int = 50) -> list[str]:
        sql = f"""
            SELECT DISTINCT id_usuario FROM `{config.BQ_TABLE}`
            ORDER BY id_usuario LIMIT {int(limite)}
        """
        return [r.id_usuario for r in self.client.query(sql).result()]


class CsvRepo:
    """Para rodar localmente sem GCP (DATA_SOURCE=csv)."""

    def __init__(self, caminho: str) -> None:
        self.df = pd.read_csv(caminho)

    def extrato(self, id_usuario: str) -> pd.DataFrame:
        df = self.df[self.df["id_usuario"] == id_usuario]
        if df.empty:
            raise ClienteNaoEncontrado(id_usuario)
        return df.copy()

    def extratos(self, ids: list[str]) -> dict[str, pd.DataFrame]:
        sub = self.df[self.df["id_usuario"].isin(ids)]
        return {u: g.copy() for u, g in sub.groupby("id_usuario")}

    def usuarios(self, limite: int = 50) -> list[str]:
        return sorted(self.df["id_usuario"].unique().tolist())[:limite]


@lru_cache(maxsize=1)
def get_repo():
    if config.DATA_SOURCE == "csv":
        return CsvRepo(config.CSV_PATH)
    return BigQueryRepo()
