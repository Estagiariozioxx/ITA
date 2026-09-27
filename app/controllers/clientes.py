"""Casos de uso determinísticos (sem LLM) sobre o extrato de um cliente: perfil, projeção,
simulação e comparação de compra, alertas, "até o salário", movimentações e gatilhos."""
from __future__ import annotations

from ..repositories import get_repo
from ..schemas import ComparacaoIn, SimulacaoIn
from ..services import engine, gatilhos
from .comum import extrato_preparado


def listar(limite: int) -> dict:
    return {"clientes": get_repo().usuarios(limite)}


def perfil(uid: str) -> dict:
    return engine.perfil(extrato_preparado(uid))


def projecao(uid: str, dias: int) -> dict:
    return engine.projetar(extrato_preparado(uid), dias)


def simular(uid: str, body: SimulacaoIn) -> dict:
    compra = {"valor": body.valor, "parcelas": body.parcelas, "entrada": body.entrada,
              "meses_espera": body.meses_espera, "taxa_mensal": body.taxa_juros_mensal}
    horizonte = max(90, 31 * (body.meses_espera + 3))  # a espera + 3 meses, no mínimo 90 dias
    d = extrato_preparado(uid)
    return {"compra": compra,
            "sem_compra": engine.resumo_projecao(engine.projetar(d, horizonte)),
            "com_compra": engine.projetar(d, horizonte, compra=compra)}


def comparar(uid: str, body: ComparacaoIn) -> dict:
    return engine.comparar_opcoes(extrato_preparado(uid), body.valor, body.parcelas, body.taxa_juros_mensal)


def alertas(uid: str) -> dict:
    return {"id_usuario": uid, "alertas": engine.alertas(extrato_preparado(uid))}


def ate_salario(uid: str, gasto: float) -> dict:
    return engine.ate_proximo_salario(extrato_preparado(uid), gasto)


def movimentacoes(uid: str, limite: int) -> dict:
    return {"id_usuario": uid, "movimentacoes": gatilhos.movimentacoes(extrato_preparado(uid), limite)}


def gatilhos_do_cliente(uid: str, nome: str) -> dict:
    d = extrato_preparado(uid)
    pf = engine.perfil(d)
    return {"id_usuario": uid, "data_referencia": pf["data_referencia"], "saldo_atual": pf["saldo_atual"],
            "gatilhos": gatilhos.detectar(d, pf, nome)}
