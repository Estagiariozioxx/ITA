"""Caso de uso do /chat: uma mensagem do cliente (texto, áudio ou foto) até a resposta do ITA.

    mídia (transcrição do áudio, guard de imagem) -> guard de entrada (texto) -> agentes (ADK)
    -> gráfico escolhido pelo agente -> resposta com a trilha para o painel "por dentro"

Os agentes recebem sempre texto: o áudio vira transcrição e a foto vira uma nota do que foi lido.
"""
from __future__ import annotations

import logging
import time

from fastapi import HTTPException

from ..agents import runner
from ..schemas import ChatIn
from ..services import engine, gatilhos, graficos, guard_entrada, midia
from .comum import extrato_preparado, garantir_cliente

log = logging.getLogger("ita")

# saídas dos agentes e das tools que vão para o front (gráficos, botões e painel "por dentro")
TELA = {"contexto_cliente", "leitura_da_pergunta", "proposta", "simulacao", "projecao", "ate_salario",
        "gastos_categorias", "dinheiro_extra", "lancamentos", "oferta", "clarificacao"}
RESPOSTA_PADRAO = "Pode me contar um pouco mais sobre o que você precisa?"
ERROS_GEMINI = {429: "cota do Gemini esgotada (limite de chamadas por minuto da chave)",
                503: "Gemini com alta demanda no momento, tente de novo em instantes"}


class _Bloqueio(Exception):
    """A mensagem parou antes dos agentes; `resposta` é o corpo pronto do /chat."""

    def __init__(self, resposta: dict):
        super().__init__(resposta.get("rota"))
        self.resposta = resposta


def _bloqueado(body: ChatIn, resposta: str, rota: str, trilha: list[dict]) -> dict:
    return {"session_id": body.session_id, "resposta": resposta, "bloqueado": True, "rota": rota,
            "dados_tela": {}, "imagens": [], "trilha": trilha}


# --------------------------------------------------------------------------- #
# etapas
# --------------------------------------------------------------------------- #
def _ler_midia(body: ChatIn) -> tuple[str, dict | None, list[dict]]:
    """(mensagem em texto, leitura da foto, trilha). Áudio vira texto; foto passa pelo guard de imagem."""
    trilha: list[dict] = []
    mensagem, imagem = body.mensagem.strip(), None
    try:
        if body.audio:
            dados, mime = midia.decodificar(body.audio, midia.MIMES_AUDIO, "o áudio", "audio/ogg")
            transcrito = midia.transcrever(dados, mime)
            mensagem = f"{mensagem} {transcrito}".strip() if mensagem else transcrito
            trilha.append({"agente": "transcricao", "acao": "audio", "trecho": transcrito[:240]})
        if body.imagem:
            dados, mime = midia.decodificar(body.imagem, midia.MIMES_IMAGEM, "a foto", "image/jpeg")
            leitura = midia.ler_imagem(dados, mime)
            trilha.append({"agente": "guard_imagem", "acao": "aprovada" if leitura["aceita"] else "bloqueio",
                           "motivo": leitura.get("motivo") or leitura.get("tipo")})
            if not leitura["aceita"]:
                log.info("guard_imagem bloqueou (%s) para %s", leitura["motivo"], body.id_usuario)
                raise _Bloqueio(_bloqueado(body, leitura["resposta"], "guard_imagem", trilha))
            imagem = leitura
            mensagem = f"{mensagem}\n{midia.nota(leitura)}".strip()
    except midia.MidiaInvalida as e:
        log.info("midia recusada (%s) para %s", e.motivo, body.id_usuario)
        raise _Bloqueio(_bloqueado(body, e.resposta, "midia",
                                   trilha + [{"agente": "midia", "acao": "recusa", "motivo": e.motivo}])) from None
    return mensagem, imagem, trilha


def _checar_entrada(body: ChatIn, mensagem: str, trilha: list[dict]) -> None:
    veredito = guard_entrada.avaliar(mensagem)
    if not veredito.permitido:
        log.info("guard_entrada bloqueou (%s) para %s", veredito.motivo, body.id_usuario)
        raise _Bloqueio(_bloqueado(body, veredito.resposta, "guard_entrada", trilha + [
            {"agente": "guard_entrada", "acao": "bloqueio", "motivo": veredito.motivo}]))
    trilha.append({"agente": "guard_entrada", "acao": "aprovado"})


def _gatilho(uid: str, tipo: str) -> dict:
    """O aviso proativo que abriu a conversa, com os números, para o agente PROATIVIDADE continuar dele."""
    d = extrato_preparado(uid)
    g = next((x for x in gatilhos.detectar(d, engine.perfil(d)) if x["tipo"] == tipo), None)
    if not g or not g.get("ativo"):
        return {"tipo": tipo}
    return {k: g[k] for k in ("tipo", "titulo", "mensagem", "dados") if k in g}


def _estado_inicial(body: ChatIn, mensagem: str, imagem: dict | None, trilha: list[dict]) -> dict:
    """O que muda no estado a cada turno: resposta, oferta, regras e gráfico são recalculados;
    proposta e simulação ficam para o "quero a B"."""
    from ..agents.tools import hoje_extenso  # tardio: carrega o ADK só quando há conversa

    estado = {"pergunta": mensagem, "resposta": "", "rota_atual": None, "rota_forcada": body.rota,
              "oferta": None, "regras_produto": None, "guardrails": None, "clarificacao": None,
              "grafico_escolhido": None, "imagem": imagem, "data_hoje": hoje_extenso()}
    if body.gatilho:
        estado.update(gatilho=_gatilho(body.id_usuario, body.gatilho), rota_forcada="proatividade")
        trilha.append({"agente": "gatilho", "acao": "rota direta", "motivo": body.gatilho})
    elif body.rota:
        trilha.append({"agente": "clarificacao", "acao": "botão escolhido", "motivo": body.rota})
    return estado


def _registrar_evento(ev, tela: dict, trilha: list[dict]) -> None:
    """Guarda as saídas das tools para o front e anota na trilha tools, textos, regras e guardrails."""
    delta = ev.actions.state_delta if ev.actions else {}
    tela.update({k: v for k, v in delta.items() if k in TELA and v is not None})
    if delta.get("regras_produto"):
        r = delta["regras_produto"]
        trilha.append({"agente": "regras_produto", "acao": "oferta" if r.get("oferta") else "regras",
                       "regras": r.get("regras_aplicadas"), "produto": (r.get("oferta") or {}).get("nome")})
    for g in delta.get("guardrails") or []:
        trilha.append({"agente": "guardrails_saida", "acao": g["guardrail"], "motivo": g["acao"]})
    for p in (ev.content.parts if ev.content and ev.content.parts else []):
        if p.function_call:
            trilha.append({"agente": ev.author, "acao": "ferramenta", "ferramenta": p.function_call.name,
                           "argumentos": dict(p.function_call.args or {})})
        elif p.text and not getattr(p, "thought", False):
            trilha.append({"agente": ev.author, "acao": "texto", "trecho": p.text[:240]})


async def _rodar_agentes(body: ChatIn, session_id: str, mensagem: str, estado: dict, trilha: list[dict]) -> dict:
    """Roda o turno no ADK e devolve os dados de tela; erro do Gemini vira 503/502 com o motivo."""
    from google.genai import errors as genai_errors
    from google.genai import types

    executor, _ = runner.obter()
    tela: dict = {}
    msg = types.Content(role="user", parts=[types.Part(text=mensagem)])
    try:
        async for ev in executor.run_async(user_id=body.id_usuario, session_id=session_id,
                                           new_message=msg, state_delta=estado):
            _registrar_evento(ev, tela, trilha)
    except genai_errors.APIError as e:
        log.warning("Gemini falhou (%s): %s", e.code, e.message)
        raise HTTPException(503 if e.code in (429, 503) else 502,
                            f"{ERROS_GEMINI.get(e.code, 'erro ao chamar o Gemini')} [{e.code}]") from None
    return tela


# --------------------------------------------------------------------------- #
# caso de uso
# --------------------------------------------------------------------------- #
async def conversar(body: ChatIn) -> dict:
    garantir_cliente(body.id_usuario)
    try:
        mensagem, imagem, trilha = _ler_midia(body)
        _checar_entrada(body, mensagem, trilha)
    except _Bloqueio as b:
        return b.resposta

    sessao = await runner.sessao(body.id_usuario, body.session_id)
    t0 = time.perf_counter()
    estado = _estado_inicial(body, mensagem, imagem, trilha)
    tela = await _rodar_agentes(body, sessao.id, mensagem, estado, trilha)

    st = await runner.estado(body.id_usuario, sessao.id)
    resposta = st.get("resposta") or RESPOSTA_PADRAO
    rota = st.get("rota_atual") or "saudacao"
    if imagem:
        tela["imagem"] = imagem  # o que o ITA leu na foto, para o painel "por dentro"
    escolha = st.get("grafico_escolhido")
    imagens = graficos.escolhido(tela, escolha, resposta)
    trilha.append({"agente": "graficos", "acao": "grafico" if imagens else "sem_grafico",
                   "motivo": (escolha or {}).get("tipo") or "o agente não pediu gráfico"})
    log.info("chat %s: %.1fs, rota %s, %d passos, resposta com %d caracteres",
             body.id_usuario, time.perf_counter() - t0, rota, len(trilha), len(resposta))
    return {
        "session_id": sessao.id,
        "resposta": resposta,
        # o que os agentes receberam (com a transcrição e a nota da foto): o front reusa este texto no
        # botão da clarificação, que não reenvia o áudio nem a foto
        "pergunta": mensagem,
        "bloqueado": False,
        "rota": rota,
        "dados_tela": tela,
        "imagens": imagens,  # o gráfico escolhido pelo agente, se houver
        "trilha": trilha,
    }
