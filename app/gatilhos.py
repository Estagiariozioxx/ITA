"""Gatilhos proativos do ITA (Cenário 2): eventos detectados no extrato que fazem o ITA
chamar o cliente no WhatsApp antes de ele perguntar.

Cada gatilho é detectado por regra fixa em código, sobre o extrato real (BigQuery), e a
mensagem de abertura é um modelo com os números do motor (no WhatsApp Business, mensagens
iniciadas pela empresa usam modelos aprovados). Toda abertura é educativa, nunca oferta;
produto só pode aparecer depois, na conversa, se o motor de regras permitir (produtos.py).

Tom: positivo (fim de parcela, mês no azul), neutro (aumento de entradas, dia do salário)
ou negativo (pressão financeira, categoria fora do normal).
"""
from __future__ import annotations

import datetime as dt
import math
import re

import pandas as pd

from .engine import _data_no_mes, _py, brl

JANELA = 30          # dias do "mês atual" (terminando na data de referência do extrato)
BASE = 90            # dias de comparação antes da janela


def _dm(d) -> str:
    d = dt.date.fromisoformat(d) if isinstance(d, str) else d
    return d.strftime("%d/%m")


def _janelas(d: pd.DataFrame):
    fim = d["dt"].max()
    atual = d[d["dt"] > fim - pd.Timedelta(days=JANELA)]
    base = d[(d["dt"] <= fim - pd.Timedelta(days=JANELA)) & (d["dt"] > fim - pd.Timedelta(days=JANELA + BASE))]
    meses_base = max(1.0, (base["dt"].max() - base["dt"].min()).days / 30) if not base.empty else 1.0
    return fim, atual, base, meses_base


def nome_lancamento(descr: str) -> str:
    """Descrição do extrato como o cliente reconhece ("cart credito loja brinq parc 4/5" -> "Loja brinq")."""
    s = str(descr or "").lower()
    if "salario" in s or "salário" in s:
        return "Salário"
    s = re.sub(r"\bparc(ela)?\.?\s*\d+\s*/\s*\d+\b", " ", s)
    s = re.sub(r"\b(cart(ao|ão)?\s+(de\s+)?credito|cred|deb(ito)?|pgto|pag|compra|transf)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return (s[:1].upper() + s[1:]) if s else str(descr)


def _lanc(r) -> dict:
    return {"data": r.dt.date().isoformat(), "descricao": nome_lancamento(r.descr), "categoria": r.nom_cate_macro,
            "valor": round(float(r.vlr), 2), "saida": bool(r.saida)}


def _separar_por_mes(pf: dict) -> float:
    """Quanto sugerir guardar: 70% da sobra média, arredondado para cima de 10 em 10 (mínimo R$ 50)."""
    return max(50.0, float(math.ceil(0.7 * (pf["sobra_mensal_media"] or 0) / 10) * 10))


def _inativo(tipo, motivo):
    return {"tipo": tipo, "ativo": False, "motivo_inativo": motivo}


# --------------------------------------------------------------------------- #
# gatilhos
# --------------------------------------------------------------------------- #
def fim_parcela(d, pf, nome) -> dict:
    """Positivo: uma parcela terminou (ou termina logo) e abre folga no orçamento."""
    fim = d["dt"].max()
    p = d[d["parcelado"]].copy()
    terminadas = []
    if not p.empty:
        p["vlr_r"] = p["vlr"].round(2)
        g = p.groupby(["descr", "parcela_total", "vlr_r"]).agg(atual=("parcela_atual", "max"), ultima=("dt", "max"))
        g = g.reset_index()
        g = g[(g["atual"] >= g["parcela_total"]) & (g["ultima"] >= fim - pd.Timedelta(days=40))]
        terminadas = sorted(g.itertuples(), key=lambda r: -r.vlr_r)
        terminadas = [r for r in terminadas if r.vlr_r >= 100] or terminadas  # prefere folgas relevantes
    if terminadas:
        t = terminadas[0]
        valor, descr, quando = float(t.vlr_r), t.descr, "terminou este mês"
        detalhe = f"Parcela {int(t.parcela_total)}/{int(t.parcela_total)} paga em {_dm(t.ultima.date())}"
    else:
        prox = [x for x in pf["parcelas_abertas"]
                if dt.date.fromisoformat(x["termina_em"]) <= fim.date() + dt.timedelta(days=45)]
        if not prox:
            return _inativo("fim_parcela", "nenhuma parcela terminou nem termina nos próximos 45 dias")
        x = max(prox, key=lambda x: x["valor_parcela"])
        valor, descr, quando = x["valor_parcela"], x["descricao"], f"termina em {_dm(x['termina_em'])}"
        detalhe = f"Faltam {x['restantes']} parcela(s) · última em {_dm(x['termina_em'])}"
    descr = nome_lancamento(descr)
    return {
        "tipo": "fim_parcela", "ativo": True, "tom": "positivo", "emoji": "💰", "titulo": "Fim de parcela",
        "regra": "R009",
        "mensagem": (f"Oi, {nome}! 👋\n\nUma parcela de *{brl(valor)}* ({descr}) {quando}. Isso abre uma nova "
                     f"folga no seu orçamento.\n\nQuer ver algumas possibilidades para esse valor?"),
        "botoes": [
            {"t": "Quero sim", "pergunta": f"Minha parcela de {brl(valor)} de {descr} {quando}. "
                                          f"O que posso fazer com essa folga de {brl(valor)} por mês?"},
            {"t": "Agora não", "pergunta": None},
        ],
        "app": {"titulo": "Última parcela paga ✓" if terminadas else "Parcela chegando ao fim",
                "descricao": descr, "valor": valor, "detalhe": detalhe, "tom": "positivo"},
        "dados": {"valor_parcela": valor, "descricao": descr, "quando": quando},
    }


def pressao_financeira(d, pf, nome) -> dict:
    """Negativo: gastos subiram e o saldo ficou negativo em alguns dias."""
    fim, atual, base, meses_base = _janelas(d)
    gasto = atual.loc[atual["saida"], "vlr"].sum()
    media = base.loc[base["saida"], "vlr"].sum() / meses_base if not base.empty else 0
    dias_neg = int(atual.loc[atual["saldo_apos"] < 0, "dt"].nunique())
    if not media or gasto < 1.10 * media or dias_neg == 0:
        return _inativo("pressao_financeira", "gastos dentro da média ou sem dias no negativo nos últimos 30 dias")
    aumento = 100 * (gasto / media - 1)
    pior = atual.loc[atual["saldo_apos"].idxmin()]  # linha (Series): usar pior["dt"], não pior.dt
    return {
        "tipo": "pressao_financeira", "ativo": True, "tom": "negativo", "emoji": "⚠️", "titulo": "Pressão financeira",
        "regra": "R003",
        "mensagem": (f"Oi, {nome}. Tudo bem?\n\nPercebi que *seus gastos aumentaram* ({aumento:.0f}% acima da sua média) "
                     f"e *seu saldo ficou negativo* em {dias_neg} dia(s) este mês.\n\n"
                     f"Quer entender o que está pressionando seu orçamento?"),
        "botoes": [
            {"t": "Quero sim", "pergunta": "Por que meus gastos aumentaram e meu saldo ficou negativo este mês? "
                                                "O que está pressionando meu orçamento?"},
            {"t": "Agora não", "pergunta": None},
        ],
        "app": {"titulo": "Saldo negativo", "descricao": f"Menor saldo em {_dm(pior['dt'].date())}",
                "valor": round(float(pior["saldo_apos"]), 2),
                "detalhe": f"Gastos dos últimos 30 dias: {brl(gasto)} ({aumento:+.0f}% vs média)", "tom": "negativo"},
        "dados": {"gasto_30d": round(gasto, 2), "media_mensal": round(media, 2), "dias_no_negativo_30d": dias_neg},
    }


def aumento_entradas(d, pf, nome) -> dict:
    """Neutro: entradas subiram; o ITA confirma se é recorrente antes de recalcular (R010)."""
    fim = d["dt"].max()
    e = d[~d["saida"]]
    rec = e[e["dt"] > fim - pd.Timedelta(days=60)]
    ant = e[(e["dt"] <= fim - pd.Timedelta(days=60)) & (e["dt"] > fim - pd.Timedelta(days=180))]
    if rec.empty or ant.empty:
        return _inativo("aumento_entradas", "histórico insuficiente de entradas")
    media_rec, media_ant = rec["vlr"].sum() / 2, ant["vlr"].sum() / 4
    if media_ant <= 0 or media_rec < 1.3 * media_ant or media_rec - media_ant < 500:
        return _inativo("aumento_entradas", "entradas dos últimos 2 meses sem aumento relevante")
    aumento = 100 * (media_rec / media_ant - 1)
    maior = rec.loc[rec["vlr"].idxmax()]
    return {
        "tipo": "aumento_entradas", "ativo": True, "tom": "neutro", "emoji": "📈", "titulo": "Aumento de entradas",
        "regra": "R010",
        "mensagem": (f"Oi, {nome}! 👋\n\nPercebi um *aumento relevante nas suas entradas* nos últimos meses: em média "
                     f"*{brl(media_rec)}* por mês, {aumento:.0f}% acima do que era antes ({brl(media_ant)}).\n\n"
                     f"Esse valor passou a fazer parte da sua renda recorrente?"),
        "botoes": [
            {"t": "Sim, é recorrente", "pergunta": f"Sim, minhas entradas subiram para cerca de {brl(media_rec)} por mês "
                                                   f"e isso agora é recorrente. O que muda para mim?"},
            {"t": "Não, foi pontual", "pergunta": f"Não, o aumento nas minhas entradas foi pontual. "
                                                  f"Como devo usar esse dinheiro extra?"},
        ],
        "app": {"titulo": "Crédito recebido", "descricao": nome_lancamento(maior["descr"]),
                "valor": round(float(maior["vlr"]), 2),
                "detalhe": f"Entradas: {brl(media_rec)}/mês nos últimos 2 meses ({aumento:+.0f}%)", "tom": "positivo"},
        "dados": {"media_recente": round(media_rec, 2), "media_anterior": round(media_ant, 2)},
    }


def categoria_fora(d, pf, nome) -> dict:
    """Negativo: uma categoria de gasto disparou em relação à média do cliente."""
    fim, atual, base, meses_base = _janelas(d)
    if base.empty:
        return _inativo("categoria_fora", "histórico insuficiente")
    fixas = {f["descricao"] for f in pf["contas_fixas"]}
    a = atual[atual["saida"] & ~atual["descr"].isin(fixas)].groupby("nom_cate_macro")["vlr"].sum()
    b = base[base["saida"] & ~base["descr"].isin(fixas)].groupby("nom_cate_macro")["vlr"].sum() / meses_base
    cand = []
    for cat, v in a.items():
        if re.search(r"transf|invest|aplica|resgate|fatura|pagamento", str(cat).lower()):
            continue  # não é gasto de consumo: dinheiro mudando de lugar
        m = b.get(cat, 0)
        if m >= 100 and v >= 300 and v >= 1.5 * m and v - m >= 200:
            cand.append((v - m, cat, v, m))  # o maior aumento em reais (não em %) é o mais relevante
    if not cand:
        return _inativo("categoria_fora", "nenhuma categoria relevante 50% acima da média")
    _, cat, v, m = max(cand)
    aumento = 100 * (v / m - 1)
    top = atual[atual["saida"] & (atual["nom_cate_macro"] == cat)].nlargest(3, "vlr")
    return {
        "tipo": "categoria_fora", "ativo": True, "tom": "negativo", "emoji": "🛒", "titulo": "Gasto fora do normal",
        "regra": "R003",
        "mensagem": (f"Oi, {nome}!\n\nSeus gastos com *{cat}* estão em *{brl(v)}* nos últimos 30 dias, "
                     f"*{aumento:.0f}% acima* da sua média ({brl(m)} por mês).\n\nQuer ver o que puxou esse aumento?"),
        "botoes": [
            {"t": "Quero sim", "pergunta": f"Por que meus gastos com {cat} aumentaram tanto este mês e como posso reduzir?"},
            {"t": "Agora não", "pergunta": None},
        ],
        "app": {"titulo": f"Gastos com {cat}", "descricao": "últimos 30 dias", "valor": round(float(v), 2),
                "detalhe": f"{aumento:+.0f}% vs sua média de {brl(m)}", "tom": "negativo",
                "lancamentos": [_lanc(r) for r in top.itertuples()]},
        "dados": {"categoria": cat, "gasto_30d": round(v, 2), "media_mensal": round(m, 2)},
    }


def dia_salario(d, pf, nome) -> dict:
    """Neutro: o salário está para cair; hora de planejar antes de gastar."""
    entradas = pf["entradas_recorrentes"]
    if not entradas:
        return _inativo("dia_salario", "sem entrada recorrente identificada")
    sal = max(entradas, key=lambda r: r["valor"])
    inicio = dt.date.fromisoformat(pf["data_referencia"]) + dt.timedelta(days=1)
    data = min(x for m in range(3) if (x := _data_no_mes(inicio.year, inicio.month + m, sal["dia"])) >= inicio)
    sobra = pf["sobra_mensal_media"] or 0
    if sobra > 0 and pf["saldo_atual"] >= 0:
        separar = _separar_por_mes(pf)
        convite = (f"Que tal já separar *{brl(separar)}* para a sua reserva no dia do pagamento, "
                   f"antes de começar a gastar?")
        pergunta = f"Meu salário cai em {_dm(data)}. Como separo {brl(separar)} para a reserva e organizo o mês?"
    else:
        convite = "Quer que eu monte um plano para as contas do mês antes de você começar a gastar?"
        pergunta = f"Meu salário cai em {_dm(data)}. Como devo organizar as contas deste mês?"
    return {
        "tipo": "dia_salario", "ativo": True, "tom": "neutro", "emoji": "🗓️", "titulo": "Dia do salário",
        "regra": "R007",
        "mensagem": (f"Oi, {nome}! 👋\n\nSeu *{nome_lancamento(sal['descricao']).lower()}* de *{brl(sal['valor'])}* "
                     f"deve cair em *{_dm(data)}*.\n\n{convite}"),
        "botoes": [{"t": "Quero sim", "pergunta": pergunta}, {"t": "Agora não", "pergunta": None}],
        "app": {"titulo": "Crédito previsto", "descricao": nome_lancamento(sal["descricao"]), "valor": sal["valor"],
                "detalhe": f"Previsto para {_dm(data)}", "tom": "positivo"},
        "dados": {"data": data.isoformat(), "valor": sal["valor"]},
    }


def mes_no_azul(d, pf, nome) -> dict:
    """Positivo (R012, recuperação): 30 dias sem negativo e gastando menos que a média."""
    fim, atual, base, meses_base = _janelas(d)
    if atual.empty or base.empty:
        return _inativo("mes_no_azul", "histórico insuficiente")
    if (atual["saldo_apos"] < 0).any():
        return _inativo("mes_no_azul", "o saldo ficou negativo nos últimos 30 dias")
    gasto = atual.loc[atual["saida"], "vlr"].sum()
    media = base.loc[base["saida"], "vlr"].sum() / meses_base
    saiu_do_vermelho = bool((base["saldo_apos"] < 0).any())
    economia = media - gasto
    if economia < max(100.0, 0.05 * media) and not saiu_do_vermelho:
        return _inativo("mes_no_azul", "gastos do mês na média")
    if saiu_do_vermelho:
        destaque = "*saiu do vermelho*: nos últimos 30 dias sua conta não ficou negativa nenhuma vez"
    else:
        destaque = "*não entrou no negativo* nos últimos 30 dias"
    extra = f" e gastou *{brl(economia)} a menos* que a sua média" if economia > 0 else ""
    return {
        "tipo": "mes_no_azul", "ativo": True, "tom": "positivo", "emoji": "🎉", "titulo": "Mês no azul",
        "regra": "R012",
        "mensagem": (f"Oi, {nome}! 🎉\n\nBoa notícia: você {destaque}{extra}.\n\n"
                     f"Quer transformar essa folga em um objetivo?"),
        "botoes": [
            {"t": "Quero sim", "pergunta": "Meu mês ficou no azul e sobrou dinheiro. Como transformo essa folga "
                                                   "em um objetivo, começando pela reserva?"},
            {"t": "Agora não", "pergunta": None},
        ],
        "app": {"titulo": "Mês no azul ✓", "descricao": "últimos 30 dias sem saldo negativo",
                "valor": round(float(pf["saldo_atual"]), 2),
                "detalhe": (f"Gastos: {brl(gasto)} ({100 * (gasto / media - 1):+.0f}% vs média)" if media else ""),
                "tom": "positivo"},
        "dados": {"gasto_30d": round(gasto, 2), "media_mensal": round(media, 2), "saiu_do_vermelho": saiu_do_vermelho},
    }


DETECTORES = [fim_parcela, mes_no_azul, aumento_entradas, dia_salario, pressao_financeira, categoria_fora]
TIPOS = [f.__name__ for f in DETECTORES]


def detectar(d: pd.DataFrame, pf: dict, nome: str = "tudo bem") -> list[dict]:
    """Todos os gatilhos do cliente, ativos ou não (os inativos vêm com o motivo)."""
    return _py([f(d, pf, nome) for f in DETECTORES])


def movimentacoes(d: pd.DataFrame, limite: int = 8) -> list[dict]:
    """Últimos lançamentos (mais recentes primeiro), para a tela do app."""
    return _py([_lanc(r) for r in d.iloc[::-1].head(limite).itertuples()])
