"""Agentes do ITA (Google ADK + Gemini): orquestrador, clarificação e um especialista por cenário.

Os nomes públicos são carregados só quando usados (PEP 562): importar a API não carrega o ADK,
que só entra na primeira mensagem do /chat.
"""
_PUBLICOS = {"root_agent", "orquestrador", "clarificacao", "previsibilidade", "proatividade",
             "produtos_agente", "ESPECIALISTAS"}


def __getattr__(nome: str):
    if nome in _PUBLICOS:
        from . import agentes
        return getattr(agentes, nome)
    raise AttributeError(f"module {__name__!r} has no attribute {nome!r}")
