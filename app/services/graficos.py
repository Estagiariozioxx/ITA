"""Gráficos do ITA como IMAGEM (PNG), como o banco mandaria no WhatsApp.

O tipo de gráfico sai da natureza dos dados que as tools calcularam no turno:
- evolução no tempo      -> colunas (pior saldo de cada mês) ou linhas (saldo dia a dia, cenários);
- comparação             -> barras horizontais (gastos por categoria vs a média);
- partes de um total     -> rosca (dinheiro extra: quanto quita parcelas e quanto fica guardado).
Todos os números vêm dos dados; aqui só se desenha.
"""
from __future__ import annotations

import base64
import json
import re
import datetime as dt
import io

import matplotlib

matplotlib.use("Agg")  # sem tela (servidor)
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.dates import DateFormatter  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Patch  # noqa: E402

from .formatos import brl_centavos, brl_curto, dia_mes, mes_curto  # noqa: E402
from .gatilhos import nome_lancamento  # noqa: E402  ("cred pgto salario" -> "Salário")
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

AZUL, LARANJA, VERDE, VERMELHO, CINZA = "#061B67", "#FF6200", "#00A884", "#D92D20", "#9AA6AD"
TEXTO, SUAVE, FUNDO = "#111B21", "#667781", "#FFFFFF"
CORES_CENARIO = [LARANJA, VERDE, "#6D28D9", "#0EA5E9"]

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": "#D1D7DB", "axes.labelcolor": SUAVE,
    "xtick.color": SUAVE, "ytick.color": SUAVE, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#EEF1F3", "grid.linewidth": 1, "axes.axisbelow": True,
})


# --------------------------------------------------------------------------- #
# utilidades
# --------------------------------------------------------------------------- #








def _fig(titulo: str, subtitulo: str = "", altura: float = 4.6):
    fig, ax = plt.subplots(figsize=(7.2, altura), dpi=150)
    fig.patch.set_facecolor(FUNDO)
    fig.subplots_adjust(left=0.17, right=0.95, top=0.80 if subtitulo else 0.85, bottom=0.16)
    fig.text(0.04, 0.94, titulo, fontsize=15, fontweight="bold", color=TEXTO, ha="left", va="top")
    if subtitulo:
        fig.text(0.04, 0.875, subtitulo, fontsize=10.5, color=SUAVE, ha="left", va="top")
    fig.text(0.97, 0.02, "ITA · Itaú", fontsize=8.5, color=CINZA, ha="right", va="bottom")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: brl_curto(v)))
    return fig, ax


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _mensal_da_serie(serie: list[dict]) -> list[dict]:
    """Série diária -> pior saldo de cada mês."""
    pior: dict[str, float] = {}
    for p in serie:
        m = p["data"][:7]
        pior[m] = min(pior.get(m, p["saldo"]), p["saldo"])
    return [{"mes": m, "menor_saldo": v} for m, v in pior.items()]


# --------------------------------------------------------------------------- #
# tipos de gráfico
# --------------------------------------------------------------------------- #
def colunas_mensais(meses: list[dict], titulo: str, subtitulo: str = "", destaque: str | None = None) -> str:
    """Pior saldo de cada mês: colunas verdes ou vermelhas (negativo), com o valor em cima.
    Com `destaque` (AAAA-MM), o mês destacado fica forte e os demais esmaecidos."""
    fig, ax = _fig(titulo, subtitulo)
    x = [mes_curto(m["mes"]) for m in meses]
    y = [m["menor_saldo"] for m in meses]
    cores = [VERMELHO if v < 0 else VERDE for v in y]
    tem = destaque and any(str(m["mes"])[:7] == destaque for m in meses)
    alfas = [1 if not tem or str(m["mes"])[:7] == destaque else 0.35 for m in meses]
    barras = ax.bar(x, y, color=cores, width=0.6, zorder=2)
    for b, a in zip(barras, alfas, strict=True):
        b.set_alpha(a)
    ax.axhline(0, color=TEXTO, linewidth=1)
    for b, v in zip(barras, y, strict=True):
        ax.annotate(brl_curto(v), (b.get_x() + b.get_width() / 2, v), ha="center", fontsize=10, fontweight="bold",
                    va="bottom" if v >= 0 else "top", xytext=(0, 4 if v >= 0 else -4), textcoords="offset points",
                    color=VERMELHO if v < 0 else VERDE)
    ax.margins(y=0.18)
    ax.grid(axis="x", visible=False)
    return _png(fig)


def linhas_diarias(series: list[dict], titulo: str, subtitulo: str = "", marcar: tuple[str, str] | None = None) -> str:
    """Saldo dia a dia; uma área para a série principal e linhas para as demais."""
    fig, ax = _fig(titulo, subtitulo)
    for i, s in enumerate(series):
        xs = [dt.date.fromisoformat(p["data"]) for p in s["pontos"]]
        ys = [p["saldo"] for p in s["pontos"]]
        ax.plot(xs, ys, color=s["cor"], linewidth=2.6, label=s["nome"], zorder=3)
        if i == 0:
            ax.fill_between(xs, ys, 0, color=s["cor"], alpha=0.08, zorder=1)
        k = min(range(len(ys)), key=ys.__getitem__)
        ax.scatter([xs[k]], [ys[k]], color=s["cor"], s=36, zorder=4)
        no_fim = k > 0.6 * len(ys)  # perto da borda direita: rótulo à esquerda do ponto
        ax.annotate(f"menor: {brl_curto(ys[k])}", (xs[k], ys[k]), xytext=(-8 if no_fim else 8, -18 if i else 10),  # 1ª acima, demais abaixo
                    textcoords="offset points", fontsize=9.5, color=s["cor"], fontweight="bold",
                    ha="right" if no_fim else "left")
    ax.axhline(0, color=VERMELHO, linewidth=1.2, linestyle=(0, (4, 3)))
    if marcar:
        d, rot = marcar
        ax.axvline(dt.date.fromisoformat(d), color=CINZA, linewidth=1, linestyle=":")
        ax.annotate(rot, (dt.date.fromisoformat(d), ax.get_ylim()[1]), xytext=(-4, -12), textcoords="offset points",
                    ha="right", fontsize=9, color=SUAVE)
    ax.xaxis.set_major_formatter(DateFormatter("%d/%m"))
    if len(series) > 1:
        ax.legend(frameon=False, loc="lower left", fontsize=10)
    return _png(fig)


def linhas_mensais(series: list[dict], titulo: str, subtitulo: str = "") -> str:
    """Um caminho por linha (pior saldo de cada mês), com o recomendado destacado."""
    linhas_leg = -(-len(series) // 2)  # legenda em 2 colunas, embaixo do gráfico
    fig, ax = _fig(titulo, subtitulo, altura=4.4 + 0.26 * linhas_leg)
    fig.subplots_adjust(bottom=0.10 + 0.058 * linhas_leg)
    for s in series:
        x = [mes_curto(m["mes"]) for m in s["meses"]]
        ax.plot(x, [m["menor_saldo"] for m in s["meses"]], color=s["cor"], label=s["nome"],
                linewidth=3.4 if s.get("destaque") else 2, marker="o", markersize=4,
                linestyle="--" if s.get("base") else "-", zorder=3 if s.get("destaque") else 2)
    ax.axhline(0, color=VERMELHO, linewidth=1.2, linestyle=(0, (4, 3)))
    ax.legend(frameon=False, fontsize=10, ncol=2, loc="upper center", bbox_to_anchor=(0.45, -0.1),
              handlelength=2.4, columnspacing=1.6)
    n = max(len(s["meses"]) for s in series)
    if n > 8:  # muitos meses: mostra 1 a cada `passo` para não amontoar
        passo = -(-n // 8)
        for j, rot in enumerate(ax.get_xticklabels()):
            rot.set_visible(j % passo == 0)
    return _png(fig)


def barras_categorias(cats: list[dict], titulo: str, subtitulo: str = "", destaque: str | None = None) -> str:
    """Gasto do período vs média, por categoria (barras horizontais). Com `destaque`, só a categoria
    destacada fica em laranja."""
    cats = list(reversed(cats))
    fig, ax = _fig(titulo, subtitulo, altura=max(3.6, 0.62 * len(cats) + 1.8))
    fig.subplots_adjust(left=0.30)
    y = range(len(cats))
    ax.barh([i + 0.2 for i in y], [c["media_periodo"] for c in cats], height=0.36, color="#D1D7DB", label="sua média",
            zorder=2)
    if destaque and any(c["categoria"].lower() == destaque.lower() for c in cats):
        acima = [c["categoria"].lower() == destaque.lower() for c in cats]
    else:
        acima = [(c.get("variacao_pct") or 0) > 5 for c in cats]  # "acima da média" = mais de 5% acima
    ax.barh([i - 0.2 for i in y], [c["gasto_periodo"] for c in cats], height=0.36, zorder=2, label="agora",
            color=[LARANJA if a else AZUL for a in acima])
    ax.set_yticks(list(y), [c["categoria"] for c in cats])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: brl_curto(v)))
    ax.xaxis.set_major_locator(MaxNLocator(4))
    ax.tick_params(axis="y", colors=TEXTO, labelsize=10.5)
    for i, c, a in zip(y, cats, acima, strict=True):
        if c.get("variacao_pct") is not None and abs(c["variacao_pct"]) >= 1:
            ax.annotate(f"{c['variacao_pct']:+.0f}%", (c["gasto_periodo"], i - 0.2), xytext=(4, 0),
                        textcoords="offset points", va="center", fontsize=9.5, fontweight="bold",
                        color=LARANJA if a else AZUL)
    ax.grid(axis="y", visible=False)
    ax.margins(x=0.15)
    ax.legend(frameon=False, loc="lower right", fontsize=9.5)
    return _png(fig)


def rosca(partes: list[dict], titulo: str, centro: str, subtitulo: str = "") -> str:
    """Partes de um total (ex.: quanto do dinheiro extra quita parcelas e quanto fica guardado)."""
    partes = [p for p in partes if p["valor"] > 0]
    fig, ax = _fig(titulo, subtitulo, altura=4.4)
    ax.grid(False)
    ax.set_axis_off()
    fig.subplots_adjust(left=0.02, right=0.62, bottom=0.04)
    ax.pie([p["valor"] for p in partes], colors=[p["cor"] for p in partes], startangle=90, counterclock=False,
           wedgeprops={"width": 0.36, "edgecolor": "white", "linewidth": 2})
    ax.text(0, 0, centro, ha="center", va="center", fontsize=12.5, fontweight="bold", color=TEXTO)
    total = sum(p["valor"] for p in partes) or 1
    for i, p in enumerate(partes):
        yy = 0.66 - i * 0.16
        fig.add_artist(FancyBboxPatch((0.66, yy - 0.012), 0.022, 0.05, transform=fig.transFigure,
                                      boxstyle="round,pad=0.004", color=p["cor"]))
        fig.text(0.70, yy + 0.03, p["rotulo"], fontsize=10.5, color=TEXTO, va="top")
        fig.text(0.70, yy - 0.02, f"{brl_centavos(p['valor'])} · {100 * p['valor'] / total:.0f}%",
                 fontsize=10, color=SUAVE, va="top")
    return _png(fig)


# --------------------------------------------------------------------------- #
# o que desenhar para cada tipo de dado do turno
# --------------------------------------------------------------------------- #
def gerar(tela: dict) -> list[dict]:
    """Imagens dos dados calculados no turno. Cada falha vira ausência do gráfico, nunca erro no chat."""
    out: list[dict] = []

    def add(tipo, titulo, fn, *a, **kw):
        try:
            out.append({"tipo": tipo, "titulo": titulo, "src": fn(*a, **kw)})
        except Exception:  # noqa: BLE001 - gráfico é enfeite: se falhar, a resposta segue sem ele
            pass
        finally:
            plt.close("all")

    sim = tela.get("simulacao") or {}
    if sim.get("cenarios"):
        rec = (sim.get("sugestao_da_regra") or {}).get("chave")
        series = [{"nome": "sem decidir", "cor": CINZA, "meses": sim["sem_decisao"].get("projecao_mensal") or [],
                   "base": True}]
        for i, c in enumerate(sim["cenarios"]):
            series.append({"nome": ("★ " if c["chave"] == rec else "") + f"caminho {c['chave']}",
                           "cor": CORES_CENARIO[i % 4], "meses": c.get("projecao_mensal") or [],
                           "destaque": c["chave"] == rec})
        series = [s for s in series if len(s["meses"]) > 1]
        if series:
            add("linhas", "Seus caminhos, mês a mês", linhas_mensais, series, "Pior saldo de cada mês em cada caminho",
                "abaixo da linha vermelha = conta no negativo")
    elif (tela.get("comparacao") or {}).get("opcoes"):
        # comparação do atalho "Simular uma compra" (engine.comparar_opcoes): séries diárias -> pior saldo do mês
        cp = tela["comparacao"]
        series = [{"nome": "sem a compra", "cor": CINZA, "meses": _mensal_da_serie(cp["sem_compra"]["serie"]),
                   "base": True}]
        for i, o in enumerate(cp["opcoes"]):
            series.append({"nome": ("★ " if o["chave"] == cp["recomendada"] else "") + o["opcao"][:28],
                           "cor": CORES_CENARIO[i % 4], "meses": _mensal_da_serie(o["serie"]),
                           "destaque": o["chave"] == cp["recomendada"]})
        add("linhas", "Seus caminhos, mês a mês", linhas_mensais, series[:5], "Pior saldo de cada mês em cada caminho",
            "abaixo da linha vermelha = conta no negativo")
    elif tela.get("projecao"):
        pj = tela["projecao"]
        meses = pj.get("projecao_mensal") or (_mensal_da_serie(pj["serie"]) if pj.get("serie") else [])
        if len(meses) > 1:
            neg = pj.get("dias_no_negativo")
            add("colunas", "Pior saldo de cada mês", colunas_mensais, meses, "Pior saldo de cada mês",
                f"{neg} dia(s) no negativo nos próximos {len(pj.get('serie') or []) or 90} dias" if neg
                else "seu saldo não fica negativo no período")

    a = tela.get("ate_salario") or {}
    if (a.get("sem_gasto") or {}).get("serie"):
        series = [{"nome": "sem o gasto", "cor": AZUL, "pontos": a["sem_gasto"]["serie"]}]
        if a.get("gasto"):
            series.append({"nome": f"com {brl_centavos(a['gasto'])}", "cor": LARANJA, "pontos": a["com_gasto"]["serie"]})
        pr = a.get("proxima_renda")
        titulo = f"Seu saldo até o salário de {dia_mes(str(pr['data']))}" if pr else "Seu saldo nos próximos dias"
        add("linhas", titulo, linhas_diarias, series, titulo,
            f"dá para gastar até {brl_centavos(a['gasto_maximo_seguro'])} com folga" if a.get("gasto_maximo_seguro") else "")

    g = tela.get("gastos_categorias") or {}
    cats = [c for c in g.get("categorias") or [] if c.get("gasto_periodo", 0) > 0][:6]
    if cats:
        add("barras", "Seus gastos vs sua média", barras_categorias, cats, "Seus gastos vs sua média",
            f"últimos {g.get('periodo_dias', 30)} dias · laranja = acima da média")

    x = tela.get("dinheiro_extra") or {}
    if x.get("valor_extra"):
        partes = [{"rotulo": "quitar parcelas", "valor": x.get("usado_para_quitar") or 0, "cor": LARANJA},
                  {"rotulo": "guardar", "valor": x.get("guardado") or 0, "cor": VERDE}]
        if sum(p["valor"] for p in partes) > 0:
            add("rosca", "Como usar o dinheiro extra", rosca, partes, "Como usar o dinheiro extra",
                brl_curto(x["valor_extra"]), f"alívio de {brl_centavos(x.get('alivio_mensal') or 0)} por mês nas parcelas")
    return out


# --------------------------------------------------------------------------- #
# tipos novos (usados quando o agente escolhe o gráfico)
# --------------------------------------------------------------------------- #
def saldo_dias(serie: list[dict], titulo: str, subtitulo: str = "") -> str:
    """Saldo dia a dia com as maiores contas que saem (e a maior entrada) marcadas no dia em que caem."""
    fig, ax = _fig(titulo, subtitulo)
    xs = [dt.date.fromisoformat(p["data"]) for p in serie]
    ys = [p["saldo"] for p in serie]
    ax.plot(xs, ys, color=AZUL, linewidth=2.6, zorder=3)
    ax.fill_between(xs, ys, 0, where=[v < 0 for v in ys], color=VERMELHO, alpha=0.12, zorder=1, interpolate=True)
    ax.fill_between(xs, ys, 0, where=[v >= 0 for v in ys], color=AZUL, alpha=0.06, zorder=1, interpolate=True)
    ax.axhline(0, color=VERMELHO, linewidth=1.2, linestyle=(0, (4, 3)))
    eventos = [(dt.date.fromisoformat(p["data"]), p["saldo"], e) for p in serie for e in p.get("eventos") or []]
    saidas = sorted([e for e in eventos if e[2]["valor"] < 0], key=lambda e: e[2]["valor"])[:3]
    entradas = sorted([e for e in eventos if e[2]["valor"] > 0], key=lambda e: -e[2]["valor"])[:1]
    for d, s, e in saidas + entradas:
        cor = VERDE if e["valor"] > 0 else LARANJA
        ax.scatter([d], [s], color=cor, s=40, zorder=4)
        rot = f"{nome_lancamento(e['descricao'])[:18]} {brl_curto(e['valor'])}"
        ax.annotate(rot, (d, s), xytext=(0, 12 if e["valor"] > 0 else -16), textcoords="offset points",
                    ha="center", fontsize=8.8, color=cor, fontweight="bold")
    ax.xaxis.set_major_formatter(DateFormatter("%d/%m"))
    ax.margins(y=0.15)
    return _png(fig)


def barras_h(itens: list[dict], titulo: str, subtitulo: str = "", destaque: str | None = None) -> str:
    """Barras horizontais simples (ex.: lançamentos que mais pesaram), com o item destacado em laranja."""
    itens = list(reversed(itens))
    fig, ax = _fig(titulo, subtitulo, altura=max(3.4, 0.5 * len(itens) + 1.9))
    fig.subplots_adjust(left=0.32)
    tem = bool(destaque) and any(str(i["rotulo"]).lower() == destaque.lower() for i in itens)
    if tem:
        cores = [LARANJA if str(i["rotulo"]).lower() == destaque.lower() else "#C3CCD1" for i in itens]
    else:
        cores = [AZUL] * len(itens)
        cores[-1] = LARANJA  # sem destaque: o maior em laranja
    y = list(range(len(itens)))
    ax.barh(y, [i["valor"] for i in itens], color=cores, height=0.6, zorder=2)
    ax.set_yticks(y, [str(i["rotulo"])[:26] for i in itens])
    ax.tick_params(axis="y", colors=TEXTO, labelsize=10.5)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: brl_curto(v)))
    ax.xaxis.set_major_locator(MaxNLocator(4))
    for k, i in zip(y, itens, strict=True):
        extra = f" · {i['extra']}" if i.get("extra") else ""
        ax.annotate(brl_curto(i["valor"]) + extra, (i["valor"], k), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=9.5, color=TEXTO)
    ax.grid(axis="y", visible=False)
    ax.margins(x=0.22)
    return _png(fig)


def custo_caminhos(caminhos: list[dict], titulo: str, subtitulo: str = "", destaque: str | None = None) -> str:
    """Custo total de cada caminho, separando o valor do bem e o que é juros/taxa."""
    caminhos = list(reversed(caminhos))
    fig, ax = _fig(titulo, subtitulo, altura=max(3.4, 0.62 * len(caminhos) + 1.9))
    fig.subplots_adjust(left=0.34)
    y = list(range(len(caminhos)))
    base = [max(0.0, c["custo_total"] - c["juros"]) for c in caminhos]
    juros = [max(0.0, c["juros"]) for c in caminhos]
    alfa = [1 if not destaque or c["chave"] == destaque else 0.45 for c in caminhos]
    b1 = ax.barh(y, base, color=AZUL, height=0.56, zorder=2, label="valor")
    b2 = ax.barh(y, juros, left=base, color=LARANJA, height=0.56, zorder=2, label="juros e taxas")
    for barras in (b1, b2):
        for b, a in zip(barras, alfa, strict=True):
            b.set_alpha(a)
    ax.set_yticks(y, [("★ " if c["chave"] == destaque else "") + c["rotulo"][:30] for c in caminhos])
    ax.tick_params(axis="y", colors=TEXTO, labelsize=10)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: brl_curto(v)))
    ax.xaxis.set_major_locator(MaxNLocator(4))
    for k, c in zip(y, caminhos, strict=True):
        ax.annotate(brl_curto(c["custo_total"]), (c["custo_total"], k), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=9.5, fontweight="bold", color=TEXTO)
    ax.grid(axis="y", visible=False)
    ax.margins(x=0.2)
    # legenda acima do gráfico, com as cores cheias (as barras podem estar esmaecidas pelo destaque)
    ax.legend(handles=[Patch(color=AZUL, label="valor"), Patch(color=LARANJA, label="juros e taxas")],
              frameon=False, fontsize=9.5, ncol=2, loc="lower right", bbox_to_anchor=(1, 1.0))
    return _png(fig)


# --------------------------------------------------------------------------- #
# escolha do agente: "GRAFICO: {...}" na última linha da resposta
# --------------------------------------------------------------------------- #
_LINHA = re.compile(r"^[ \t]*[*_`]*GR[AÁ]FICO[*_`]*[ \t]*:[ \t]*(.*?)[ \t]*$", re.I | re.M)


def extrair_escolha(texto: str) -> tuple[str, dict | None]:
    """Tira a linha de controle do texto e devolve (texto_limpo, escolha ou None)."""
    escolha = None
    for m in _LINHA.finditer(texto or ""):
        bruto = m.group(1).strip().strip("`")
        if "{" not in bruto:
            continue
        try:
            obj = json.loads(bruto[bruto.find("{"):bruto.rfind("}") + 1])
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("tipo") and str(obj["tipo"]).lower() != "nenhum":
            escolha = obj
    limpo = _LINHA.sub("", texto or "").rstrip()
    return re.sub(r"\n{3,}", "\n\n", limpo), escolha


def _titulo_ok(titulo, resposta: str, padrao: str) -> str:
    """Título do agente, se curto e sem número que não esteja no texto da resposta."""
    t = " ".join(str(titulo or "").split())[:70]
    if not t:
        return padrao
    nums_texto = set(re.findall(r"\d+", resposta or ""))
    return t if all(n in nums_texto for n in re.findall(r"\d+", t)) else padrao


def escolhido(tela: dict, escolha: dict | None, resposta: str = "") -> list[dict]:
    """O gráfico que o agente escolheu (0 ou 1 imagem), desenhado só com os dados das tools do turno.
    Sem escolha, sem gráfico. Escolha inválida (tipo sem os dados da tool) também não gera gráfico."""
    if not escolha:
        return []
    tipo = str(escolha.get("tipo") or "").strip().lower()
    destaque = escolha.get("destaque")
    destaque = str(destaque).strip() if destaque not in (None, "") else None

    def feito(t, padrao, desenhar):
        titulo = _titulo_ok(escolha.get("titulo"), resposta, padrao)
        try:
            return [{"tipo": t, "titulo": titulo, "escolhido_pelo_agente": True, "src": desenhar(titulo)}]
        except Exception:  # noqa: BLE001 - gráfico é enfeite: se falhar, a resposta segue sem ele
            return []
        finally:
            plt.close("all")

    pj, sim = tela.get("projecao") or {}, tela.get("simulacao") or {}
    g, lanc = tela.get("gastos_categorias") or {}, tela.get("lancamentos") or {}
    rotulos = {c.get("chave"): c.get("descricao") or f"caminho {c.get('chave')}"
               for c in (tela.get("proposta") or {}).get("cenarios") or []}

    if tipo == "saldo_meses" and pj:
        meses = pj.get("projecao_mensal") or (_mensal_da_serie(pj["serie"]) if pj.get("serie") else [])
        if len(meses) > 1:
            neg = pj.get("dias_no_negativo")
            sub = f"{neg} dia(s) no negativo no período" if neg else "seu saldo não fica negativo no período"
            mes = (destaque or "")[:7] or None
            return feito("colunas", "Pior saldo de cada mês", lambda t: colunas_mensais(meses, t, sub, destaque=mes))
    if tipo == "saldo_dias" and pj.get("serie"):
        return feito("linhas", "Seu saldo dia a dia",
                     lambda t: saldo_dias(pj["serie"], t, "as contas que mais pesam aparecem no dia em que caem"))
    a = tela.get("ate_salario") or {}
    if tipo == "saldo_ate_salario" and (a.get("sem_gasto") or {}).get("serie"):
        series = [{"nome": "sem o gasto", "cor": AZUL, "pontos": a["sem_gasto"]["serie"]}]
        if a.get("gasto"):
            series.append({"nome": f"com {brl_centavos(a['gasto'])}", "cor": LARANJA, "pontos": a["com_gasto"]["serie"]})
        sub = f"dá para gastar até {brl_centavos(a['gasto_maximo_seguro'])} com folga" if a.get("gasto_maximo_seguro") else ""
        return feito("linhas", "Seu saldo até o salário", lambda t: linhas_diarias(series, t, sub))
    cats = [c for c in g.get("categorias") or [] if c.get("gasto_periodo", 0) > 0]
    if tipo == "categorias" and cats:
        sub = f"últimos {g.get('periodo_dias', 30)} dias · barra cinza = sua média"
        return feito("barras", "Seus gastos vs sua média",
                     lambda t: barras_categorias(cats[:6], t, sub, destaque=destaque))
    if tipo == "divisao_gastos" and cats:
        cores = [LARANJA, AZUL, VERDE, "#6D28D9"]
        top = sorted(cats, key=lambda c: -c["gasto_periodo"])
        partes = [{"rotulo": c["categoria"], "valor": c["gasto_periodo"], "cor": cores[i]} for i, c in enumerate(top[:4])]
        resto = sum(c["gasto_periodo"] for c in top[4:])
        if resto > 0:
            partes.append({"rotulo": "outros", "valor": resto, "cor": CINZA})
        total = sum(p["valor"] for p in partes)
        sub = f"últimos {g.get('periodo_dias', 30)} dias"
        return feito("rosca", "Para onde vai o seu dinheiro", lambda t: rosca(partes, t, brl_curto(total), sub))
    if tipo == "maiores_gastos" and lanc.get("principais"):
        itens = [{"rotulo": p["descricao"], "valor": p["total"], "extra": f"{p['vezes']}x"}
                 for p in lanc["principais"][:7]]
        per = (lanc.get("periodo") or {}).get("dias")
        sub = f"total de {brl_centavos(lanc.get('total_gasto') or 0)}" + (f" em {per} dias" if per else "")
        return feito("barras", "O que mais pesou", lambda t: barras_h(itens, t, sub, destaque=destaque))
    if tipo == "caminhos" and sim.get("cenarios"):
        rec = destaque or (sim.get("sugestao_da_regra") or {}).get("chave")
        series = [{"nome": "sem decidir", "cor": CINZA, "base": True,
                   "meses": (sim.get("sem_decisao") or {}).get("projecao_mensal") or []}]
        for i, c in enumerate(sim["cenarios"]):
            nome = f"{c['chave']}) {rotulos.get(c['chave'], 'caminho')}"[:30]
            series.append({"nome": ("★ " if c["chave"] == rec else "") + nome, "cor": CORES_CENARIO[i % 4],
                           "meses": c.get("projecao_mensal") or [], "destaque": c["chave"] == rec})
        series = [s for s in series if len(s["meses"]) > 1]
        if series:
            sub = "pior saldo de cada mês · abaixo da linha vermelha = negativo"
            return feito("linhas", "Seus caminhos, mês a mês", lambda t: linhas_mensais(series, t, sub))
    if tipo == "custo_caminhos" and sim.get("cenarios"):
        caminhos = [{"chave": c["chave"], "rotulo": f"{c['chave']}) {rotulos.get(c['chave'], 'caminho')}",
                     "custo_total": float(c.get("custo_total") or 0), "juros": float(c.get("juros_e_taxas") or 0)}
                    for c in sim["cenarios"] if c.get("custo_total")]
        if caminhos:
            return feito("barras", "Quanto custa cada caminho",
                         lambda t: custo_caminhos(caminhos, t, "valor + juros e taxas", destaque=destaque))
    x = tela.get("dinheiro_extra") or {}
    if tipo == "dinheiro_extra" and x.get("valor_extra"):
        partes = [{"rotulo": "quitar parcelas", "valor": x.get("usado_para_quitar") or 0, "cor": LARANJA},
                  {"rotulo": "guardar", "valor": x.get("guardado") or 0, "cor": VERDE}]
        if sum(p["valor"] for p in partes) > 0:
            sub = f"alívio de {brl_centavos(x.get('alivio_mensal') or 0)} por mês nas parcelas"
            return feito("rosca", "Como usar o dinheiro extra",
                         lambda t: rosca(partes, t, brl_curto(x["valor_extra"]), sub))
    return []
