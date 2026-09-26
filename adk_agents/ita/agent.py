"""Entrada para `adk web adk_agents` (Agent Platform / Antigravity / VS Code).

Para testar no chat do ADK, defina o cliente no estado da sessão:
  no painel "State" do adk web, adicione  {"id_usuario": "<id>"}
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.agents import root_agent  # noqa: E402,F401
