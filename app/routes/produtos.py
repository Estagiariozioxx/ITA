"""Simular e contratar (demonstração) os produtos ofertados, sem sair da conversa."""
from fastapi import APIRouter

from ..controllers import produtos
from ..schemas import ProdutoIn

router = APIRouter(prefix="/clientes/{uid}/produtos", tags=["produtos"])


@router.post("/simular")
def simular(uid: str, body: ProdutoIn):
    """Parcela, custo total, capacidade de pagamento e saldo em 90 dias."""
    return produtos.simular(uid, body)


@router.post("/contratar")
def contratar(uid: str, body: ProdutoIn):
    """Contratação de DEMONSTRAÇÃO: refaz a simulação e, se couber, devolve um protocolo de proposta."""
    return produtos.contratar(uid, body)
