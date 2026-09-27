"""Gráficos como imagem para dados já calculados."""
from fastapi import APIRouter

from ..controllers import graficos

router = APIRouter(tags=["graficos"])


@router.post("/graficos")
def gerar(dados: dict):
    """PNGs para as mesmas chaves de dados_tela (projecao, ate_salario, gastos_categorias, simulacao,
    dinheiro_extra, comparacao). Usado pelos atalhos do menu, que não passam pelo /chat."""
    return graficos.gerar(dados)
