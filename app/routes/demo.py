"""Apoio à demonstração e job de alertas."""
from fastapi import APIRouter, Query

from ..controllers import demo

router = APIRouter(tags=["demo"])


@router.get("/demo/candidatos")
def candidatos(limite: int = Query(50, ge=1, le=500)):
    """Bons clientes para a demo (têm parcelas, contas fixas e já ficaram no negativo)."""
    return demo.candidatos(limite)


@router.get("/demo/gatilhos")
def gatilhos(limite: int = Query(60, ge=1, le=300)):
    """Para cada tipo de gatilho, os clientes em que ele acontece de verdade (1 query; cache de 10 min)."""
    return demo.gatilhos_por_tipo(limite)


@router.post("/jobs/alertas")
def job_alertas(limite: int = Query(50, ge=1, le=1000)):
    """Chamado pelo Cloud Scheduler: varre clientes e devolve quem deve receber aviso."""
    return demo.job_alertas(limite)
