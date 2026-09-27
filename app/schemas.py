"""Modelos de entrada da API (validação do corpo das requisições)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


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


class ProdutoIn(BaseModel):
    produto: Literal["financiamento", "consorcio", "credito"]
    valor: float = Field(..., gt=0, le=5_000_000)
    prazo_meses: int = Field(..., ge=1, le=120)
    entrada: float = Field(0, ge=0)
    taxa: float | None = Field(None, ge=0, description="taxa do cenário que gerou a oferta (0.02 = 2%)")


class ChatIn(BaseModel):
    id_usuario: str
    mensagem: str = Field("", max_length=2000)
    session_id: str | None = None
    rota: Literal["previsibilidade", "produtos"] | None = Field(
        None, description="opção escolhida num botão de clarificação: vai direto ao especialista")
    gatilho: str | None = Field(
        None, max_length=40, description="tipo do gatilho proativo que abriu a conversa (ex.: fim_parcela)")
    audio: str | None = Field(
        None, description="áudio do cliente em base64 ou data URI; o ITA transcreve e segue o fluxo de texto")
    imagem: str | None = Field(
        None, description="foto em base64 ou data URI (etiqueta de preço, boleto, proposta); passa pelo "
                          "guard de imagem antes dos agentes")

    @model_validator(mode="after")
    def _tem_conteudo(self):
        if not (self.mensagem.strip() or self.audio or self.imagem):
            raise ValueError("mande uma mensagem, um áudio ou uma imagem")
        return self
