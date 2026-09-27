"""Motor de regras de produtos do ITA: necessidade -> solução -> produto.

Baseado em ITA_arvore_decisao_regras_produtos.xlsx (Arvore_Decisao, Matriz_Regras,
Necessidade_Produto, Contrato_Tecnico e Exemplos). Princípios:
- o ITA começa pelo problema do cliente; produto é consequência da necessidade;
- elegibilidade ≠ recomendação: ser elegível não basta, o produto precisa resolver a necessidade;
- elegibilidade, taxa, limite e custo nunca vêm do LLM, só daqui e do motor financeiro.

Produtos ofertáveis: Financiamento Itaú, Consórcio Itaú e Crédito pessoal Itaú.
Renegociação e investimentos aparecem nas regras só como orientação, nunca como oferta.

A elegibilidade é SIMULADA a partir do extrato (a base do hackathon não tem dados de crédito);
toda oferta avisa que depende de análise de crédito.
"""
from __future__ import annotations

import re

from .engine import _py

PRODUTOS = {
    # tipos de cenário (Cenario.tipo em agents.py) que correspondem a cada produto
    "financiamento": {"nome": "Financiamento Itaú", "tipos_cenario": ("financiamento", "juntar_entrada")},
    "consorcio": {"nome": "Consórcio Itaú", "tipos_cenario": ("consorcio",)},
    "credito": {"nome": "Crédito pessoal Itaú", "tipos_cenario": ()},  # ofertado sem simular taxa
}
TIPOS_DE_PRODUTO = {t for v in PRODUTOS.values() for t in v["tipos_cenario"]}


def produto_do_cenario(tipo: str) -> str | None:
    return next((k for k, v in PRODUTOS.items() if tipo in v["tipos_cenario"]), None)

# Limites da elegibilidade simulada. A régua é o comprometimento com DÍVIDAS (parcelas, financiamentos,
# empréstimos) sobre a renda, como no mercado de crédito, e não todas as contas fixas (aluguel, luz,
# assinaturas): nos dados reais, contas fixas + parcelas passam de 50% da renda para a maioria dos clientes.
DIVIDA_MAX_ELEGIVEL = 35.0     # dívidas atuais acima disso: nenhum produto de dívida é elegível
DIVIDA_MAX_CREDITO = 30.0
DIVIDA_MAX_DEPOIS = 35.0       # capacidade: dívidas atuais + parcela nova até 35% da renda
DIVIDA_MAX_CAPACIDADE = 30.0   # para crédito sem simulação (R004 / R003)
DIAS_NEGATIVO_DIFICULDADE = 30  # 30+ dias no negativo em 90 dias com saldo negativo = dificuldade
DIAS_NEGATIVO_MAX_CREDITO = 15
_DIVIDA = re.compile(r"finan|emprest|empr[eé]st|consig|cdc|cr[eé]dito pessoal|\bparc")  # "finan imob" no extrato


def divida_mensal(pf: dict) -> float:
    """Parcelas em aberto + contas fixas que são dívida (financiamento, empréstimo, consignado)."""
    fixas_divida = sum(f["valor"] for f in pf.get("contas_fixas") or [] if _DIVIDA.search(str(f["descricao"]).lower()))
    return float(pf["parcelas_mensais_total"] or 0) + fixas_divida


# --------------------------------------------------------------------------- #
# sinais e elegibilidade (calculados do extrato)
# --------------------------------------------------------------------------- #
def sinais(pf: dict, alertas: list[dict], rot: dict | None = None) -> dict:
    """Condições da Matriz_Regras, a partir do perfil, dos alertas e do que o orquestrador extraiu."""
    rot = rot or {}
    renda = pf["renda_mensal_media"] or 0
    tipos = {a["tipo"] for a in alertas}
    essenciais = (pf["contas_fixas_total"] + pf["parcelas_mensais_total"]) or 0.5 * pf["gastos_mensais_medios"]
    sobra = pf["sobra_mensal_media"] or 0
    return _py({
        # proxy de inadimplência: a base não tem atraso de dívida, só o saldo da conta
        "dificuldade_grave": pf["dias_no_negativo_90d"] >= DIAS_NEGATIVO_DIFICULDADE and pf["saldo_atual"] < 0,
        "risco_saldo_negativo": "aperto" in tipos,
        "sobra_recorrente": sobra >= max(150.0, 0.05 * renda),
        "reserva_adequada": pf["saldo_atual"] >= 3 * essenciais,
        "parcela_terminando": "parcela_terminando" in tipos,
        "comprometimento_renda_pct": pf["comprometimento_renda_pct"],
        "divida_pct": round(100 * divida_mensal(pf) / renda, 1) if renda else 100.0,
        "renda_mensal": renda,
        "dias_no_negativo_90d": pf["dias_no_negativo_90d"],
        "necessidade": rot.get("necessidade") or _necessidade_padrao(rot),
        "urgencia": rot.get("urgencia"),
        "bem_duravel": bool(rot.get("bem_duravel")),
    })


def _necessidade_padrao(rot: dict) -> str:
    if rot.get("rota") == "decisao":
        return "aquisicao" if rot.get("tipo") != "meta" else "objetivo"
    return "diagnostico"


def elegibilidade(s: dict) -> dict:
    """Elegibilidade SIMULADA (não é aprovação de crédito)."""
    base = not s["dificuldade_grave"] and s["divida_pct"] < DIVIDA_MAX_ELEGIVEL
    return {
        "financiamento": base,
        "consorcio": base,
        "credito": base and s["divida_pct"] < DIVIDA_MAX_CREDITO
        and s["dias_no_negativo_90d"] < DIAS_NEGATIVO_MAX_CREDITO,
    }


# --------------------------------------------------------------------------- #
# regras (Matriz_Regras)
# --------------------------------------------------------------------------- #
def avaliar(s: dict, eleg: dict) -> dict:
    """Aplica a Matriz_Regras: quais produtos PODEM entrar na conversa e por quê.

    Devolve as regras aplicadas (auditáveis), os produtos permitidos (candidatos à oferta,
    ainda sujeitos à simulação) e os bloqueados com o motivo.
    """
    regras: list[dict] = []
    permitidos: dict[str, str] = {}   # produto -> regra
    bloqueados: dict[str, dict] = {}  # produto -> {regra, motivo}
    # produto permitido só como SEGUNDO PASSO: a recomendação sem produto vem antes e é a principal
    segundo_passo: dict[str, str] = {}  # produto -> condição em que ele faz sentido

    def aplica(rid, decisao, cuidado):
        regras.append({"regra": rid, "decisao": decisao, "cuidado": cuidado})

    def bloqueia(produto, rid, motivo):
        bloqueados.setdefault(produto, {"regra": rid, "motivo": motivo})

    nec, urg = s["necessidade"], s["urgencia"]

    # R001/R002 (proxy): dificuldade grave -> tratar a situação atual, nada de dívida nova
    if s["dificuldade_grave"]:
        aplica("R002", "ajudar a tratar a situação atual antes de qualquer produto",
               "não estimular novo crédito; não inventar solução não elegível")
        for p in PRODUTOS:
            bloqueia(p, "R002", "o saldo está negativo há muitos dias: primeiro reorganizar as contas")

    # R003: risco de saldo negativo -> prevenir primeiro; crédito só se adequado e elegível
    if s["risco_saldo_negativo"] and not s["dificuldade_grave"]:
        aplica("R003", "prevenir a falta de dinheiro primeiro: reorganizar e simular",
               "crédito não deve ser resposta automática")
        if nec not in ("liquidez", "dificuldade"):
            bloqueia("credito", "R003", "o problema se resolve reorganizando o fluxo, sem dívida nova")

    # R004: liquidez + crédito elegível + capacidade de pagamento
    if nec in ("liquidez", "dificuldade"):
        capacidade = s["divida_pct"] < DIVIDA_MAX_CAPACIDADE and s["sobra_recorrente"]
        if eleg["credito"] and capacidade:
            aplica("R004", "comparar alternativas sem crédito e o crédito antes de ofertar",
                   "mostrar custo e efeito futuro")
            permitidos.setdefault("credito", "R004")
            # crédito nunca é a primeira resposta: as alternativas sem dívida vêm antes
            segundo_passo["credito"] = ("depois de ver as alternativas sem crédito (adiar, reduzir, usar a sobra "
                                        "do mês), se ainda precisar do valor agora")
        elif eleg["credito"] and s["risco_saldo_negativo"] and s["divida_pct"] < DIVIDA_MAX_CAPACIDADE:
            # R003: "reorganizar/simular; crédito somente se adequado + elegível" -> só depois da reorganização
            permitidos.setdefault("credito", "R003")
            segundo_passo["credito"] = ("só se, depois de reorganizar as contas e adiar o que der, ainda faltar "
                                        "dinheiro para o essencial")
        else:
            bloqueia("credito", "R004", "sem capacidade de pagamento para uma parcela nova"
                     if eleg["credito"] else "não elegível na simulação")

    # R005 / R006: aquisição de bem, com ou sem urgência
    if nec == "aquisicao":
        if not s["bem_duravel"]:
            # compra do dia a dia: pagar à vista, parcelar, esperar ou poupar resolvem sem produto
            for p in ("financiamento", "consorcio"):
                bloqueia(p, "R013", "para uma compra do dia a dia, esperar, poupar ou parcelar resolvem sem produto")
        elif urg == "alta":
            if eleg["financiamento"]:
                aplica("R005", "comparar recursos próprios e financiamento", "validar capacidade e impacto")
                permitidos.setdefault("financiamento", "R005")
            else:
                bloqueia("financiamento", "R005", "não elegível na simulação")
            bloqueia("consorcio", "R006", "o consórcio não garante o bem agora (sai por sorteio ou lance)")
        else:
            aplica("R006", "comparar consórcio, juntar dinheiro e financiamento futuro",
                   "não tratar consórcio como equivalente a compra imediata")
            for p in ("consorcio", "financiamento"):
                if eleg[p]:
                    permitidos.setdefault(p, "R006")
                else:
                    bloqueia(p, "R006", "não elegível na simulação")
        if "credito" not in permitidos:
            bloqueia("credito", "R013", "para comprar um bem, crédito pessoal não é a solução mais adequada")

    # R007 / R008 / R009: sobra -> reserva primeiro (investimentos ficam como orientação)
    if s["sobra_recorrente"] and not s["reserva_adequada"]:
        aplica("R007", "priorizar a construção da reserva de emergência",
               "não partir direto para um objetivo de maior risco")
    if s["sobra_recorrente"] and s["reserva_adequada"]:
        aplica("R008", "direcionar a sobra conforme objetivo e perfil de investidor", "respeitar perfil e horizonte")
    if s["parcela_terminando"]:
        aplica("R009", "avaliar o contexto antes de direcionar a folga", "não assumir que todo valor ficou livre")
    # R011: com sobra, depois da reserva, um objetivo planejado (carro, imóvel) pode ir para o consórcio
    if nec == "sobra" and s["sobra_recorrente"] and eleg["consorcio"]:
        aplica("R011", "entender o objetivo e recalcular a capacidade", "elegibilidade é filtro, não recomendação")
        permitidos.setdefault("consorcio", "R011")
        segundo_passo["consorcio"] = ("depois de montar a reserva de emergência, se houver um objetivo planejado "
                                      "como trocar de carro ou comprar um imóvel, sem pressa")

    # R013: produto elegível sem necessidade aderente não é ofertado
    for p in PRODUTOS:
        if p not in permitidos and p not in bloqueados:
            bloqueia(p, "R013", "não resolve a necessidade atual")
    if bloqueados:
        aplica("R013", "produto disponível não implica oferta", "elegibilidade é filtro, não recomendação")
    # R014: vários permitidos -> simular e comparar só os aderentes; o cliente decide
    if len(permitidos) > 1:
        aplica("R014", "simular e comparar apenas as soluções que resolvem a necessidade",
               "o cliente decide depois da explicação")

    for p in permitidos:
        bloqueados.pop(p, None)
    return _py({
        "sinais": s,
        "elegibilidade_simulada": eleg,
        "regras_aplicadas": regras,
        "produtos_permitidos": [{"produto": p, "nome": PRODUTOS[p]["nome"], "regra": r,
                                 "segundo_passo": p in segundo_passo, "condicao": segundo_passo.get(p)}
                                for p, r in permitidos.items()],
        "produtos_bloqueados": [{"produto": p, "nome": PRODUTOS[p]["nome"], **b} for p, b in bloqueados.items()],
    })


def tipos_cenario_permitidos(av: dict) -> set[str]:
    """Tipos de cenário de produto que o PROPOR pode sugerir (os demais tipos são sempre livres)."""
    return {t for p in av["produtos_permitidos"] for t in PRODUTOS[p["produto"]]["tipos_cenario"]}


# --------------------------------------------------------------------------- #
# oferta final (depois da simulação)
# --------------------------------------------------------------------------- #
def _saudavel(o: dict, s: dict) -> bool:
    """Cenário saudável: nenhum dia no negativo e dívidas atuais + parcela nova até 35% da renda."""
    renda = s.get("renda_mensal") or 0
    if not renda:
        return False
    return o["dias_no_negativo"] == 0 and s["divida_pct"] + 100 * (o.get("parcela") or 0) / renda <= DIVIDA_MAX_DEPOIS


def oferta(av: dict, comp: dict | None = None) -> dict | None:
    """No máximo 1 oferta, só de produto permitido e que se mostrou saudável na simulação.

    Financiamento e consórcio precisam de um cenário simulado sem dia negativo e com
    comprometimento até 30% (a preferência é o cenário recomendado). Crédito pessoal é
    ofertado sem taxa nem parcela na mensagem: o cliente vê as condições na simulação da própria conversa
    (contratacao.py).
    """
    permitidos = {p["produto"]: p for p in av["produtos_permitidos"]}
    if comp:
        opcoes = sorted(comp["opcoes"], key=lambda o: o["chave"] != comp["recomendada"])
        for o in opcoes:
            prod = produto_do_cenario(o["tipo"])
            if prod in permitidos and _saudavel(o, av["sinais"]):
                return _py({
                    "produto": prod, "nome": PRODUTOS[prod]["nome"], "regra": permitidos[prod]["regra"],
                    "cenario": o["chave"], "opcao": o["opcao"], "parcela": o["parcela"],
                    "custo_total": o["custo_total"], "juros_e_taxas": o["juros_e_taxas"],
                    "taxa_hipotetica": o["taxa_assumida"], "recomendado_pelo_motor": o["chave"] == comp["recomendada"],
                    "aviso": "elegibilidade simulada a partir do extrato; a contratação depende de análise de crédito",
                })
    # sem cenário simulado: crédito pessoal, ou um produto liberado só como segundo passo (sem números)
    for prod in ("credito", "consorcio"):
        p = permitidos.get(prod)
        if p and (prod == "credito" or p.get("segundo_passo")):
            return {"produto": prod, "nome": PRODUTOS[prod]["nome"], "regra": p["regra"], "cenario": None,
                    "segundo_passo": bool(p.get("segundo_passo")), "condicao": p.get("condicao"),
                    "condicoes": ("valor, taxa e parcelas aparecem na simulação aqui na conversa, antes de contratar"
                                  if prod == "credito" else
                                  "valor da carta, prazo e taxa de administração aparecem na simulação aqui na conversa"),
                    "aviso": "elegibilidade simulada a partir do extrato; a contratação depende de análise de crédito"}
    return None


def resumo(av: dict, of: dict | None) -> dict:
    """Versão curta para o prompt e para a trilha."""
    return {
        "regras_aplicadas": [r["regra"] for r in av["regras_aplicadas"]],
        "decisoes": [f"{r['regra']}: {r['decisao']} (cuidado: {r['cuidado']})" for r in av["regras_aplicadas"]],
        "produtos_bloqueados": [f"{b['nome']}: {b['motivo']} ({b['regra']})" for b in av["produtos_bloqueados"]],
        "oferta": of,
    }
