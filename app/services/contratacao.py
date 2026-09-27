"""Simular e contratar os produtos do ITA dentro do WhatsApp (formulário na conversa).

Todos os números vêm daqui (motor), nunca do LLM. Antes de liberar a contratação o ITA
confere a elegibilidade simulada e a capacidade de pagamento (produtos.py) e projeta o
saldo dos próximos 90 dias com a parcela nova. A contratação é de DEMONSTRAÇÃO: gera um
protocolo e o status "proposta enviada para análise"; nada é contratado de verdade.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import time

import pandas as pd

from .. import config
from . import engine, produtos
from .engine import _data_no_mes, _py, brl, valor_parcela

PRAZOS = {  # meses permitidos por produto
    "financiamento": (12, 72),
    "consorcio": (24, 100),
    "credito": (3, 36),
}
NECESSIDADE = {"financiamento": "aquisicao", "consorcio": "aquisicao", "credito": "liquidez"}


def _taxa(produto: str, taxa: float | None) -> tuple[float, bool]:
    """Taxa usada e se ela é ilustrativa (não veio do cenário que gerou a oferta)."""
    if taxa and taxa > 0:
        return (taxa / 100 if taxa > 1 else taxa), False
    return {"financiamento": config.TAXA_REF_FINANCIAMENTO, "credito": config.TAXA_REF_CREDITO,
            "consorcio": config.TAXA_ADM_CONSORCIO}[produto], True


def _parcela(produto: str, principal: float, n: int, taxa: float) -> float:
    if produto == "consorcio":  # sem juros; taxa de administração total diluída nas parcelas
        return principal * (1 + taxa) / n
    return valor_parcela(principal, n, taxa)


def simular(d: pd.DataFrame, produto: str, valor: float, prazo: int, entrada: float = 0.0,
            taxa: float | None = None) -> dict:
    pf = engine.perfil(d)
    s = produtos.sinais(pf, engine.alertas(d), {"necessidade": NECESSIDADE[produto], "bem_duravel": True})
    eleg = produtos.elegibilidade(s)[produto]
    lo, hi = PRAZOS[produto]
    prazo = max(lo, min(int(prazo), hi))
    entrada = max(0.0, min(float(entrada or 0), valor)) if produto == "financiamento" else 0.0
    principal = float(valor) - entrada
    tx, ilustrativa = _taxa(produto, taxa)
    parcela = _parcela(produto, principal, prazo, tx)
    total = parcela * prazo + entrada
    renda = s["renda_mensal"] or 0
    divida_depois = s["divida_pct"] + (100 * parcela / renda if renda else 100)

    # projeção de 90 dias com a decisão: crédito entra na conta hoje; entrada sai hoje; parcelas no dia padrão
    inicio = dt.date.fromisoformat(pf["data_referencia"]) + dt.timedelta(days=1)
    extras = []
    if produto == "credito":
        extras.append({"data": inicio, "valor": float(valor), "descricao": "crédito liberado", "origem": "produto"})
    if entrada:
        extras.append({"data": inicio, "valor": -entrada, "descricao": "entrada", "origem": "produto"})
    primeira = _data_no_mes(inicio.year, inicio.month + 1, config.DIA_VENCIMENTO_PADRAO)
    for k in range(min(prazo, 4)):
        extras.append({"data": _data_no_mes(primeira.year, primeira.month + k, config.DIA_VENCIMENTO_PADRAO),
                       "valor": -parcela, "descricao": f"parcela {k + 1}/{prazo}", "origem": "produto"})
    pj = engine.projetar(d, 90, pf=pf, extras=extras)

    cabe = eleg and divida_depois <= produtos.DIVIDA_MAX_DEPOIS and pj["dias_no_negativo"] == 0
    motivo = None
    if not eleg:
        motivo = ("seu saldo está negativo há muitos dias: o melhor agora é reorganizar as contas"
                  if s["dificuldade_grave"] else "suas dívidas atuais já comprometem boa parte da renda")
    elif divida_depois > produtos.DIVIDA_MAX_DEPOIS:
        motivo = f"a parcela deixaria {divida_depois:.0f}% da sua renda com dívidas (o limite saudável é 35%)"
    elif pj["dias_no_negativo"]:
        motivo = f"seu saldo ficaria negativo em {pj['dias_no_negativo']} dia(s) nos próximos 90 dias"

    sugestao = None
    if eleg and not cabe and renda:
        # 1) maior prazo que cabe;  2) senão, o maior valor que cabe no prazo máximo
        folga = (produtos.DIVIDA_MAX_DEPOIS - s["divida_pct"]) / 100 * renda
        for n in sorted({*range(prazo + 6, hi + 1, 6), hi}):
            if _parcela(produto, principal, n, tx) <= folga:
                sugestao = {"tipo": "prazo", "prazo": n, "parcela": round(_parcela(produto, principal, n, tx), 2),
                            "texto": f"em {n} meses a parcela cai para {brl(_parcela(produto, principal, n, tx))}"}
                break
        if not sugestao and folga > 0:
            unit = _parcela(produto, 1.0, hi, tx)
            vmax = round((folga / unit + entrada) / 100) * 100
            if vmax >= 500:
                sugestao = {"tipo": "valor", "valor": vmax, "prazo": hi,
                            "texto": f"um valor de até {brl(vmax)} em {hi} meses caberia no seu orçamento"}

    obs = []
    if ilustrativa:
        obs.append("Taxa ilustrativa: a taxa real é definida na análise de crédito.")
    if produto == "consorcio":
        obs.append("No consórcio não há juros; a carta sai por sorteio ou lance, sem data certa.")
    else:
        obs.append("Você pode desistir em até 7 dias depois de contratar, sem custo.")
    anual = ((1 + tx) ** 12 - 1) * 100 if produto != "consorcio" else None
    return _py({
        "produto": produto, "nome": produtos.PRODUTOS[produto]["nome"],
        "valor": float(valor), "entrada": entrada, "prazo_meses": prazo, "prazo_min": lo, "prazo_max": hi,
        "taxa_pct": round(100 * tx, 2), "taxa_anual_pct": round(anual, 1) if anual else None,
        "taxa_ilustrativa": ilustrativa, "tipo_taxa": "administração (total)" if produto == "consorcio" else "juros ao mês",
        "parcela": round(parcela, 2), "custo_total": round(total, 2), "juros_e_taxas": round(total - float(valor), 2),
        "primeira_parcela": primeira,
        "divida_atual_pct": s["divida_pct"], "divida_depois_pct": round(divida_depois, 1),
        "dias_no_negativo_90d": pj["dias_no_negativo"], "menor_saldo_90d": pj["menor_saldo"],
        "elegivel": eleg, "cabe": cabe, "motivo": motivo, "sugestao": sugestao, "observacoes": obs,
        "aviso": "Simulação com elegibilidade calculada a partir do extrato; a contratação depende de análise de crédito.",
    })


def contratar(d: pd.DataFrame, uid: str, produto: str, valor: float, prazo: int, entrada: float = 0.0,
              taxa: float | None = None) -> dict:
    """Refaz a simulação e, se couber, registra a proposta (demonstração: só gera o protocolo)."""
    sim = simular(d, produto, valor, prazo, entrada, taxa)
    if not sim["cabe"]:
        return {"contratado": False, "simulacao": sim, "motivo": sim["motivo"] or "a proposta não cabe no orçamento"}
    protocolo = "ITA-" + hashlib.sha1(f"{uid}{produto}{valor}{prazo}{time.time()}".encode()).hexdigest()[:8].upper()
    passos = ["Análise de crédito em até 1 dia útil.",
              "O contrato chega aqui no WhatsApp para você revisar e assinar.",
              ("Com o contrato assinado, você entra nos sorteios e pode dar lances." if produto == "consorcio"
               else "Você pode desistir em até 7 dias depois de assinar, sem custo.")]
    return {"contratado": True, "protocolo": protocolo, "status": "proposta enviada para análise",
            "demonstracao": True, "simulacao": sim, "proximos_passos": passos}
