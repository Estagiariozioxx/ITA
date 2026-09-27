"""Guardrails de saída: conferem a resposta do agente ANTES de ela chegar ao cliente.

Determinístico (regex + os dados que as tools calcularam), sem chamada ao LLM: custo ~0.
Substitui o Guardião Gemini; as regras da Res. Conjunta nº 8 ficam no prompt de cada agente,
e aqui ficam as conferências objetivas:
  1. produto do banco citado sem oferta liberada pelas regras -> o trecho sai;
  2. promessa proibida ("garantido", "sem risco", "crédito aprovado"...) -> vira linguagem neutra;
  3. oferta sem o aviso de análise de crédito -> o aviso é acrescentado;
  4. valor em R$ ou % que não aparece nos dados calculados -> registrado na trilha para auditoria.
"""
from __future__ import annotations

import itertools
import re

PRODUTOS_BANCO = {
    "financiamento": r"financiamento\s+ita[uú]",
    "consorcio": r"cons[oó]rcio\s+ita[uú]",
    "credito": r"cr[eé]dito\s+pessoal\s+ita[uú]",
}
OUTROS_PRODUTOS = r"(cart[aã]o\s+de\s+cr[eé]dito|cheque\s+especial|empr[eé]stimo|investimento|cdb|lci|lca|fundo)\s+ita[uú]"
BLOCO_OFERTA = "📌 Oferta Itaú"
AVISO_OFERTA = "_Elegibilidade simulada a partir do seu extrato; a contratação depende de análise de crédito._"

PROMESSAS = [
    (r"\brentabilidade\s+garantida\b", "rentabilidade estimada"),
    (r"\bcr[eé]dito\s+(j[aá]\s+)?aprovado\b", "crédito sujeito a análise"),
    (r"\bvoc[eê]\s+(j[aá]\s+)?est[aá]\s+aprovad[oa]\b", "você pode simular"),
    (r"\bsem\s+(nenhum\s+)?risco\b", "de baixo risco"),
    (r"\brisco\s+zero\b", "baixo risco"),
    (r"\bgarantid([oa]s?)\b", r"previst\1"),
]

# dados que as tools e o motor calcularam: fonte da verdade dos números
CHAVES_DADOS = ("contexto_cliente", "projecao", "simulacao", "ate_salario", "gastos_categorias",
                "dinheiro_extra", "lancamentos", "oferta", "gatilho", "proposta")


def _paragrafos(texto: str) -> list[str]:
    return re.split(r"\n\s*\n", texto.strip())


def _numeros(obj, fora=("serie",)) -> list[float]:
    """Todos os números de um JSON (sem as séries diárias)."""
    if isinstance(obj, bool):
        return []
    if isinstance(obj, (int, float)):
        return [abs(float(obj))]
    if isinstance(obj, dict):
        return [n for k, v in obj.items() if k not in fora for n in _numeros(v, fora)]
    if isinstance(obj, (list, tuple)):
        return [n for v in obj for n in _numeros(v, fora)]
    return []


def _valor_br(s: str) -> float | None:
    s = s.strip().replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except ValueError:
        return None


def _valores_texto(texto: str) -> list[tuple[str, float, bool]]:
    """(trecho, valor, é_percentual) de cada R$ e % do texto."""
    out = []
    for m in re.finditer(r"R\$\s?-?\s?(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)", texto):
        v = _valor_br(m.group(1))
        if v is not None:
            out.append((m.group(0), v, False))
    for m in re.finditer(r"(\d+(?:,\d+)?)\s?%", texto):
        v = _valor_br(m.group(1))
        if v is not None:
            out.append((m.group(0), v, True))
    return out


def _confere(v: float, pct: bool, base: list[float], pares: set[float]) -> bool:
    tol = 0.15 if pct else max(1.0, 0.005 * v)
    if any(abs(v - b) <= tol for b in base):
        return True
    if pct:
        return any(abs(v - 100 * b) <= tol for b in base if b <= 1)  # 0.02 -> 2%
    # contas simples que o agente pode fazer em cima dos dados: soma/diferença de dois valores e múltiplos
    return any(abs(v - s) <= tol for s in pares)


def aplicar(texto: str, estado: dict) -> tuple[str, list[dict]]:
    """Devolve o texto corrigido e a lista do que cada guardrail fez (vai para a trilha)."""
    if not texto:
        return texto, []
    acoes: list[dict] = []
    oferta = estado.get("oferta") or None
    produto_ofertado = (oferta or {}).get("produto")

    # 1) produto do banco sem oferta liberada
    paragrafos = _paragrafos(texto)
    if not oferta:
        antes = len(paragrafos)
        paragrafos = [p for p in paragrafos if not p.lstrip().startswith(BLOCO_OFERTA)]
        if len(paragrafos) != antes:
            acoes.append({"guardrail": "oferta_sem_regra", "acao": "bloco de oferta removido"})
    proibidos = [rx for prod, rx in PRODUTOS_BANCO.items() if prod != produto_ofertado] + [OUTROS_PRODUTOS]
    limpos = []
    for p in paragrafos:
        achou = next((rx for rx in proibidos if re.search(rx, p, re.I)), None)
        if achou:
            acoes.append({"guardrail": "produto_sem_oferta", "acao": "trecho removido",
                          "trecho": p[:120]})
        else:
            limpos.append(p)
    texto = "\n\n".join(limpos) if limpos else texto  # nunca devolve vazio

    # 2) promessas proibidas
    for rx, novo in PROMESSAS:
        texto, n = re.subn(rx, novo, texto, flags=re.I)
        if n:
            acoes.append({"guardrail": "promessa", "acao": f"trocado por '{novo}'", "vezes": n})

    # 3) oferta sem o aviso de análise de crédito
    if oferta and BLOCO_OFERTA in texto and not re.search(r"an[aá]lise\s+de\s+cr[eé]dito", texto, re.I):
        texto = texto.rstrip() + "\n\n" + AVISO_OFERTA
        acoes.append({"guardrail": "aviso_credito", "acao": "aviso acrescentado"})

    # 4) números que não aparecem nos dados (auditoria)
    base = sorted(set(_numeros([estado.get(k) for k in CHAVES_DADOS]) + _numeros(
        [v for _, v, _ in _valores_texto(estado.get("pergunta") or "")])))
    pequenos = [b for b in base if b >= 1][:300]
    pares = {a + b for a, b in itertools.combinations(pequenos, 2)} | \
            {abs(a - b) for a, b in itertools.combinations(pequenos, 2)} | \
            {a * k for a in pequenos for k in (2, 3, 6, 12)}
    sem_origem = [t for t, v, pct in _valores_texto(texto) if v > 0 and not _confere(v, pct, base, pares)]
    if sem_origem:
        acoes.append({"guardrail": "numero_sem_origem", "acao": "registrado para auditoria", "valores": sem_origem[:5]})
    return texto, acoes
