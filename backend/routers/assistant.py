"""
routers/assistant.py — Endpoint de l'assistant « Daily Muslim ».
Reçoit la question de l'utilisateur (avec historique et le contexte local
prochaine prière / position Coran) et répond via la chaîne multi-fournisseurs
de translator.py. En mode dégradé (aucune clé API) renvoie 503 : l'application
affiche alors ses réponses locales hors-ligne.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi import Request
from pydantic import BaseModel, Field

import translator
from ratelimit import SlidingWindowRateLimiter, client_ip

router = APIRouter(prefix="/api", tags=["assistant"])

# Fenêtre glissante par IP : chaque réponse appelle la chaîne IA (coûteuse).
_LIMIT_WINDOW = 60.0
_LIMIT_MAX = 15
assistant_limiter = SlidingWindowRateLimiter(_LIMIT_WINDOW, _LIMIT_MAX)


class ChatTurn(BaseModel):
    role: str = Field(...)
    content: str = Field(...)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    history: list[ChatTurn] = Field(default_factory=list)
    prayer: dict | None = None
    quranPos: dict | None = None
    locale: str = "fr"


class ChatReply(BaseModel):
    reply: str
    provider: str | None = None
    offline: bool = False
    disclaimer: str = ""


@router.post("/assistant", response_model=ChatReply)
async def assistant_chat(req: ChatRequest, request: Request) -> ChatReply:
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(400, "Message vide")

    if not assistant_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many requests, try again in a minute")

    if not translator.has_api_key():
        raise HTTPException(503, "no_api_key")

    history = [h.model_dump() for h in req.history]
    try:
        result = await translator.chat_assistant(message, history)
    except Exception as exc:  # défensif : ne jamais casser l'API
        import logging
        logging.getLogger("uvicorn.error").warning("assistant error: %r", exc)
        result = None

    if not result:
        raise HTTPException(503, "providers_failed")

    return ChatReply(
        reply=result["reply"],
        provider=result.get("provider"),
        offline=False,
        disclaimer=translator.ASSISTANT_DISCLAIMER,
    )