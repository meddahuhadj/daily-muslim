"""
routers/hisn_muslim.py — Hisn al-Muslim complet (132 chapitres / 267
invocations), arabe + anglais, hors-ligne (backend/data/adhkar_hisn_muslim.json).

Exposes:
  GET /api/hisn/categories        -> liste des 132 chapitres
  GET /api/hisn/category/{number} -> invocations d'un chapitre
  GET /api/hisn/random            -> une invocation au hasard
  GET /api/hisn/search?q=...      -> recherche dans le texte arabe
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

import hisn_index

router = APIRouter(prefix="/api/hisn", tags=["hisn_muslim"])


@router.get("/categories")
async def list_categories() -> dict[str, Any]:
    if not hisn_index.available():
        raise HTTPException(status_code=503, detail="Hisn al-Muslim index not available")
    return {"categories": hisn_index.categories()}


@router.get("/category/{number}")
async def get_category(number: int) -> dict[str, Any]:
    if not hisn_index.available():
        raise HTTPException(status_code=503, detail="Hisn al-Muslim index not available")
    duas = hisn_index.by_book(number)
    if not duas:
        raise HTTPException(status_code=404, detail="Chapitre introuvable")
    return {"book": number, "duas": duas}


@router.get("/random")
async def random_dua() -> dict[str, Any]:
    if not hisn_index.available():
        raise HTTPException(status_code=503, detail="Hisn al-Muslim index not available")
    d = hisn_index.random_dua()
    if not d:
        raise HTTPException(status_code=404, detail="Aucune invocation disponible")
    return d


@router.get("/search")
async def search_dua(
    q: str = Query(..., min_length=1, description="Terme de recherche (arabe)"),
    limit: int = Query(30, ge=1, le=100),
) -> dict[str, Any]:
    if not hisn_index.available():
        raise HTTPException(status_code=503, detail="Hisn al-Muslim index not available")
    results = hisn_index.search(q, limit=limit)
    return {"query": q, "results": results, "count": len(results)}
