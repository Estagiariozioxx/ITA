"""Varreduras sobre vários clientes: escolher a persona da demo, achar quem tem cada gatilho e o
job de alertas (Cloud Scheduler). Um cliente com dado ruim nunca derruba a varredura."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from typing import Any

import pandas as pd

from .. import config
from ..repositories import get_repo
from ..services import engine, gatilhos

log = logging.getLogger("ita")
_cache_gatilhos: dict[int, tuple[float, dict]] = {}


def _varrer(limite: int, calcular: Callable[[pd.DataFrame], Any], em_lote: bool = False) -> Iterator[tuple[str, Any]]:
    """(id, calcular(extrato preparado)) de cada cliente; em lote = 1 query só no BigQuery."""
    repo = get_repo()
    ids = repo.usuarios(limite)
    brutos = repo.extratos(ids).items() if em_lote else ((uid, None) for uid in ids)
    for uid, df in brutos:
        try:
            yield uid, calcular(engine.preparar(df if df is not None else repo.extrato(uid)))
        except Exception as e:  # noqa: BLE001 - varredura: registra e segue para o próximo cliente
            log.warning("falha em %s: %s", uid, e)


def job_alertas(limite: int) -> dict:
    saida = [{"id_usuario": uid, "alertas": [{k: v for k, v in a.items() if k != "dados"} for a in al]}
             for uid, al in _varrer(limite, engine.alertas) if al]
    return {"clientes_avaliados": limite, "com_alerta": len(saida), "resultado": saida}


def candidatos(limite: int) -> dict:
    out = [{"id_usuario": uid, **pontos} for uid, pontos in _varrer(limite, engine.pontuar_para_demo)]
    out.sort(key=lambda x: (not x["bom_para_demo"], -x["parcelas_abertas"]))
    return {"candidatos": out}


def gatilhos_por_tipo(limite: int) -> dict:
    """Para cada gatilho, os clientes em que ele acontece de verdade (cache de CACHE_TTL segundos)."""
    hit = _cache_gatilhos.get(limite)
    if hit and time.time() - hit[0] < config.CACHE_TTL:
        return hit[1]
    por_tipo: dict[str, list[str]] = {t: [] for t in gatilhos.TIPOS}
    detectar = lambda d: gatilhos.detectar(d, engine.perfil(d))  # noqa: E731
    for uid, lista in _varrer(limite, detectar, em_lote=True):
        for g in lista:
            if g["ativo"]:
                por_tipo[g["tipo"]].append(uid)
    out = {"clientes_avaliados": limite, "por_tipo": por_tipo}
    _cache_gatilhos[limite] = (time.time(), out)
    return out
