"""Guardião de entrada: filtra a mensagem ANTES de ela chegar aos agentes.

Determinístico (regex + listas), sem chamada ao LLM: custo zero e latência ~0.
Bloqueia 4 casos e devolve uma resposta pronta e educada:
  - prompt_injection: tentativas de mudar as regras do agente
  - dados_sensiveis:  CPF, número de cartão, senha ou código de segurança
  - ilicito:          pedidos para fraudar, sonegar ou lavar dinheiro
  - fora_do_escopo:   pedidos claramente sem relação com finanças pessoais
O resto segue para o time de agentes; a conformidade da RESPOSTA fica com o Guardião de saída.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Veredito:
    permitido: bool
    motivo: str | None = None
    resposta: str | None = None


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


# Padrões estreitos de propósito: melhor deixar passar (o Guardião de saída revisa)
# do que barrar pergunta legítima como "sofri uma fraude no cartão" ou "o que é CVV?".
_INJECTION = re.compile(
    r"ignor\w* (todas )?(as )?(suas|tuas) (instrucoes|regras)"
    r"|ignor\w* todas as (instrucoes|regras)"
    r"|ignor\w* (as )?(instrucoes|regras) (anteriores|acima|do sistema)"
    r"|ignore (all |the )?(previous|above|prior) (instructions|rules)"
    r"|esquec\w* (todas )?(as |suas )(instrucoes|regras)"
    r"|(system|sistema) prompt|prompt (do|de) sistema"
    r"|(revel|mostr|repit)\w* (o |a )?(seu|teu|sua|tua) (prompt|instrucoes)"
    r"|(revel|mostr|repit)\w* (o prompt|suas instrucoes|tuas instrucoes)"
    r"|\bvoce agora e\b|a partir de agora voce e\b|finja (que voce|ser)"
    r"|\bmodo (desenvolvedor|dev|deus|sem restricoes)\b|jailbreak"
)

_ILICITO = re.compile(
    r"lava\w* (de )?dinheiro|\bsonegar\b|como sonego|burlar (o |a )?(imposto|receita|fisco|banco)"
    r"|\bfraudar\b|(fazer|aplicar|cometer) (uma )?fraude|clonar (um )?(cartao|conta)"
    r"|conta laranja|esconder (dinheiro|renda) (da|do) (receita|leao|fisco)"
)

_FORA_DO_ESCOPO = re.compile(
    r"\b(poema|poesia|piada|letra de musica|horoscopo)\b"
    r"|\breceita (culinaria|de (bolo|comida|pao|doce|torta|lasanha))"
    r"|\b(escrev|faz|faca|crie|gere)\w* (um |uma )?(codigo|programa|script|redacao|historia)\b"
    r"|\b(quem ganhou|resultado do jogo|previsao do tempo)\b"
)

_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\bcpf\D{0,15}\d{11}\b")
_CARTAO = re.compile(r"\b(?:\d{4}[ .-]?){3}\d{4}\b")
_SEGREDO = re.compile(
    r"\b(minha senha|a senha|meu cvv|o cvv|codigo de seguranca|meu token) (e|eh)\b"
    r"|\b(senha|cvv|token)\s*[:=]\s*\S"
)

RESPOSTAS = {
    "prompt_injection": (
        "Não consigo mudar a forma como eu funciono. Posso te ajudar com o seu dinheiro: "
        "quer saber como vão ficar suas contas nos próximos meses ou simular uma compra?"
    ),
    "dados_sensiveis": (
        "Por segurança, não compartilhe CPF, número de cartão, senha ou códigos aqui. "
        "Eu não preciso deles para te ajudar. Pode me contar o que você quer decidir?"
    ),
    "ilicito": (
        "Não posso ajudar com isso. Se você está com dificuldade para pagar as contas ou "
        "impostos, posso te mostrar caminhos legais para organizar o orçamento. Quer ver?"
    ),
    "fora_do_escopo": (
        "Sou o ITA, especialista no seu dinheiro. Posso te mostrar como seu saldo vai "
        "ficar, simular uma compra ou parcelamento, ou te avisar de um aperto. Por onde começamos?"
    ),
}


def avaliar(mensagem: str) -> Veredito:
    t = _normalizar(mensagem)
    if not t:
        return Veredito(False, "vazia", "Pode me contar o que você quer saber sobre o seu dinheiro?")
    for motivo, achou in (
        ("prompt_injection", _INJECTION.search(t)),
        ("dados_sensiveis", _CPF.search(t) or _CARTAO.search(t) or _SEGREDO.search(t)),
        ("ilicito", _ILICITO.search(t)),
        ("fora_do_escopo", _FORA_DO_ESCOPO.search(t)),
    ):
        if achou:
            return Veredito(False, motivo, RESPOSTAS[motivo])
    return Veredito(True)
