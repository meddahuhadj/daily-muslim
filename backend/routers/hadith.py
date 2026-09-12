"""
routers/hadith.py — Recherche de hadith.

Exposes:
  GET /api/hadith/search?q=...      -> liste de hadiths contenant le terme
  GET /api/hadith/random            -> un hadith au hasard
  GET /api/hadith/collections       -> liste des collections supportees

Hors-ligne : tout est lu dans backend/data/hadith_index.json
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

import hadith_index

router = APIRouter(prefix="/api", tags=["hadith"])

COLLECTIONS = {
    "bukhari": "Sahih al-Bukhari",
    "muslim": "Sahih Muslim",
    "tirmidhi": "Jami' at-Tirmidhi",
    "abu_dawud": "Sunan Abi Dawud",
    "an_nasa'i": "Sunan an-Nasa'i",
    "ibn_majah": "Sunan Ibn Majah",
    "malik": "al-Muwatta",
    "nasai_sharif": "Sunan an-Nasa'i al-Sharif",
}


@router.get("/hadith/search")
async def search_hadith(
    q: str = Query(..., min_length=1, description="Terme de recherche"),
    limit: int = Query(30, ge=1, le=100),
    collection: str = Query("", description="Filtrer par collection"),
    book: int | None = Query(None, description="Filtrer par numero de livre/chapitre"),
) -> dict[str, Any]:
    """Recherche un terme dans les hadiths (texte arabe normalise)."""
    if not hadith_index.available():
        raise HTTPException(status_code=503, detail="Hadith index not available")

    results = hadith_index.search(q, limit=500 if (collection or book is not None) else 200)
    if collection:
        results = [h for h in results if h.get("collection") == collection]
    if book is not None:
        results = [h for h in results if h.get("book") == book]
    results = results[:limit]

    for h in results:
        h["collection_name"] = COLLECTIONS.get(h.get("collection", ""), h.get("collection", ""))

    return {"query": q, "results": results, "count": len(results)}


@router.get("/hadith/list")
async def list_hadith(
    collection: str = Query("bukhari", description="Collection a parcourir"),
    book: int | None = Query(None, description="Filtrer par numero de livre/chapitre"),
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
) -> dict[str, Any]:
    """Parcourt une collection (ou un livre precis) dans l'ordre, sans recherche
    textuelle — pour un navigateur par chapitre (ex: Sahih al-Bukhari)."""
    if not hadith_index.available():
        raise HTTPException(status_code=503, detail="Hadith index not available")
    page, total = hadith_index.list_by(collection, book=book, offset=offset, limit=limit)
    for h in page:
        h["collection_name"] = COLLECTIONS.get(h.get("collection", ""), h.get("collection", ""))
    return {"collection": collection, "book": book, "offset": offset, "limit": limit,
            "total": total, "results": page}


@router.get("/hadith/books")
async def list_books(
    collection: str = Query("bukhari", description="Collection dont on liste les livres/chapitres"),
) -> dict[str, Any]:
    """Livres/chapitres d'une collection, pour un navigateur par chapitre."""
    if not hadith_index.available():
        raise HTTPException(status_code=503, detail="Hadith index not available")
    return {"collection": collection, "books": hadith_index.books(collection)}


@router.get("/hadith/random")
async def random_hadith(collection: str = Query("")) -> dict[str, Any]:
    """Retourne un hadith au hasard (optionnellement dans une collection donnee)."""
    if not hadith_index.available():
        raise HTTPException(status_code=503, detail="Hadith index not available")

    pool = hadith_index._refs
    if collection:
        pool = [h for h in pool if h.get("collection") == collection]
    if not pool:
        raise HTTPException(status_code=404, detail="No hadith in this collection")

    h = dict(random.choice(pool))
    h["collection_name"] = COLLECTIONS.get(h.get("collection", ""), h.get("collection", ""))
    return h


@router.get("/hadith/collections")
async def list_collections() -> dict[str, Any]:
    """Liste des collections de hadith supportees."""
    return {
        "collections": [
            {"id": cid, "name": name}
            for cid, name in COLLECTIONS.items()
        ]
    }