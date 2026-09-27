"""API do ITA (FastAPI) — roda no Cloud Run.

Endpoints determinísticos (rápidos, sem LLM) alimentam telas e gráficos;
/chat passa pelo guard de entrada e roda o time de agentes: o orquestrador responde saudações,
pede clarificação ou encaminha para um especialista por cenário (previsibilidade, proatividade,
produtos); os guardrails de saída conferem a resposta em código antes de ela sair.
"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import config, contratacao, engine, gatilhos, graficos, guard_entrada
from .data import ClienteNaoEncontrado, get_repo

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

log = logging.getLogger("ita")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="ITA API",
    version="1.0.0",
    description="Agente de decisão financeira — Batalha de Agentes Itaú",
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _df(uid: str):
    try:
        return engine.preparar(get_repo().extrato(uid))
    except ClienteNaoEncontrado:
        raise HTTPException(404, f"cliente {uid} não encontrado")


class SimulacaoIn(BaseModel):
    valor: float = Field(..., gt=0, examples=[3000])
    parcelas: int = Field(1, ge=1, le=48, examples=[12])
    entrada: float = Field(0, ge=0)
    meses_espera: int = Field(0, ge=0, le=12)
    taxa_juros_mensal: float = Field(0, ge=0, le=0.2, description="0.02 = 2% ao mês")


class ComparacaoIn(BaseModel):
    valor: float = Field(..., gt=0, examples=[3000])
    parcelas: int = Field(12, ge=1, le=48)
    taxa_juros_mensal: float = Field(0, ge=0, le=0.2)


class ChatIn(BaseModel):
    id_usuario: str
    mensagem: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None
    rota: Literal["previsibilidade", "produtos"] | None = Field(
        None, description="opção escolhida num botão de clarificação: vai direto ao especialista")
    gatilho: str | None = Field(
        None, max_length=40, description="tipo do gatilho proativo que abriu a conversa (ex.: fim_parcela)")


# --------------------------------------------------------------------------- #
# infraestrutura
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
def raiz():
    """Protótipo navegável (app Itaú -> IA.I -> agente) ligado a esta API."""
    return FileResponse(WEB_DIR / "index.html")


@app.get("/whatsapp", include_in_schema=False)
def whatsapp():
    """O ITA dentro de uma conversa de WhatsApp (mock), ligado a esta API."""
    return FileResponse(WEB_DIR / "whatsapp.html")


@app.get("/info")
def info():
    return {"servico": "ita", "modelo": config.MODEL, "dados": config.DATA_SOURCE,
            "docs": "/docs"}


@app.get("/health")
def health():
    return {"ok": True}


# --------------------------------------------------------------------------- #
# dados determinísticos (telas, gráficos)
# --------------------------------------------------------------------------- #
@app.get("/clientes")
def listar_clientes(limite: int = Query(20, ge=1, le=1000)):
    return {"clientes": get_repo().usuarios(limite)}


@app.get("/clientes/{uid}/perfil")
def perfil(uid: str):
    return engine.perfil(_df(uid))


@app.get("/clientes/{uid}/projecao")
def projecao(uid: str, dias: int = Query(90, ge=7, le=365)):
    return engine.projetar(_df(uid), dias)


@app.post("/clientes/{uid}/simular")
def simular(uid: str, body: SimulacaoIn):
    compra = {"valor": body.valor, "parcelas": body.parcelas, "entrada": body.entrada,
              "meses_espera": body.meses_espera, "taxa_mensal": body.taxa_juros_mensal}
    horizonte = max(90, 31 * (body.meses_espera + 3))
    d = _df(uid)
    return {"compra": compra,
            "sem_compra": engine.resumo_projecao(engine.projetar(d, horizonte)),
            "com_compra": engine.projetar(d, horizonte, compra=compra)}


@app.post("/clientes/{uid}/comparar")
def comparar(uid: str, body: ComparacaoIn):
    return engine.comparar_opcoes(_df(uid), body.valor, body.parcelas, body.taxa_juros_mensal)


@app.get("/clientes/{uid}/alertas")
def alertas(uid: str):
    return {"id_usuario": uid, "alertas": engine.alertas(_df(uid))}


@app.get("/clientes/{uid}/ate-salario")
def ate_salario(uid: str, gasto: float = Query(0, ge=0, le=1_000_000)):
    """"Até o próximo salário dá?" — saldo até a véspera da renda, com e sem um gasto à vista hoje."""
    return engine.ate_proximo_salario(_df(uid), gasto)


@app.post("/jobs/alertas")
def job_alertas(limite: int = Query(50, ge=1, le=1000)):
    """Chamado pelo Cloud Scheduler: varre clientes e devolve quem deve receber aviso."""
    repo, saida = get_repo(), []
    for uid in repo.usuarios(limite):
        try:
            al = engine.alertas(engine.preparar(repo.extrato(uid)))
        except Exception as e:  # um cliente com dado ruim não derruba o job
            log.warning("falha em %s: %s", uid, e)
            continue
        if al:
            saida.append({"id_usuario": uid,
                          "alertas": [{k: v for k, v in a.items() if k != "dados"} for a in al]})
    return {"clientes_avaliados": limite, "com_alerta": len(saida), "resultado": saida}


@app.get("/demo/candidatos")
def candidatos(limite: int = Query(50, ge=1, le=500)):
    """Procura bons clientes para a demo (têm parcelas, contas fixas e já ficaram no negativo)."""
    repo, out = get_repo(), []
    for uid in repo.usuarios(limite):
        try:
            out.append({"id_usuario": uid, **engine.pontuar_para_demo(engine.preparar(repo.extrato(uid)))})
        except Exception as e:
            log.warning("falha em %s: %s", uid, e)
    out.sort(key=lambda x: (not x["bom_para_demo"], -x["parcelas_abertas"]))
    return {"candidatos": out}


# --------------------------------------------------------------------------- #
# proatividade (Cenário 2): gatilhos detectados no extrato
# --------------------------------------------------------------------------- #
@app.get("/clientes/{uid}/gatilhos")
def gatilhos_cliente(uid: str, nome: str = Query("tudo bem", max_length=40)):
    """Gatilhos proativos do cliente (ativos e inativos, com o motivo) e a mensagem de abertura do ITA."""
    d = _df(uid)
    pf = engine.perfil(d)
    return {"id_usuario": uid, "data_referencia": pf["data_referencia"], "saldo_atual": pf["saldo_atual"],
            "gatilhos": gatilhos.detectar(d, pf, nome)}


@app.get("/clientes/{uid}/movimentacoes")
def movimentacoes(uid: str, limite: int = Query(8, ge=1, le=50)):
    """Últimos lançamentos do extrato (para a tela do app)."""
    return {"id_usuario": uid, "movimentacoes": gatilhos.movimentacoes(_df(uid), limite)}


class ProdutoIn(BaseModel):
    produto: Literal["financiamento", "consorcio", "credito"]
    valor: float = Field(..., gt=0, le=5_000_000)
    prazo_meses: int = Field(..., ge=1, le=120)
    entrada: float = Field(0, ge=0)
    taxa: float | None = Field(None, ge=0, description="taxa do cenário que gerou a oferta (0.02 = 2%)")


@app.post("/clientes/{uid}/produtos/simular")
def simular_produto(uid: str, body: ProdutoIn):
    """Simulação do produto dentro da conversa: parcela, custo total, capacidade de pagamento e saldo em 90 dias."""
    return contratacao.simular(_df(uid), body.produto, body.valor, body.prazo_meses, body.entrada, body.taxa)


@app.post("/clientes/{uid}/produtos/contratar")
def contratar_produto(uid: str, body: ProdutoIn):
    """Contratação de DEMONSTRAÇÃO: refaz a simulação e, se couber, devolve um protocolo de proposta."""
    r = contratacao.contratar(_df(uid), uid, body.produto, body.valor, body.prazo_meses, body.entrada, body.taxa)
    log.info("contratacao %s %s: %s", uid, body.produto, r.get("protocolo") or r.get("motivo"))
    return r


_cache_demo: dict[int, tuple[float, dict]] = {}


@app.get("/demo/gatilhos")
def demo_gatilhos(limite: int = Query(60, ge=1, le=300)):
    """Para cada tipo de gatilho, os clientes em que ele acontece de verdade (1 query no BigQuery; cache 10 min)."""
    hit = _cache_demo.get(limite)
    if hit and time.time() - hit[0] < config.CACHE_TTL:
        return hit[1]
    repo = get_repo()
    por_tipo: dict[str, list[str]] = {t: [] for t in gatilhos.TIPOS}
    for uid, df in repo.extratos(repo.usuarios(limite)).items():
        try:
            d = engine.preparar(df)
            for g in gatilhos.detectar(d, engine.perfil(d)):
                if g["ativo"]:
                    por_tipo[g["tipo"]].append(uid)
        except Exception as e:  # um cliente com dado ruim não derruba a busca
            log.warning("gatilhos: falha em %s: %s", uid, e)
    out = {"clientes_avaliados": limite, "por_tipo": por_tipo}
    _cache_demo[limite] = (time.time(), out)
    return out


# --------------------------------------------------------------------------- #
# agentes
# --------------------------------------------------------------------------- #
_runner = None
_sessions = None
APP_NAME = "ita"
# saídas dos agentes e das tools que vão para o front (gráficos, botões e painel "por dentro")
TELA = {"contexto_cliente", "leitura_da_pergunta", "proposta", "simulacao", "projecao", "ate_salario",
        "gastos_categorias", "dinheiro_extra", "lancamentos", "oferta", "clarificacao"}


def _gatilho(uid: str, tipo: str) -> dict:
    """O aviso proativo que abriu a conversa, com os números, para o agente PROATIVIDADE continuar dele."""
    d = _df(uid)
    g = next((x for x in gatilhos.detectar(d, engine.perfil(d)) if x["tipo"] == tipo), None)
    if not g or not g.get("ativo"):
        return {"tipo": tipo}
    return {k: g[k] for k in ("tipo", "titulo", "mensagem", "dados") if k in g}


def _get_runner():
    global _runner, _sessions
    if _runner is None:
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService

        from .agents import root_agent

        _sessions = InMemorySessionService()
        _runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=_sessions)
    return _runner, _sessions


@app.post("/chat")
async def chat(body: ChatIn):
    from google.genai import types

    try:
        get_repo().extrato(body.id_usuario)  # 404 cedo; o agente raiz carrega o extrato no estado
    except ClienteNaoEncontrado:
        raise HTTPException(404, f"cliente {body.id_usuario} não encontrado")

    veredito = guard_entrada.avaliar(body.mensagem)
    if not veredito.permitido:
        log.info("guard_entrada bloqueou (%s) para %s", veredito.motivo, body.id_usuario)
        return {
            "session_id": body.session_id,
            "resposta": veredito.resposta,
            "bloqueado": True,
            "dados_tela": {},
            "trilha": [{"agente": "guard_entrada", "acao": "bloqueio", "motivo": veredito.motivo}],
        }

    runner, sessions = _get_runner()

    session = None
    if body.session_id:
        session = await sessions.get_session(
            app_name=APP_NAME, user_id=body.id_usuario, session_id=body.session_id)
    if session is None:
        session = await sessions.create_session(
            app_name=APP_NAME, user_id=body.id_usuario,
            session_id=body.session_id or uuid.uuid4().hex,
            state={"id_usuario": body.id_usuario})

    from google.genai import errors as genai_errors

    t0 = time.perf_counter()
    trilha = [{"agente": "guard_entrada", "acao": "aprovado"}]
    tela = {}
    # a cada turno: resposta, oferta e regras recalculadas; proposta/simulação ficam para "quero a B"
    delta_inicial = {"pergunta": body.mensagem, "resposta": "", "rota_atual": None, "rota_forcada": body.rota,
                     "oferta": None, "regras_produto": None, "guardrails": None, "clarificacao": None}
    if body.gatilho:
        delta_inicial.update(gatilho=_gatilho(body.id_usuario, body.gatilho), rota_forcada="proatividade")
        trilha.append({"agente": "gatilho", "acao": "rota direta", "motivo": body.gatilho})
    elif body.rota:
        trilha.append({"agente": "clarificacao", "acao": "botão escolhido", "motivo": body.rota})
    msg = types.Content(role="user", parts=[types.Part(text=body.mensagem)])
    try:
        async for ev in runner.run_async(
            user_id=body.id_usuario, session_id=session.id, new_message=msg, state_delta=delta_inicial,
        ):
            delta = ev.actions.state_delta if ev.actions else {}
            tela.update({k: v for k, v in delta.items() if k in TELA and v is not None})
            if delta.get("regras_produto"):
                r = delta["regras_produto"]
                trilha.append({"agente": "regras_produto", "acao": "oferta" if r.get("oferta") else "regras",
                               "regras": r.get("regras_aplicadas"),
                               "produto": (r.get("oferta") or {}).get("nome")})
            for g in delta.get("guardrails") or []:
                trilha.append({"agente": "guardrails_saida", "acao": g["guardrail"], "motivo": g["acao"]})
            if not (ev.content and ev.content.parts):
                continue
            for p in ev.content.parts:
                if p.function_call:
                    trilha.append({"agente": ev.author, "acao": "ferramenta",
                                   "ferramenta": p.function_call.name,
                                   "argumentos": dict(p.function_call.args or {})})
                elif p.text and not getattr(p, "thought", False):
                    trilha.append({"agente": ev.author, "acao": "texto", "trecho": p.text[:240]})
    except genai_errors.APIError as e:
        log.warning("Gemini falhou (%s): %s", e.code, e.message)
        motivo = {429: "cota do Gemini esgotada (limite de chamadas por minuto da chave)",
                  503: "Gemini com alta demanda no momento, tente de novo em instantes"}
        raise HTTPException(503 if e.code in (429, 503) else 502,
                            f"{motivo.get(e.code, 'erro ao chamar o Gemini')} [{e.code}]")

    s = await sessions.get_session(app_name=APP_NAME, user_id=body.id_usuario, session_id=session.id)
    resposta = s.state.get("resposta") or "Pode me contar um pouco mais sobre o que você precisa?"
    rota = s.state.get("rota_atual") or "saudacao"
    log.info("chat %s: %.1fs, rota %s, %d passos, resposta com %d caracteres",
             body.id_usuario, time.perf_counter() - t0, rota, len(trilha), len(resposta))
    return {
        "session_id": session.id,
        "resposta": resposta,
        "bloqueado": False,
        "rota": rota,
        "dados_tela": tela,
        # gráficos como imagem (PNG), do jeito que o banco mandaria no WhatsApp
        "imagens": graficos.gerar(tela),
        "trilha": trilha,
    }


@app.post("/graficos")
def gerar_graficos(dados: dict):
    """Imagens (PNG) para dados já calculados (mesmas chaves de dados_tela: projecao, ate_salario,
    gastos_categorias, simulacao, dinheiro_extra). Usado pelos atalhos do menu, que não passam pelo /chat."""
    return {"imagens": graficos.gerar(dados)}
