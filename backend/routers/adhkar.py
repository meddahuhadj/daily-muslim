"""
routers/adhkar.py — Collections d'adhkar (JSON) servies à l'application.
Le contenu principal reste embarqué côté frontal (accessible hors-ligne) ;
l'endpoint sert de source de vérité et permet des mises à jour sans relivraison.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["adhkar"])

_DATA: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _DATA
    if _DATA is None:
        path = Path(__file__).resolve().parent.parent / "data" / "adhkar.json"
        import json
        try:
            _DATA = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            _DATA = {"categories": {}}
    return _DATA


@router.get("/adhkar")
async def get_adhkar():
    return _load()


@router.get("/adhkar/{category}")
async def get_adhkar_category(category: str):
    data = _load()
    cat = data.get("categories", {}).get(category)
    if cat is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Catégorie introuvable")
    return {"category": category, "items": cat}