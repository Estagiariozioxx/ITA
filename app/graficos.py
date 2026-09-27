"""Gráficos do ITA como IMAGEM (PNG), como o banco mandaria no WhatsApp.

O tipo de gráfico sai da natureza dos dados que as tools calcularam no turno:
- evolução no tempo      -> colunas (pior saldo de cada mês) ou linhas (saldo dia a dia, cenários);
- comparação             -> barras horizontais (gastos por categoria vs a média);
- partes de um total     -> rosca (dinheiro extra: quanto quita parcelas e quanto fica guardado).
Todos os números vêm dos dados; aqui só se desenha.
"""
from __future__ import annotations

import base64
import datetime as dt
import io

import matplotlib

matplotlib.use("Agg")  # sem tela (servidor)
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.dates import DateFormatter  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

AZUL, LARANJA, VERDE, VERMELHO, CINZA = "#061B67", "#FF6200", "#00A884", "#D92D20", "#9AA6AD"
TEXTO, SUAVE, FUNDO = "#111B21", "#667781", "#FFFFFF"
CORES_CENARIO = [LARANJA, VERDE, "#6D28D9", "#0EA5E9"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": "#D1D7DB", "axes.labelcolor": SUAVE,
    "xtick.color": SUAVE, "ytick.color": SUAVE, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#EEF1F3", "grid.linewidth": 1, "axes.axisbelow": True,
})


# --------------------------------------------------------------------------- #
# utilidades
# --------------------------------------------------------------------------- #
def brl_curto(v: float) -> str:
    """R$ 2,1 mil / -R$ 850 (rótulos de gráfico)."""
    s = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1000:
        return f"{s}R$ {a / 1000:.1f} mil".replace(".", ",")
    return f"{s}R$ {a:.0f}"


def brl(v: float) -> str:
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if v < 0 else "R$ ") + s


def _mes(m: str) -> str:
    a, mm = str(m)[:7].split("-")
    return f"{MESES[int(mm) - 1]}/{a[2:]}"


def _dm(d: str) -> str:
    return f"{d[8:10]}/{d[5:7]}"


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
def colunas_mensais(meses: list[dict], titulo: str, subtitulo: str = "") -> str:
    """Pior saldo de cada mês: colunas verdes (azul) ou vermelhas (negativo), com o valor em cima."""
    fig, ax = _fig(titulo, subtitulo)
    x = [_mes(m["mes"]) for m in meses]
    y = [m["menor_saldo"] for m in meses]
    cores = [VERMELHO if v < 0 else VERDE for v in y]
    barras = ax.bar(x, y, color=cores, width=0.6, zorder=2)
    ax.axhline(0, color=TEXTO, linewidth=1)
    for b, v in zip(barras, y):
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
        x = [_mes(m["mes"]) for m in s["meses"]]
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


def barras_categorias(cats: list[dict], titulo: str, subtitulo: str = "") -> str:
    """Gasto do período vs média, por categoria (barras horizontais)."""
    cats = list(reversed(cats))
    fig, ax = _fig(titulo, subtitulo, altura=max(3.6, 0.62 * len(cats) + 1.8))
    fig.subplots_adjust(left=0.30)
    y = range(len(cats))
    ax.barh([i + 0.2 for i in y], [c["media_periodo"] for c in cats], height=0.36, color="#D1D7DB", label="sua média",
            zorder=2)
    acima = [(c.get("variacao_pct") or 0) > 5 for c in cats]  # "acima da média" = mais de 5% acima
    ax.barh([i - 0.2 for i in y], [c["gasto_periodo"] for c in cats], height=0.36, zorder=2, label="agora",
            color=[LARANJA if a else AZUL for a in acima])
    ax.set_yticks(list(y), [c["categoria"] for c in cats])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: brl_curto(v)))
    ax.xaxis.set_major_locator(MaxNLocator(4))
    ax.tick_params(axis="y", colors=TEXTO, labelsize=10.5)
    for i, c, a in zip(y, cats, acima):
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
        fig.text(0.70, yy - 0.02, f"{brl(p['valor'])} · {100 * p['valor'] / total:.0f}%",
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
            series.append({"nome": f"com {brl(a['gasto'])}", "cor": LARANJA, "pontos": a["com_gasto"]["serie"]})
        pr = a.get("proxima_renda")
        titulo = f"Seu saldo até o salário de {_dm(str(pr['data']))}" if pr else "Seu saldo nos próximos dias"
        add("linhas", titulo, linhas_diarias, series, titulo,
            f"dá para gastar até {brl(a['gasto_maximo_seguro'])} com folga" if a.get("gasto_maximo_seguro") else "")

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
                brl_curto(x["valor_extra"]), f"alívio de {brl(x.get('alivio_mensal') or 0)} por mês nas parcelas")
    return out
