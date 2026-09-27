"""Tools dos agentes do ITA: consultas ao extrato do cliente (BigQuery) com as contas feitas em código.

O agente decide SE e QUANDO chamar e O QUE perguntar; a tool busca o extrato, calcula
(simulacao.py / engine.py) e devolve números prontos. O id_usuario vem sempre do
estado da sessão, nunca do Gemini, então um agente não consegue ler outro cliente.
O resultado completo fica no estado (para o front e para os guardrails de saída).

O raio-X do cliente não é tool: `carregar_perfil` roda antes de cada especialista
(before_agent_callback), porque todo especialista precisa dele.
"""
from __future__ import annotations

from google.adk.tools.tool_context import ToolContext

from . import engine, produtos, simulacao
from .data import get_repo

NECESSIDADES = {"aquisicao", "liquidez", "dificuldade", "sobra", "objetivo", "diagnostico"}


def _extrato(ctx):
    uid = ctx.state.get("id_usuario")
    if not uid:
        raise ValueError("id_usuario ausente na sessão")
    d = engine.preparar(get_repo().extrato(uid))
    return d, engine.perfil(d)


# --------------------------------------------------------------------------- #
# pré-carregamento (não é tool)
# --------------------------------------------------------------------------- #
def carregar_perfil(callback_context):
    """Antes de cada especialista: raio-X do cliente em state["contexto_cliente"] e a rota do turno."""
    st = callback_context.state
    st["rota_atual"] = callback_context.agent_name
    d, pf = _extrato(callback_context)
    st["contexto_cliente"] = simulacao.contexto(pf, engine.alertas(d))
    return None


# --------------------------------------------------------------------------- #
# Previsibilidade e Proatividade
# --------------------------------------------------------------------------- #
def ate_salario(tool_context: ToolContext, gasto: float = 0) -> dict:
    """"Até o próximo salário dá?": projeta o saldo até a véspera do próximo salário e diz quanto dá para
    gastar com segurança (gasto_maximo_seguro), com os compromissos que ainda vão sair.

    Args:
        gasto: um gasto à vista que o cliente quer fazer hoje, em reais (0 se ele só quer saber quanto pode gastar).
    """
    d, _ = _extrato(tool_context)
    r = engine.ate_proximo_salario(d, max(0.0, float(gasto)))
    tool_context.state["ate_salario"] = r
    return {k: ({kk: vv for kk, vv in v.items() if kk != "serie"} if isinstance(v, dict) else v)
            for k, v in r.items()}


def projetar_saldo(dias: int, tool_context: ToolContext) -> dict:
    """Projeta o saldo do cliente dia a dia pelos próximos `dias` dias (90 se não houver motivo para outro
    valor), com salário, contas fixas, parcelas atuais e gasto variável médio. Devolve o menor saldo e a data,
    o primeiro dia negativo, a conta que causa o aperto e o pior saldo de cada mês."""
    d, pf = _extrato(tool_context)
    pj = simulacao.projecao(d, pf, dias)
    tool_context.state["projecao"] = pj
    return {k: v for k, v in pj.items() if k != "serie"}


def comparar_gastos(tool_context: ToolContext, dias: int = 30) -> dict:
    """Compara os gastos dos últimos `dias` dias (padrão 30) por categoria com a média dos 3 meses anteriores.
    Use para "por que meu dinheiro está acabando mais rápido?" ou "gastei mais este mês?"."""
    d, _ = _extrato(tool_context)
    r = simulacao.gastos_por_categoria(d, dias)
    tool_context.state["gastos_categorias"] = r
    return r


def simular_dinheiro_extra(valor: float, tool_context: ToolContext, valor_para_quitar_parcelas: float = 0) -> dict:
    """Simula o uso de um dinheiro extra (PLR, 13º, bônus): parte para quitar parcelas abertas e o resto
    guardado. Devolve as parcelas quitadas, o alívio por mês, quanto fica guardado e os próximos 90 dias
    com e sem essa decisão.

    Args:
        valor: o dinheiro extra recebido, em reais.
        valor_para_quitar_parcelas: quanto dele o cliente quer usar para antecipar parcelas (0 = nada).
    """
    d, pf = _extrato(tool_context)
    r = simulacao.dinheiro_extra(d, pf, valor, valor_para_quitar_parcelas)
    tool_context.state["dinheiro_extra"] = r
    return r


def buscar_lancamentos(tool_context: ToolContext, categoria: str = "", descricao: str = "",
                       dias: int = 90) -> dict:
    """Busca os gastos do cliente no extrato para perguntas como "quanto gastei com iFood?".

    Args:
        categoria: parte do nome da categoria (ex.: "Alimentação", "Transporte"); vazio = todas.
        descricao: parte da descrição do lançamento (ex.: "ifood", "uber"); vazio = todas.
        dias: período em dias contando do último lançamento (padrão 90).
    """
    d, _ = _extrato(tool_context)
    r = simulacao.lancamentos(d, categoria, descricao, dias)
    tool_context.state["lancamentos"] = r
    return r


# --------------------------------------------------------------------------- #
# Produtos: as regras (produtos.py) rodam dentro das tools, não no LLM
# --------------------------------------------------------------------------- #
def _regras(tool_context: ToolContext, necessidade: str, urgencia: str, bem_duravel: bool) -> dict:
    """Aplica a Matriz_Regras sobre o raio-X do cliente e a leitura da necessidade feita pelo agente."""
    st = tool_context.state
    c = st.get("contexto_cliente")
    if not c:
        d, pf = _extrato(tool_context)
        c = st["contexto_cliente"] = simulacao.contexto(pf, engine.alertas(d))
    pf = {
        "renda_mensal_media": c["renda_mensal"],
        "contas_fixas_total": sum(f["valor"] for f in c.get("contas_fixas", [])),
        "contas_fixas": c.get("contas_fixas", []),  # para separar as que são dívida (financiamento, empréstimo)
        "parcelas_mensais_total": sum(p["valor_parcela"] for p in c.get("parcelas_abertas", [])),
        "gastos_mensais_medios": c["gastos_mensais"],
        "sobra_mensal_media": c["sobra_mensal"],
        "saldo_atual": c["saldo_atual"],
        "dias_no_negativo_90d": c["dias_no_negativo_recentes"],
        "comprometimento_renda_pct": c["comprometimento_renda_pct"],
    }
    alertas = ([{"tipo": "aperto"}] if c.get("risco_saldo_negativo") else []) + \
              ([{"tipo": "parcela_terminando"}] if c.get("parcela_terminando_em_breve") else [])
    leitura = {"necessidade": necessidade if necessidade in NECESSIDADES else "diagnostico",
               "urgencia": urgencia if urgencia in ("alta", "baixa") else None,
               "bem_duravel": bool(bem_duravel)}
    st["leitura_da_pergunta"] = leitura
    sin = produtos.sinais(pf, alertas, leitura)
    av = produtos.avaliar(sin, produtos.elegibilidade(sin))
    st["avaliacao_produtos"] = av
    return av


def avaliar_produtos(necessidade: str, tool_context: ToolContext, urgencia: str = "",
                     bem_duravel: bool = False) -> dict:
    """Aplica as regras de produto do ITA quando não há compra para simular (precisa de dinheiro, quer
    usar o que sobra, não consegue pagar as contas). Devolve as regras aplicadas, os produtos bloqueados com
    o motivo e a "oferta" (no máximo 1, ou nenhuma).

    Args:
        necessidade: aquisicao, liquidez (precisa de dinheiro agora), dificuldade (não consegue pagar as
            contas), sobra (quer usar dinheiro que sobra), objetivo (juntar para uma meta) ou diagnostico.
        urgencia: "alta" (precisa agora) ou "baixa" (pode esperar).
        bem_duravel: true para carro, moto, imóvel ou outro bem de maior valor.
    """
    av = _regras(tool_context, necessidade, urgencia, bem_duravel)
    of = produtos.oferta(av, None)
    tool_context.state["oferta"] = of
    tool_context.state["regras_produto"] = produtos.resumo(av, of)
    return produtos.resumo(av, of)


def simular_cenarios(cenarios: list[dict], necessidade: str, tool_context: ToolContext, urgencia: str = "",
                     bem_duravel: bool = False) -> dict:
    """Aplica as regras de produto, simula dia a dia os cenários da decisão e a vida sem ela, e diz se há
    oferta. Cenários de produto bloqueado pelas regras são removidos (o A, pedido do cliente, fica sempre).

    Args:
        cenarios: lista de 2 a 4 cenários. Cada um: {"chave": "A", "tipo": "compra" | "financiamento" |
            "juntar_entrada" | "consorcio" | "poupar", "descricao": "...", "valor": 3000, "parcelas": 12,
            "entrada": 0, "meses_espera": 0, "taxa_juros_mensal": 0.02, "taxa_assumida": false,
            "aporte_mensal": 0}. O A é sempre exatamente o pedido do cliente. No consórcio,
            taxa_juros_mensal é a taxa de administração total (0.15 = 15%).
        necessidade: aquisicao, liquidez, dificuldade, sobra, objetivo ou diagnostico.
        urgencia: "alta" (precisa agora) ou "baixa" (pode esperar).
        bem_duravel: true para carro, moto, imóvel ou outro bem de maior valor.
    """
    st = tool_context.state
    av = _regras(tool_context, necessidade, urgencia, bem_duravel)
    cenarios = [dict(c, chave=c.get("chave") or "ABCDEF"[i]) for i, c in enumerate(cenarios or [])][:5]
    liberados = produtos.tipos_cenario_permitidos(av)
    bloqueio = {b["produto"]: b for b in av["produtos_bloqueados"]}
    manter, removidos = [], []
    for c in cenarios:
        prod = produtos.produto_do_cenario(c.get("tipo", ""))
        if c["chave"] == "A" or c.get("tipo") not in produtos.TIPOS_DE_PRODUTO or c.get("tipo") in liberados:
            manter.append(c)
        else:
            b = bloqueio.get(prod, {})
            removidos.append({"chave": c["chave"], "tipo": c.get("tipo"), "regra": b.get("regra"),
                              "motivo": b.get("motivo", "produto não liberado pelas regras")})
    d, pf = _extrato(tool_context)
    sim = simulacao.simular(d, pf, manter)
    st["proposta"] = {"cenarios": manter}
    st["simulacao"] = sim

    # oferta: no máximo 1, de produto permitido e com cenário saudável na simulação
    por_chave = {c["chave"]: c for c in manter}
    opcoes = [{"chave": r["chave"], "tipo": por_chave[r["chave"]].get("tipo"),
               "opcao": por_chave[r["chave"]].get("descricao", ""), "parcela": r["parcela_mensal"],
               "custo_total": r["custo_total"], "juros_e_taxas": r["juros_e_taxas"],
               "taxa_assumida": bool(por_chave[r["chave"]].get("taxa_assumida")),
               "dias_no_negativo": r["dias_no_negativo"], "comprometimento_renda_pct": r["comprometimento_renda_pct"]}
              for r in sim["cenarios"] if r["chave"] in por_chave]
    sug = sim.get("sugestao_da_regra") or {}
    of = produtos.oferta(av, {"opcoes": opcoes, "recomendada": sug.get("chave")} if opcoes else None)
    st["oferta"] = of
    st["regras_produto"] = produtos.resumo(av, of)
    return {**simulacao.sem_series(sim), "removidos_pelas_regras": removidos,
            "regras_produto": produtos.resumo(av, of)}
