"""Contas por trás das tools dos agentes: raio-X, projeção e simulação de cenários.

Os agentes decidem o que perguntar (quais cenários, qual período); este módulo
responde com números calculados em código, a partir do extrato no BigQuery e do
motor em engine.py. Nada aqui chama o Gemini.
"""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd

from . import config, engine
from .engine import _data_no_mes, _py, _somar_meses, valor_parcela

MAX_DIAS = 31 * 60  # horizonte máximo das simulações: 5 anos
TAXA_ADM_CONSORCIO_HIPOTETICA = 0.15


def _inicio(pf: dict) -> dt.date:
    return dt.date.fromisoformat(pf["data_referencia"]) + dt.timedelta(days=1)


def _dia_salario(pf: dict) -> int | None:
    entradas = pf["entradas_recorrentes"]
    return max(entradas, key=lambda r: r["valor"])["dia"] if entradas else None


def _serie_mensal(pj: dict) -> list[dict]:
    """Pior saldo de cada mês (para gráfico e para o agente ler sem a série diária)."""
    s = pd.DataFrame(pj["serie"])
    s["mes"] = s["data"].str[:7]
    return [{"mes": m, "menor_saldo": round(float(v), 2)} for m, v in s.groupby("mes")["saldo"].min().items()]


# --------------------------------------------------------------------------- #
# consultar_perfil
# --------------------------------------------------------------------------- #
def contexto(pf: dict, alertas: list[dict]) -> dict:
    tipos = {a["tipo"] for a in alertas}
    return _py({
        "data_referencia": pf["data_referencia"],
        "saldo_atual": pf["saldo_atual"],
        "renda_mensal": pf["renda_mensal_media"],
        "dia_salario": _dia_salario(pf),
        "gastos_mensais": pf["gastos_mensais_medios"],
        "sobra_mensal": pf["sobra_mensal_media"],
        "contas_fixas": [{"descricao": f["descricao"], "valor": f["valor"], "dia": f["dia"]}
                         for f in pf["contas_fixas"]],
        "entradas_recorrentes": [{"descricao": f["descricao"], "valor": f["valor"], "dia": f["dia"]}
                                 for f in pf["entradas_recorrentes"]],
        "parcelas_abertas": [{"descricao": p["descricao"], "valor_parcela": p["valor_parcela"],
                              "parcela_atual": p["parcela_atual"], "parcela_total": p["parcela_total"],
                              "termina_em": p["termina_em"]} for p in pf["parcelas_abertas"]],
        "comprometimento_renda_pct": pf["comprometimento_renda_pct"],
        "gasto_variavel_mensal": pf["gasto_variavel_diario"] * 30,
        "dias_no_negativo_recentes": pf["dias_no_negativo_90d"],
        "risco_saldo_negativo": "aperto" in tipos,
        "parcela_terminando_em_breve": "parcela_terminando" in tipos,
        "top_categorias_mes": pf["top_categorias_mes"],
        "alertas": [a["mensagem"] for a in alertas],
    })


# --------------------------------------------------------------------------- #
# projetar_saldo
# --------------------------------------------------------------------------- #
def projecao(d: pd.DataFrame, pf: dict, dias: int) -> dict:
    pj = engine.projetar(d, max(7, min(int(dias), 365)), pf=pf)
    return _py({**engine.resumo_projecao(pj), "projecao_mensal": _serie_mensal(pj)})


# --------------------------------------------------------------------------- #
# simular_cenarios
# --------------------------------------------------------------------------- #
def _num(v, padrao=0.0) -> float:
    try:
        return float(v) if v not in (None, "") else padrao
    except (TypeError, ValueError):
        return padrao


def _fluxos(c: dict, pf: dict) -> tuple[list[dict], dict]:
    """Converte um cenário do PROPOR em lançamentos futuros e metadados."""
    inicio = _inicio(pf)
    venc = config.DIA_VENCIMENTO_PADRAO
    dia_ap = _dia_salario(pf) or 5
    t = c.get("tipo", "compra")
    v = _num(c.get("valor"))
    n = max(1, min(int(_num(c.get("parcelas"), 1)), 120))
    e = max(0.0, min(_num(c.get("entrada")), v))
    esp = max(0, min(int(_num(c.get("meses_espera"))), 60))
    taxa = _num(c.get("taxa_juros_mensal"))
    taxa = taxa / 100 if taxa > 1 else taxa  # veio em % em vez de decimal
    aporte = _num(c.get("aporte_mensal"))
    if aporte <= 0:
        sobra = pf["sobra_mensal_media"] or 0
        aporte = max(50.0, math.ceil((0.7 * sobra if sobra > 0 else 0.1 * pf["renda_mensal_media"]) / 10) * 10)
    extras: list[dict] = []
    parcela = aporte_usado = None

    def parcelas(base: dt.date, principal: float, qtd: int, i: float, rotulo: str):
        p = valor_parcela(principal, qtd, i)
        datas = [_data_no_mes(base.year, base.month + k, venc) for k in range(1, qtd + 1)]
        extras.extend({"data": x, "valor": -p, "descricao": f"{rotulo} ({k}/{qtd})", "origem": "cenario"}
                      for k, x in enumerate(datas, 1))
        return p, datas[-1]

    def guardar(meta: float) -> dt.date:
        m = max(1, math.ceil(meta / aporte))
        pula = 0 if _data_no_mes(inicio.year, inicio.month, dia_ap) >= inicio else 1
        datas = [_data_no_mes(inicio.year, inicio.month + pula + k, dia_ap) for k in range(m)]
        extras.extend({"data": x, "valor": -aporte, "descricao": f"guardar para o objetivo ({k}/{m})",
                       "origem": "objetivo"} for k, x in enumerate(datas, 1))
        return datas[-1]

    data_bem = None
    if t == "juntar_entrada":
        e = e or math.ceil(0.3 * v / 10) * 10
        aporte_usado = aporte
        data_bem = guardar(e)
        parcela, fim = parcelas(data_bem, v - e, n, taxa, "financiamento")
        custo = e + parcela * n
    elif t == "consorcio":
        adm = taxa or TAXA_ADM_CONSORCIO_HIPOTETICA
        parcela = v * (1 + adm) / n
        # primeira parcela no próximo vencimento a partir do início da simulação
        base = inicio if _data_no_mes(inicio.year, inicio.month, venc) < inicio else _somar_meses(inicio, -1)
        _, fim = parcelas(base, v * (1 + adm), n, 0.0, "consórcio")
        custo = v * (1 + adm)
    elif t == "poupar":
        aporte_usado = aporte
        data_bem = guardar(v)
        custo, fim = v, data_bem
    else:  # compra / financiamento
        data_bem = _somar_meses(inicio, esp) if esp else inicio
        if e:
            extras.append({"data": data_bem, "valor": -e, "descricao": "entrada", "origem": "cenario"})
        if n <= 1 and not e:
            extras.append({"data": data_bem, "valor": -v, "descricao": "compra à vista", "origem": "cenario"})
            custo, fim = v, data_bem
        else:
            parcela, fim = parcelas(data_bem, v - e, n, taxa, "compra")
            custo = e + parcela * n

    return extras, {
        "parcela_mensal": parcela, "aporte_mensal": aporte_usado,
        "custo_total": custo, "juros_e_taxas": max(0.0, custo - v),
        "data_ter_o_bem": data_bem,
        "meses_ate_ter_o_bem": ((data_bem.year - inicio.year) * 12 + data_bem.month - inicio.month)
        if data_bem else None,
        "data_ultimo_pagamento": fim,
        "inicio_divida": (data_bem or inicio) if parcela else None,
    }


def _resultado(chave: str, pj: dict, info: dict, pf: dict) -> dict:
    renda = pf["renda_mensal_media"] or 1
    ini = info.get("inicio_divida")
    parcelas_vigentes = sum(p["valor_parcela"] for p in pf["parcelas_abertas"]
                            if ini is None or dt.date.fromisoformat(p["termina_em"]) >= ini)
    comprom = 100 * (pf["contas_fixas_total"] + parcelas_vigentes + (info.get("parcela_mensal") or 0)) / renda
    return {
        "chave": chave, **info,
        "menor_saldo_previsto": pj["menor_saldo"], "data_menor_saldo": pj["data_menor_saldo"],
        "dias_no_negativo": pj["dias_no_negativo"], "primeiro_dia_negativo": pj["primeiro_dia_negativo"],
        "evento_gatilho": pj["evento_gatilho"], "saldo_final": pj["saldo_final"],
        "comprometimento_renda_pct": round(comprom, 1),
        "projecao_mensal": _serie_mensal(pj),
    }


def simular(d: pd.DataFrame, pf: dict, cenarios: list[dict]) -> dict:
    """Simula todos os cenários no mesmo horizonte, dia a dia, e devolve as métricas de cada um."""
    inicio = _inicio(pf)
    prep = [(c, *_fluxos(c, pf)) for c in cenarios if _num(c.get("valor")) > 0]
    ultimo = max([max(i["data_ultimo_pagamento"], i["data_ter_o_bem"] or inicio) for _, _, i in prep],
                 default=inicio)
    horizonte = max(90, min(MAX_DIAS, (ultimo - inicio).days + 92))
    base = engine.projetar(d, horizonte, pf=pf)
    vazio = {"parcela_mensal": None, "aporte_mensal": None, "custo_total": 0, "juros_e_taxas": 0,
             "data_ter_o_bem": None, "meses_ate_ter_o_bem": None, "data_ultimo_pagamento": None,
             "inicio_divida": None}
    sim = _py({
        "horizonte_dias": horizonte,
        "margem_seguranca": max(100.0, 0.05 * (pf["renda_mensal_media"] or 0)),
        "sem_decisao": _resultado("sem_decisao", base, vazio, pf),
        "cenarios": [_resultado(c.get("chave", "?"), engine.projetar(d, horizonte, pf=pf, extras=ex), info, pf)
                     for c, ex, info in prep],
    })
    sim["sugestao_da_regra"] = sugestao(sim)
    return sim


def sem_series(sim: dict) -> dict:
    """Versão para o agente ler: sem a projeção mês a mês de cada cenário."""
    tira = lambda r: {k: v for k, v in r.items() if k != "projecao_mensal"}  # noqa: E731
    return {**sim, "sem_decisao": tira(sim["sem_decisao"]), "cenarios": [tira(r) for r in sim["cenarios"]]}


def sugestao(sim: dict) -> dict | None:
    """Recomendação pela regra (o agente usa como base e pode divergir, justificando pela fala do cliente):
    sem dia no negativo e com folga -> menos juros -> bem mais cedo; se nenhum evita o negativo, o de menos dias."""
    cs = sim["cenarios"]
    if not cs:
        return None
    prazo = lambda c: c["meses_ate_ter_o_bem"] if c["meses_ate_ter_o_bem"] is not None else 999  # noqa: E731
    saudaveis = [c for c in cs if c["dias_no_negativo"] == 0 and c["menor_saldo_previsto"] >= sim["margem_seguranca"]]
    if saudaveis:
        r = min(saudaveis, key=lambda c: (round(c["juros_e_taxas"], -1), prazo(c)))
        return {"chave": r["chave"], "motivo": "não deixa o saldo negativo, mantém folga e tem menos juros"}
    r = min(cs, key=lambda c: (c["dias_no_negativo"], -c["menor_saldo_previsto"]))
    return {"chave": r["chave"], "motivo": "nenhum caminho evita o saldo negativo; este é o que tem menos dias no negativo"}


# --------------------------------------------------------------------------- #
# comparar_gastos
# --------------------------------------------------------------------------- #
def gastos_por_categoria(d: pd.DataFrame, dias: int = 30) -> dict:
    """Gastos dos últimos `dias` por categoria, comparados com a média dos 90 dias anteriores."""
    dias = max(7, min(int(dias), 90))
    fim = d["dt"].max()
    corte = fim - pd.Timedelta(days=dias)
    saidas = d[d["saida"]]
    atual = saidas[saidas["dt"] > corte].groupby("nom_cate_macro")["vlr"].sum()
    antes = saidas[(saidas["dt"] <= corte) & (saidas["dt"] > corte - pd.Timedelta(days=90))]
    media = antes.groupby("nom_cate_macro")["vlr"].sum() / 90 * dias  # média no mesmo tamanho de período
    linhas = []
    for cat in sorted(set(atual.index) | set(media.index)):
        a, m = float(atual.get(cat, 0.0)), float(media.get(cat, 0.0))
        linhas.append({"categoria": cat, "gasto_periodo": a, "media_periodo": m, "diferenca": a - m,
                       "variacao_pct": round(100 * (a - m) / m, 1) if m else None})
    linhas.sort(key=lambda x: x["diferenca"], reverse=True)
    total_a, total_m = float(atual.sum()), float(media.sum())
    return _py({
        "periodo_dias": dias, "ate": fim.date(),
        "total_periodo": total_a, "media_total_periodo": total_m, "diferenca_total": total_a - total_m,
        "categorias": linhas[:8],
        "maior_aumento": linhas[0] if linhas and linhas[0]["diferenca"] > 0 else None,
    })


# --------------------------------------------------------------------------- #
# simular_dinheiro_extra (PLR, 13º, bônus)
# --------------------------------------------------------------------------- #
def dinheiro_extra(d: pd.DataFrame, pf: dict, valor: float, quitar: float = 0.0) -> dict:
    """Usa parte de um dinheiro extra para quitar parcelas abertas (as de menor saldo devedor primeiro) e
    guarda o resto; compara os próximos 90 dias com e sem essa decisão."""
    valor = max(0.0, float(valor))
    quitar = max(0.0, min(float(quitar), valor))
    abertas = sorted(pf["parcelas_abertas"], key=lambda p: p["valor_parcela"] * p["restantes"])
    quitadas, usado = [], 0.0
    for p in abertas:
        devedor = p["valor_parcela"] * p["restantes"]
        if usado + devedor <= quitar + 0.01:
            quitadas.append(p)
            usado += devedor
    pf2 = dict(pf, parcelas_abertas=[p for p in pf["parcelas_abertas"] if p not in quitadas])
    antes, depois = engine.projetar(d, 90, pf=pf), engine.projetar(d, 90, pf=pf2)
    alivio = sum(p["valor_parcela"] for p in quitadas)
    guardado = valor - usado
    return _py({
        "valor_extra": valor,
        "usado_para_quitar": usado,
        "parcelas_quitadas": [{"descricao": p["descricao"], "valor_parcela": p["valor_parcela"],
                               "restantes": p["restantes"], "saldo_devedor": p["valor_parcela"] * p["restantes"]}
                              for p in quitadas],
        "parcelas_que_continuam": [{"descricao": p["descricao"], "valor_parcela": p["valor_parcela"],
                                    "termina_em": p["termina_em"]} for p in pf2["parcelas_abertas"]],
        "alivio_mensal": alivio,
        "guardado": guardado,
        "guardado_em_6_meses_com_alivio": guardado + 6 * alivio,
        "renda_comprometida_antes_pct": pf["comprometimento_renda_pct"],
        "renda_comprometida_depois_pct": round(pf["comprometimento_renda_pct"]
                                               - 100 * alivio / (pf["renda_mensal_media"] or 1), 1),
        "proximos_90_dias": {
            "sem_usar": {"menor_saldo": antes["menor_saldo"], "dias_no_negativo": antes["dias_no_negativo"]},
            "usando": {"menor_saldo": depois["menor_saldo"], "dias_no_negativo": depois["dias_no_negativo"]},
        },
    })


# --------------------------------------------------------------------------- #
# buscar_lancamentos
# --------------------------------------------------------------------------- #
def lancamentos(d: pd.DataFrame, categoria: str = "", descricao: str = "", dias: int = 90) -> dict:
    fim = d["dt"].max()
    dias = max(1, min(int(dias), 365))
    j = d[(d["dt"] > fim - pd.Timedelta(days=dias)) & d["saida"]]
    if categoria:
        j = j[j["nom_cate_macro"].str.contains(categoria, case=False, na=False)
              | j["nom_cate_micro"].astype(str).str.contains(categoria, case=False, na=False)]
    if descricao:
        j = j[j["descr"].str.contains(descricao.lower(), regex=False, na=False)]
    por_descr = j.groupby("descr")["vlr"].agg(["sum", "count"]).sort_values("sum", ascending=False).head(10)
    return _py({
        "periodo": {"de": (fim - pd.Timedelta(days=dias - 1)).date(), "ate": fim.date(), "dias": dias},
        "filtro": {"categoria": categoria or None, "descricao": descricao or None},
        "total_gasto": float(j["vlr"].sum()),
        "quantidade": int(len(j)),
        "media_mensal": float(j["vlr"].sum()) / (dias / 30),
        "principais": [{"descricao": k, "total": float(r["sum"]), "vezes": int(r["count"])}
                       for k, r in por_descr.iterrows()],
    })
