"""Execução dos agentes: um Runner do ADK e o serviço de sessões, criados na primeira mensagem.

As sessões ficam em memória (InMemorySessionService): somem quando a instância reinicia. Para
persistir, troque por VertexAiSessionService ou DatabaseSessionService aqui.
"""
from __future__ import annotations

import uuid

APP_NAME = "ita"

_runner = None
_sessions = None


def obter():
    """(runner, sessões), criados uma vez por processo."""
    global _runner, _sessions
    if _runner is None:
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService

        from .agentes import root_agent

        _sessions = InMemorySessionService()
        _runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=_sessions)
    return _runner, _sessions


async def sessao(id_usuario: str, session_id: str | None):
    """A sessão da conversa: a existente (se o front mandou o id) ou uma nova."""
    _, sessions = obter()
    s = None
    if session_id:
        s = await sessions.get_session(app_name=APP_NAME, user_id=id_usuario, session_id=session_id)
    if s is None:
        s = await sessions.create_session(app_name=APP_NAME, user_id=id_usuario,
                                          session_id=session_id or uuid.uuid4().hex,
                                          state={"id_usuario": id_usuario})
    return s


async def estado(id_usuario: str, session_id: str) -> dict:
    """O estado da sessão depois do turno (resposta, rota, gráfico escolhido...)."""
    _, sessions = obter()
    s = await sessions.get_session(app_name=APP_NAME, user_id=id_usuario, session_id=session_id)
    return s.state
