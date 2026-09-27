"""Gráficos como imagem para os atalhos do menu (que não passam pelo /chat)."""
from __future__ import annotations

from ..services import graficos


def gerar(dados: dict) -> dict:
    return {"imagens": graficos.gerar(dados)}
