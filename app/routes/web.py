"""Páginas do protótipo e rotas de infraestrutura."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from .. import config

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
router = APIRouter(tags=["infra"])


@router.get("/", include_in_schema=False)
def raiz():
    """Protótipo navegável (app Itaú -> IA.I -> agente) ligado a esta API."""
    return FileResponse(WEB_DIR / "index.html")


@router.get("/whatsapp", include_in_schema=False)
def whatsapp():
    """O ITA dentro de uma conversa de WhatsApp (mock), ligado a esta API."""
    return FileResponse(WEB_DIR / "whatsapp.html")


@router.get("/info")
def info():
    return {"servico": "ita", "modelo": config.MODEL, "dados": config.DATA_SOURCE, "docs": "/docs"}


@router.get("/health")
def health():
    return {"ok": True}
