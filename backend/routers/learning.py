"""
routers/learning.py — Contenu pédagogique du pôle « Apprentissage ».

Le frontend embarque une copie locale (fonctionnement hors ligne) ; ce miroir
serveur permet de consulter / mettre à jour le contenu sans toucher au HTML.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["learning"])

_LEARNING_PATH = Path(__file__).resolve().parent.parent / "data" / "learning.json"
_MODULE_ORDER = ("quran_study", "tajwid", "arabic", "memorize", "hadith")


def _load_json() -> dict:
    if _LEARNING_PATH.exists():
        try:
            return json.loads(_LEARNING_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            import logging

            logging.getLogger("uvicorn.error").warning("learning.json: %r", exc)
    return {"modules": {}}


def _normalize(mod: list) -> list:
    out = []
    for item in mod or []:
        t = item.get("t") or {}
        b = item.get("b") or {}
        out.append({
            "t": t,
            "b": b,
            "languages": sorted({*t, *b}),
        })
    return out


@router.get("/learning")
def api_learning() -> dict:
    data = _load_json().get("modules") or {}
    modules = []
    for mid in _MODULE_ORDER:
        modules.append({"id": mid, "lessons": _normalize(data.get(mid) or [])})
    return {"modules": modules}