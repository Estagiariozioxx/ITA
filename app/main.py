"""API do ITA (FastAPI), no Cloud Run.

Camadas:
    routes/        contrato HTTP (caminhos, parâmetros, validação)
    controllers/   casos de uso (juntam repositório, services e agentes; erro -> HTTP)
    services/      regras de negócio sem HTTP e sem LLM (motor, simulação, produtos, gatilhos, gráficos...)
    agents/        agentes ADK + Gemini, suas tools e o runner
    repositories/  extrato do cliente (BigQuery ou CSV)
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import ROUTERS

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="ITA API", version="1.0.0", description="Agente de decisão financeira — Batalha de Agentes Itaú")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for router in ROUTERS:
    app.include_router(router)
