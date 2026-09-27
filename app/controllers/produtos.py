"""Simular e contratar (demonstração) os produtos ofertados, dentro da conversa."""
from __future__ import annotations

import logging

from ..schemas import ProdutoIn
from ..services import contratacao
from .comum import extrato_preparado

log = logging.getLogger("ita")


def simular(uid: str, body: ProdutoIn) -> dict:
    return contratacao.simular(extrato_preparado(uid), body.produto, body.valor, body.prazo_meses,
                               body.entrada, body.taxa)


def contratar(uid: str, body: ProdutoIn) -> dict:
    r = contratacao.contratar(extrato_preparado(uid), uid, body.produto, body.valor, body.prazo_meses,
                              body.entrada, body.taxa)
    log.info("contratacao %s %s: %s", uid, body.produto, r.get("protocolo") or r.get("motivo"))
    return r
