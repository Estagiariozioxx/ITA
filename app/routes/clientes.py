"""Dados determinísticos do cliente (sem LLM): alimentam as telas, os atalhos e os gráficos."""
from fastapi import APIRouter, Query

from ..controllers import clientes
from ..schemas import ComparacaoIn, SimulacaoIn

router = APIRouter(prefix="/clientes", tags=["clientes"])


@router.get("")
def listar_clientes(limite: int = Query(20, ge=1, le=1000)):
    return clientes.listar(limite)


@router.get("/{uid}/perfil")
def perfil(uid: str):
    return clientes.perfil(uid)


@router.get("/{uid}/projecao")
def projecao(uid: str, dias: int = Query(90, ge=7, le=365)):
    return clientes.projecao(uid, dias)


@router.post("/{uid}/simular")
def simular(uid: str, body: SimulacaoIn):
    return clientes.simular(uid, body)


@router.post("/{uid}/comparar")
def comparar(uid: str, body: ComparacaoIn):
    return clientes.comparar(uid, body)


@router.get("/{uid}/alertas")
def alertas(uid: str):
    return clientes.alertas(uid)


@router.get("/{uid}/ate-salario")
def ate_salario(uid: str, gasto: float = Query(0, ge=0, le=1_000_000)):
    """"Até o próximo salário dá?": saldo até a véspera da renda, com e sem um gasto à vista hoje."""
    return clientes.ate_salario(uid, gasto)


@router.get("/{uid}/movimentacoes")
def movimentacoes(uid: str, limite: int = Query(8, ge=1, le=50)):
    """Últimos lançamentos do extrato."""
    return clientes.movimentacoes(uid, limite)


@router.get("/{uid}/gatilhos")
def gatilhos(uid: str, nome: str = Query("tudo bem", max_length=40)):
    """Gatilhos proativos do cliente (ativos e inativos, com o motivo) e a mensagem de abertura do ITA."""
    return clientes.gatilhos_do_cliente(uid, nome)
