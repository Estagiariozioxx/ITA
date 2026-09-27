"""O que todos os casos de uso precisam: o extrato do cliente, ou 404 se ele não existe."""
from __future__ import annotations

import pandas as pd
from fastapi import HTTPException

from ..repositories import ClienteNaoEncontrado, get_repo
from ..services import engine


def garantir_cliente(uid: str) -> None:
    """404 cedo, antes de gastar qualquer processamento com um cliente que não existe."""
    extrato_preparado(uid)


def extrato_preparado(uid: str) -> pd.DataFrame:
    try:
        return engine.preparar(get_repo().extrato(uid))
    except ClienteNaoEncontrado:
        raise HTTPException(404, f"cliente {uid} não encontrado") from None
