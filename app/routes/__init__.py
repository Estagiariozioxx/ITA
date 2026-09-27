"""Rotas HTTP: só o contrato da API (caminhos, parâmetros e validação); a lógica fica nos controllers."""
from . import chat, clientes, demo, graficos, produtos, web

ROUTERS = [web.router, clientes.router, produtos.router, chat.router, graficos.router, demo.router]
