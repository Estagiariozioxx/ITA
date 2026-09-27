"""Motor determinístico do ITA.

Regra de ouro: TODO número que o cliente vê sai daqui, nunca do LLM.
O Gemini só interpreta, explica e conversa sobre esses resultados.

Funções principais
- perfil(df):            raio-X (renda, contas fixas, parcelas, sobra, comprometimento)
- projetar(df, ...):     saldo dia a dia nos próximos N dias, com ou sem uma compra
- comparar_opcoes(...):  simula caminhos para uma compra e recomenda o mais saudável
- alertas(df):           gatilhos proativos (aperto, parcela terminando, sobra -> reserva)
"""
from __future__ import annotations

import calendar
import datetime as dt
import math
from collections import defaultdict

import numpy as np
import pandas as pd

from .. import config
from .formatos import brl  # noqa: F401  (usado aqui e reexportado)


# --------------------------------------------------------------------------- #
# utilidades
# --------------------------------------------------------------------------- #


def _data_no_mes(ano: int, mes: int, dia: int) -> dt.date:
    ano += (mes - 1) // 12
    mes = (mes - 1) % 12 + 1
    return dt.date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def _somar_meses(d: dt.date, k: int, dia: int | None = None) -> dt.date:
    return _data_no_mes(d.year, d.month + k, dia or d.day)


def _py(v):
    """Converte tipos numpy/pandas para JSON puro."""
    if isinstance(v, dict):
        return {k: _py(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_py(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if math.isnan(v) else round(float(v), 2)
    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 2)
    if isinstance(v, (pd.Timestamp, dt.datetime)):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    return v


# --------------------------------------------------------------------------- #
# preparação
# --------------------------------------------------------------------------- #
def preparar(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["dt"] = (
        pd.to_datetime(d["anomesdia"], utc=True).dt.tz_convert(None).dt.normalize()
    )
    d["vlr"] = pd.to_numeric(d["vlr"], errors="coerce").fillna(0).abs()
    d["saida"] = d["tipo"].astype(str).str.upper().eq(config.TIPO_SAIDA.upper())
    d["mes"] = d["dt"].dt.to_period("M")
    d["dia"] = d["dt"].dt.day
    d["parcela_total"] = pd.to_numeric(d.get("parcela_total"), errors="coerce")
    d["parcela_atual"] = pd.to_numeric(d.get("parcela_atual"), errors="coerce")
    d["parcelado"] = d["parcela_total"].fillna(0) > 1
    d["descr"] = d["descr"].fillna("").astype(str).str.strip().str.lower()
    d["nom_cate_macro"] = d["nom_cate_macro"].fillna("Outros")
    d["saldo_apos"] = pd.to_numeric(d["saldo_apos"], errors="coerce")
    d = d.reset_index(drop=True)
    d["_ordem"] = np.arange(len(d))
    return d.sort_values(["dt", "_ordem"], kind="stable").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# padrões
# --------------------------------------------------------------------------- #
def recorrencias(d: pd.DataFrame) -> list[dict]:
    """Lançamentos que se repetem ~1x por mês (salário, aluguel, assinaturas...)."""
    fim = d["dt"].max()
    n_meses = d["mes"].nunique()
    base = d[~d["parcelado"]]
    if base.empty:
        return []
    g = (
        base.groupby(["descr", "saida"])
        .agg(
            meses=("mes", "nunique"),
            n=("vlr", "size"),
            valor=("vlr", "median"),
            dia=("dia", "median"),
            ultima=("dt", "max"),
            categoria=("nom_cate_macro", "first"),
        )
        .reset_index()
    )
    min_meses = max(2, min(3, n_meses))
    g = g[
        (g["meses"] >= min_meses)
        & (g["meses"] / n_meses >= 0.6)
        & (g["n"] <= g["meses"] * 1.5)
        & (g["ultima"] >= fim - pd.Timedelta(days=45))
    ]
    out = []
    for r in g.itertuples():
        out.append(
            {
                "descricao": r.descr,
                "tipo": "saida" if r.saida else "entrada",
                "valor": round(float(r.valor), 2),
                "dia": int(round(r.dia)),
                "categoria": r.categoria,
            }
        )
    return sorted(out, key=lambda x: (x["tipo"], x["dia"]))


def parcelas_abertas(d: pd.DataFrame) -> list[dict]:
    """Compras parceladas que ainda têm parcelas a vencer."""
    p = d[d["parcelado"]].copy()
    if p.empty:
        return []
    fim = d["dt"].max()
    p["vlr_r"] = p["vlr"].round(2)
    g = (
        p.groupby(["descr", "parcela_total", "vlr_r"])
        .agg(
            atual=("parcela_atual", "max"),
            ultima=("dt", "max"),
            categoria=("nom_cate_macro", "first"),
        )
        .reset_index()
    )
    g = g[(g["atual"] < g["parcela_total"]) & (g["ultima"] >= fim - pd.Timedelta(days=40))]
    out = []
    for r in g.itertuples():
        restantes = int(r.parcela_total - r.atual)
        ultima = r.ultima.date()
        out.append(
            {
                "descricao": r.descr,
                "valor_parcela": float(r.vlr_r),
                "parcela_atual": int(r.atual),
                "parcela_total": int(r.parcela_total),
                "restantes": restantes,
                "dia": ultima.day,
                "ultima_cobranca": ultima.isoformat(),
                "termina_em": _somar_meses(ultima, restantes).isoformat(),
                "categoria": r.categoria,
            }
        )
    return sorted(out, key=lambda x: x["termina_em"])


# --------------------------------------------------------------------------- #
# perfil (ENTENDER)
# --------------------------------------------------------------------------- #
def perfil(d: pd.DataFrame) -> dict:
    fim = d["dt"].max()
    j = d[d["dt"] > fim - pd.Timedelta(days=90)]
    rec = recorrencias(d)
    parc = parcelas_abertas(d)

    fixos = [r for r in rec if r["tipo"] == "saida"]
    entradas_fixas = [r for r in rec if r["tipo"] == "entrada"]
    desc_fixos = {r["descricao"] for r in fixos}
    desc_entradas = {r["descricao"] for r in entradas_fixas}

    renda_mensal = j.loc[~j["saida"], "vlr"].sum() / 3
    gastos_mensais = j.loc[j["saida"], "vlr"].sum() / 3
    fixos_total = sum(r["valor"] for r in fixos)
    parcelas_mes = sum(p["valor_parcela"] for p in parc)

    # o que não é recorrente nem parcela vira fluxo "variável" diário médio
    saida_variavel = (
        j.loc[j["saida"] & ~j["parcelado"] & ~j["descr"].isin(desc_fixos), "vlr"].sum() / 90
    )
    entrada_variavel = j.loc[~j["saida"] & ~j["descr"].isin(desc_entradas), "vlr"].sum() / 90

    top = (
        j[j["saida"]]
        .groupby("nom_cate_macro")["vlr"].sum()
        .sort_values(ascending=False)
        .head(5)
        / 3
    )
    renda_ref = renda_mensal or 1
    return _py(
        {
            "data_referencia": fim.date(),
            "saldo_atual": float(d.iloc[-1]["saldo_apos"]),
            "renda_mensal_media": renda_mensal,
            "gastos_mensais_medios": gastos_mensais,
            "sobra_mensal_media": renda_mensal - gastos_mensais,
            "contas_fixas": fixos,
            "contas_fixas_total": fixos_total,
            "entradas_recorrentes": entradas_fixas,
            "parcelas_abertas": parc,
            "parcelas_mensais_total": parcelas_mes,
            "comprometimento_renda_pct": round(100 * (fixos_total + parcelas_mes) / renda_ref, 1),
            "gasto_variavel_diario": saida_variavel,
            "entrada_variavel_diaria": entrada_variavel,
            "dias_no_negativo_90d": int(j.loc[j["saldo_apos"] < 0, "dt"].nunique()),
            "top_categorias_mes": [
                {"categoria": k, "valor_mensal": v} for k, v in top.items()
            ],
        }
    )


# --------------------------------------------------------------------------- #
# projeção (ANTECIPAR)
# --------------------------------------------------------------------------- #
def valor_parcela(valor: float, n: int, taxa_mensal: float = 0.0) -> float:
    if n <= 0:
        return valor
    if taxa_mensal <= 0:
        return valor / n
    i = taxa_mensal
    return valor * i / (1 - (1 + i) ** -n)


def projetar(
    d: pd.DataFrame,
    dias: int = 90,
    compra: dict | None = None,
    pf: dict | None = None,
    extras: list[dict] | None = None,
) -> dict:
    """Projeta o saldo dia a dia.

    compra = {"valor": 3000, "parcelas": 12, "entrada": 0, "meses_espera": 0,
              "taxa_mensal": 0.0, "dia_vencimento": 10}
    extras = lançamentos futuros avulsos:
             [{"data": date, "valor": -250.0, "descricao": "...", "origem": "objetivo"}]
    """
    pf = pf or perfil(d)
    inicio = dt.date.fromisoformat(pf["data_referencia"]) + dt.timedelta(days=1)
    fim_proj = inicio + dt.timedelta(days=dias - 1)
    eventos: dict[dt.date, list[dict]] = defaultdict(list)

    def add(data: dt.date, valor: float, descricao: str, origem: str):
        if inicio <= data <= fim_proj:
            eventos[data].append(
                {"descricao": descricao, "valor": round(valor, 2), "origem": origem}
            )

    n_meses = dias // 28 + 2
    for r in pf["contas_fixas"] + pf["entradas_recorrentes"]:
        sinal = -1 if r["tipo"] == "saida" else 1
        for m in range(n_meses):
            add(_data_no_mes(inicio.year, inicio.month + m, r["dia"]), sinal * r["valor"],
                r["descricao"], "recorrente")

    for p in pf["parcelas_abertas"]:
        ultima = dt.date.fromisoformat(p["ultima_cobranca"])
        for k in range(1, p["restantes"] + 1):
            add(_somar_meses(ultima, k, p["dia"]), -p["valor_parcela"],
                f"{p['descricao']} ({p['parcela_atual'] + k}/{p['parcela_total']})", "parcela")

    parcela_nova = None
    if compra:
        valor = float(compra["valor"])
        entrada = float(compra.get("entrada") or 0)
        n = int(compra.get("parcelas") or 1)
        espera = int(compra.get("meses_espera") or 0)
        taxa = float(compra.get("taxa_mensal") or 0)
        dia_venc = int(compra.get("dia_vencimento") or config.DIA_VENCIMENTO_PADRAO)
        data_compra = _somar_meses(inicio, espera) if espera else inicio
        parcela_nova = valor_parcela(valor - entrada, n, taxa)
        if entrada:
            add(data_compra, -entrada, "entrada da compra", "compra")
        if n <= 1 and not entrada:
            add(data_compra, -valor, "compra à vista", "compra")
        else:
            for k in range(1, n + 1):
                add(_data_no_mes(data_compra.year, data_compra.month + k, dia_venc),
                    -parcela_nova, f"nova compra ({k}/{n})", "compra")

    for e in extras or []:
        data = dt.date.fromisoformat(e["data"]) if isinstance(e["data"], str) else e["data"]
        add(data, e["valor"], e["descricao"], e["origem"])

    var_dia = pf["entrada_variavel_diaria"] - pf["gasto_variavel_diario"]
    saldo = pf["saldo_atual"]
    serie, fluxo_mes = [], defaultdict(float)
    for i in range(dias):
        dia = inicio + dt.timedelta(days=i)
        delta = var_dia + sum(e["valor"] for e in eventos[dia])
        saldo += delta
        fluxo_mes[dia.strftime("%Y-%m")] += delta
        serie.append({"data": dia.isoformat(), "saldo": round(saldo, 2),
                      "eventos": eventos.get(dia, [])})

    saldos = [s["saldo"] for s in serie]
    negativos = [s for s in serie if s["saldo"] < 0]
    i_min = int(np.argmin(saldos))
    gatilho = None
    if negativos:
        primeiro = dt.date.fromisoformat(negativos[0]["data"])
        janela = [
            e | {"data": s["data"]}
            for s in serie
            if primeiro - dt.timedelta(days=5) <= dt.date.fromisoformat(s["data"]) <= primeiro
            for e in s["eventos"] if e["valor"] < 0
        ]
        if janela:
            gatilho = min(janela, key=lambda e: e["valor"])

    meses_completos = [
        {"mes": m, "sobra": round(v, 2)} for m, v in fluxo_mes.items()
    ]
    return _py(
        {
            "inicio": inicio,
            "fim": fim_proj,
            "saldo_inicial": pf["saldo_atual"],
            "saldo_final": saldos[-1],
            "menor_saldo": saldos[i_min],
            "data_menor_saldo": serie[i_min]["data"],
            "dias_no_negativo": len(negativos),
            "primeiro_dia_negativo": negativos[0]["data"] if negativos else None,
            "evento_gatilho": gatilho,
            "parcela_nova": parcela_nova,
            "fluxo_mensal": meses_completos,
            "serie": serie,
        }
    )


def resumo_projecao(p: dict) -> dict:
    """Versão enxuta (sem a série diária) para mandar ao LLM."""
    return {k: v for k, v in p.items() if k != "serie"}


def ate_proximo_salario(d: pd.DataFrame, gasto: float = 0.0) -> dict:
    """"Até o próximo salário dá?": projeta até a véspera da maior entrada recorrente
    e mostra o efeito de um gasto à vista feito hoje, com a composição dos compromissos."""
    pf = perfil(d)
    inicio = dt.date.fromisoformat(pf["data_referencia"]) + dt.timedelta(days=1)
    entradas = pf["entradas_recorrentes"]
    salario = max(entradas, key=lambda r: r["valor"]) if entradas else None
    if salario:
        proxima = min(
            dt_ for m in range(3)
            if (dt_ := _data_no_mes(inicio.year, inicio.month + m, salario["dia"])) > inicio
        )
        dias = (proxima - inicio).days  # até a véspera da renda
    else:
        proxima, dias = None, 30

    base = projetar(d, dias, pf=pf)
    com = projetar(d, dias, compra={"valor": gasto, "parcelas": 1}, pf=pf) if gasto else base

    fixas = parcelas = outras_entradas = 0.0
    for s in base["serie"]:
        for e in s["eventos"]:
            if e["origem"] == "parcela":
                parcelas += -e["valor"]
            elif e["valor"] < 0:
                fixas += -e["valor"]
            else:
                outras_entradas += e["valor"]
    variavel = pf["gasto_variavel_diario"] * dias
    entrada_variavel = pf["entrada_variavel_diaria"] * dias

    margem = max(100.0, 0.05 * (pf["renda_mensal_media"] or 0))
    seguro = max(0.0, math.floor((base["menor_saldo"] - margem) / 10) * 10)

    def resumo(p):
        return {"saldo_final": p["saldo_final"], "menor_saldo": p["menor_saldo"],
                "data_menor_saldo": p["data_menor_saldo"], "dias_no_negativo": p["dias_no_negativo"],
                "serie": [{"data": s["data"], "saldo": s["saldo"]} for s in p["serie"]]}

    return _py({
        "data_referencia": pf["data_referencia"],
        "saldo_atual": pf["saldo_atual"],
        "proxima_renda": ({"data": proxima, "descricao": salario["descricao"], "valor": salario["valor"]}
                          if salario else None),
        "dias_ate_renda": dias,
        "gasto": gasto,
        "compromissos": {
            "contas_fixas": round(fixas, 2),
            "parcelas": round(parcelas, 2),
            "gasto_variavel_estimado": round(variavel, 2),
            "outras_entradas": round(outras_entradas + entrada_variavel, 2),
            "total_saidas": round(fixas + parcelas + variavel, 2),
        },
        "margem_seguranca": round(margem, 2),
        "gasto_maximo_seguro": seguro,
        "cabe": com["dias_no_negativo"] == 0 and com["menor_saldo"] >= margem,
        "sem_gasto": resumo(base),
        "com_gasto": resumo(com),
    })


# --------------------------------------------------------------------------- #
# comparação de caminhos (ORIENTAR)
# --------------------------------------------------------------------------- #
PRIORIDADE = ["agora", "entrada", "esperar", "menos_parcelas", "valor_menor"]


def comparar_opcoes(
    d: pd.DataFrame, valor: float, parcelas: int, taxa_mensal: float = 0.0
) -> dict:
    pf = perfil(d)
    renda = pf["renda_mensal_media"] or 1
    parc = pf["parcelas_abertas"]
    meses_liberar = max([p["restantes"] for p in parc], default=2)
    meses_liberar = min(max(meses_liberar, 1), 6)
    horizonte = max(90, 31 * (meses_liberar + 3))

    n = max(int(parcelas), 1)
    cenarios = [
        ("agora", f"{n}x de {brl(valor_parcela(valor, n, taxa_mensal))}, agora",
         {"valor": valor, "parcelas": n}),
        ("entrada", f"Entrada de {brl(round(valor * 0.3, -1))} + {n}x",
         {"valor": valor, "parcelas": n, "entrada": round(valor * 0.3, -1)}),
        ("esperar", f"Esperar {meses_liberar} {'mês' if meses_liberar == 1 else 'meses'} e fazer {n}x",
         {"valor": valor, "parcelas": n, "meses_espera": meses_liberar}),
        ("valor_menor", f"Modelo de {brl(round(valor * 0.6, -1))} em {n}x",
         {"valor": round(valor * 0.6, -1), "parcelas": n}),
    ]
    if n >= 4:
        cenarios.insert(1, ("menos_parcelas", f"{n // 2}x de {brl(valor_parcela(valor, n // 2, taxa_mensal))}",
                            {"valor": valor, "parcelas": n // 2}))

    base = projetar(d, horizonte, pf=pf)
    fixos = pf["contas_fixas_total"]
    opcoes = []
    for chave, rotulo, compra in cenarios:
        compra = compra | {"taxa_mensal": taxa_mensal}
        pj = projetar(d, horizonte, compra=compra, pf=pf)
        espera = compra.get("meses_espera", 0)
        parcelas_na_epoca = sum(p["valor_parcela"] for p in parc if p["restantes"] > espera)
        comprometimento = 100 * (fixos + parcelas_na_epoca + (pj["parcela_nova"] or 0)) / renda
        opcoes.append(
            {
                "chave": chave,
                "opcao": rotulo,
                "parcela": pj["parcela_nova"],
                "custo_total": round((pj["parcela_nova"] or 0) * compra["parcelas"]
                                     + compra.get("entrada", 0), 2),
                "dias_no_negativo": pj["dias_no_negativo"],
                "menor_saldo": pj["menor_saldo"],
                "data_menor_saldo": pj["data_menor_saldo"],
                "evento_gatilho": pj["evento_gatilho"],
                "comprometimento_renda_pct": round(comprometimento, 1),
                "serie": [{"data": s["data"], "saldo": s["saldo"]} for s in pj["serie"]],
            }
        )

    margem = max(100.0, 0.05 * renda)
    saudaveis = [o for o in opcoes if o["dias_no_negativo"] == 0 and o["menor_saldo"] >= margem]
    sem_negativo = [o for o in opcoes if o["dias_no_negativo"] == 0]
    if saudaveis:
        rec = min(saudaveis, key=lambda o: PRIORIDADE.index(o["chave"]))
    elif sem_negativo:
        rec = min(sem_negativo, key=lambda o: PRIORIDADE.index(o["chave"]))
    else:
        rec = min(opcoes, key=lambda o: (o["dias_no_negativo"], -o["menor_saldo"]))

    motivo = []
    if rec["chave"] == "agora":
        motivo.append("a compra cabe no seu fluxo sem deixar o saldo negativo")
    elif rec["chave"] == "esperar" and parc:
        motivo.append(f"suas parcelas atuais terminam em até {meses_liberar} "
                      f"{'mês' if meses_liberar == 1 else 'meses'} e liberam "
                      f"{brl(pf['parcelas_mensais_total'])} por mês")
    if rec["dias_no_negativo"] == 0:
        motivo.append("o saldo não fica negativo em nenhum dia")
    else:
        motivo.append(f"é a opção com menos dias no negativo ({rec['dias_no_negativo']})")

    return _py(
        {
            "valor_compra": valor,
            "parcelas_pedidas": n,
            "horizonte_dias": horizonte,
            "sem_compra": {
                "dias_no_negativo": base["dias_no_negativo"],
                "menor_saldo": base["menor_saldo"],
                "serie": [{"data": s["data"], "saldo": s["saldo"]} for s in base["serie"]],
            },
            "opcoes": opcoes,
            "recomendada": rec["chave"],
            "motivo": "; ".join(motivo),
            "renda_mensal": renda,
        }
    )




# --------------------------------------------------------------------------- #
# alertas proativos
# --------------------------------------------------------------------------- #
def alertas(d: pd.DataFrame) -> list[dict]:
    pf = perfil(d)
    renda = pf["renda_mensal_media"] or 0
    out: list[dict] = []

    # 1) aperto nos próximos 45 dias
    pj = projetar(d, 45, pf=pf)
    if pj["dias_no_negativo"] > 0:
        g = pj["evento_gatilho"]
        depois = f", logo depois de '{g['descricao']}' ({brl(g['valor'])})" if g else ""
        out.append({
            "tipo": "aperto",
            "prioridade": "alta",
            "titulo": "Seu saldo vai ficar negativo",
            "mensagem": (f"Em {pj['primeiro_dia_negativo']} seu saldo deve ficar negativo"
                         f"{depois}. O ponto mais baixo é {brl(pj['menor_saldo'])} em "
                         f"{pj['data_menor_saldo']}. Quer ver como evitar?"),
            "dados": resumo_projecao(pj),
        })
    elif pj["menor_saldo"] < max(100, 0.05 * renda):
        out.append({
            "tipo": "atencao",
            "prioridade": "media",
            "titulo": "Mês apertado à vista",
            "mensagem": (f"Seu saldo deve chegar a só {brl(pj['menor_saldo'])} em "
                         f"{pj['data_menor_saldo']}. Um imprevisto pode te levar ao cheque especial."),
            "dados": resumo_projecao(pj),
        })

    # 2) parcelas terminando -> dinheiro liberado
    ref = dt.date.fromisoformat(pf["data_referencia"])
    terminando = [p for p in pf["parcelas_abertas"]
                  if dt.date.fromisoformat(p["termina_em"]) <= ref + dt.timedelta(days=45)]
    if terminando:
        liberado = sum(p["valor_parcela"] for p in terminando)
        out.append({
            "tipo": "parcela_terminando",
            "prioridade": "baixa",
            "titulo": "Parcelas chegando ao fim",
            "mensagem": (f"{len(terminando)} parcelamento(s) terminam nas próximas semanas e "
                         f"liberam {brl(liberado)} por mês. Já pensou no que fazer com esse valor?"),
            "dados": {"parcelas": terminando, "valor_liberado_mes": round(liberado, 2)},
        })

    # 3) sobra -> reserva de emergência (educativo, sem indicar produto)
    pj90 = projetar(d, 90, pf=pf)
    sobras = [m["sobra"] for m in pj90["fluxo_mensal"][1:]] or [m["sobra"] for m in pj90["fluxo_mensal"]]
    sobra = float(np.mean(sobras)) if sobras else 0.0
    if pj90["dias_no_negativo"] == 0 and sobra >= max(150, 0.05 * renda):
        guardar = math.floor(sobra * 0.7 / 10) * 10
        essenciais = (pf["contas_fixas_total"] + pf["parcelas_mensais_total"]) or 0.5 * pf["gastos_mensais_medios"]
        meta = round(3 * essenciais, -1)
        # dinheiro parado na conta além de 1 mês de contas já conta como reserva
        reserva_atual = max(0.0, pj90["menor_saldo"])
        if reserva_atual >= meta:
            out.append({
                "tipo": "oportunidade_investir",
                "prioridade": "media",
                "titulo": "Seu dinheiro pode trabalhar por você",
                "mensagem": (f"Mesmo no pior dia dos próximos 3 meses você mantém {brl(reserva_atual)} "
                             f"na conta, mais do que uma reserva de 3 meses de contas ({brl(meta)}). "
                             f"E ainda sobram cerca de {brl(sobra)} por mês. Que tal definir um objetivo "
                             f"e descobrir seu perfil de investidor?"),
                "educativo": ("Dinheiro parado na conta corrente não rende. Separe a reserva de emergência "
                              "em algo de baixo risco e resgate imediato; o que passar disso pode ir para "
                              "objetivos de médio e longo prazo, de acordo com o seu perfil de investidor. "
                              "Conteúdo educativo, não é recomendação de produto."),
                "dados": {"sobra_mensal_prevista": round(sobra, 2), "reserva_atual": reserva_atual,
                          "meta_reserva": meta, "excedente": round(reserva_atual - meta, 2)},
            })
            return _py(out)
        out.append({
            "tipo": "oportunidade_reserva",
            "prioridade": "media",
            "titulo": "Está sobrando dinheiro",
            "mensagem": (f"Nos próximos meses devem sobrar cerca de {brl(sobra)} por mês. "
                         f"Guardando {brl(guardar)} por mês, você teria {brl(guardar * 6)} em 6 meses "
                         f"e {brl(guardar * 12)} em 12, rumo a uma reserva de emergência de "
                         f"{brl(meta)} (3 meses de contas fixas)."),
            "educativo": ("Reserva de emergência vem antes de investir para ganhar mais: ela cobre "
                          "imprevistos sem cheque especial. O ideal são aplicações de baixo risco "
                          "com resgate a qualquer momento. Conteúdo educativo, não é recomendação de produto."),
            "dados": {"sobra_mensal_prevista": round(sobra, 2), "valor_sugerido": guardar,
                      "reserva_6m": guardar * 6, "reserva_12m": guardar * 12, "meta_reserva": meta},
        })
    return _py(out)


# --------------------------------------------------------------------------- #
# persona para a demo
# --------------------------------------------------------------------------- #
def pontuar_para_demo(d: pd.DataFrame) -> dict:
    pf = perfil(d)
    return {
        "renda_mensal": pf["renda_mensal_media"],
        "dias_no_negativo_90d": pf["dias_no_negativo_90d"],
        "parcelas_abertas": len(pf["parcelas_abertas"]),
        "contas_fixas": len(pf["contas_fixas"]),
        "comprometimento_renda_pct": pf["comprometimento_renda_pct"],
        "bom_para_demo": bool(pf["parcelas_abertas"]) and 1 <= pf["dias_no_negativo_90d"] <= 20
        and len(pf["contas_fixas"]) >= 2,
    }
