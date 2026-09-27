"""Conversa com o ITA (agentes)."""
from fastapi import APIRouter

from ..controllers import chat
from ..schemas import ChatIn

router = APIRouter(tags=["chat"])


@router.post("/chat")
async def conversar(body: ChatIn):
    """Texto, áudio ou foto -> guards -> agentes -> resposta, gráfico escolhido e trilha."""
    return await chat.conversar(body)
