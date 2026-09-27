"""Formatação de valores e datas como o cliente lê (padrão brasileiro)."""
from __future__ import annotations

import datetime as dt

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def brl(v: float) -> str:
    """R$ 1.235 (sem centavos: textos e mensagens)."""
    s = f"{abs(v):,.0f}".replace(",", ".")
    return f"-R$ {s}" if v < 0 else f"R$ {s}"


def brl_centavos(v: float) -> str:
    """R$ 1.234,56."""
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if v < 0 else "R$ ") + s


def brl_curto(v: float) -> str:
    """R$ 2,1 mil / -R$ 850 (rótulos de gráfico)."""
    s = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1000:
        return f"{s}R$ {a / 1000:.1f} mil".replace(".", ",")
    return f"{s}R$ {a:.0f}"


def dia_mes(d: str | dt.date) -> str:
    """10/03."""
    d = dt.date.fromisoformat(str(d)[:10]) if isinstance(d, str) else d
    return d.strftime("%d/%m")


def mes_curto(m: str) -> str:
    """'2026-03' -> 'mar/26'."""
    a, mm = str(m)[:7].split("-")
    return f"{MESES[int(mm) - 1]}/{a[2:]}"
