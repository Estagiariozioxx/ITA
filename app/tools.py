"""Ferramentas (tools) que os agentes podem chamar.

Cada tool lê o `id_usuario` do estado da sessão (nunca do texto do usuário),
chama o motor determinístico e devolve um resumo compacto para o LLM.
O resultado completo (com a série diária para gráficos) fica em
`state["dados_tela"]`, que a API devolve para o front-end.
"""
from __future__ import annotations

from google.adk.tools.tool_context import ToolContext

from . import engine
from .data import get_repo


def _df(tool_context: ToolContext):
    uid = tool_context.state.get("id_usuario")
    if not uid:
        raise ValueError("id_usuario ausente na sessão")
    return engine.preparar(get_repo().extrato(uid))


def _guardar_tela(tool_context: ToolContext, chave: str, valor) -> None:
    tela = dict(tool_context.state.get("dados_tela") or {})
    tela[chave] = valor
    tool_context.state["dados_tela"] = tela


def consultar_perfil(tool_context: ToolContext) -> dict:
    """Raio-X financeiro do cliente: saldo atual, renda média, contas fixas com dia
    de vencimento, parcelas em aberto (quando terminam), comprometimento da renda,
    dias no negativo nos últimos 90 dias e principais categorias de gasto."""
    pf = engine.perfil(_df(tool_context))
    _guardar_tela(tool_context, "perfil", pf)
    return pf


def verificar_alertas(tool_context: ToolContext) -> dict:
    """Verifica situações que merecem aviso proativo: saldo que vai ficar negativo,
    mês apertado, parcelas terminando e dinheiro sobrando (reserva/investimento)."""
    al = engine.alertas(_df(tool_context))
    _guardar_tela(tool_context, "alertas", al)
    return {"alertas": [{k: v for k, v in a.items() if k != "dados"} for a in al]}


def projetar_saldo(dias: int, tool_context: ToolContext) -> dict:
    """Projeta o saldo do cliente dia a dia pelos próximos `dias` dias (use 90 se não
    houver motivo para outro valor), considerando salário, contas fixas, parcelas já
    assumidas e o gasto variável médio."""
    pj = engine.projetar(_df(tool_context), max(7, min(int(dias), 365)))
    _guardar_tela(tool_context, "projecao", pj)
    return engine.resumo_projecao(pj)


def simular_compra(
    valor: float,
    parcelas: int,
    entrada: float,
    meses_espera: int,
    taxa_juros_mensal: float,
    tool_context: ToolContext,
) -> dict:
    """Simula UMA forma específica de fazer uma compra e mostra o impacto no saldo.

    Args:
        valor: valor total da compra em reais.
        parcelas: número de parcelas (1 = à vista).
        entrada: valor pago de entrada em reais (0 se não houver).
        meses_espera: quantos meses esperar antes de comprar (0 = agora).
        taxa_juros_mensal: juros ao mês em decimal, ex. 0.02 para 2% (0 = sem juros).
    """
    compra = {"valor": valor, "parcelas": parcelas, "entrada": entrada,
              "meses_espera": meses_espera, "taxa_mensal": taxa_juros_mensal}
    horizonte = max(90, 31 * (int(meses_espera) + 3))
    pj = engine.projetar(_df(tool_context), horizonte, compra=compra)
    _guardar_tela(tool_context, "simulacao", {"compra": compra, **pj})
    return {"compra": compra, **engine.resumo_projecao(pj)}


def comparar_opcoes_compra(
    valor: float, parcelas: int, taxa_juros_mensal: float, tool_context: ToolContext
) -> dict:
    """Compara automaticamente os caminhos possíveis para uma compra (parcelar agora,
    menos parcelas, dar entrada, esperar as parcelas atuais acabarem, um valor menor)
    e indica qual é o mais saudável para o fluxo de caixa do cliente e por quê.

    Args:
        valor: valor total da compra em reais.
        parcelas: número de parcelas que o cliente pediu.
        taxa_juros_mensal: juros ao mês em decimal (0 se sem juros ou desconhecido).
    """
    c = engine.comparar_opcoes(_df(tool_context), valor, parcelas, taxa_juros_mensal)
    _guardar_tela(tool_context, "comparacao", c)
    return engine.resumo_comparacao(c)
