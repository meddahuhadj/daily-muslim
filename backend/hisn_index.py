"""
hisn_index.py — Chargement et recherche dans le corpus complet Hisn al-Muslim
(« La Citadelle du musulman », Sheikh Sa'id Al-Qahtani), 132 chapitres /
267 invocations. Donnees hors-ligne : backend/data/adhkar_hisn_muslim.json
(voir scripts/build_adhkar_hisn_muslim.py).

Distinct du petit jeu data/adhkar.json (compteur rapide fr/en/nl/ar, 8
categories) servi par routers/adhkar.py : ce module couvre l'integralite
du livre, en arabe + anglais.
"""

from __future__ import annotations

import json
from pathlib import Path

from quran_index import normalize

_PATH = Path(__file__).resolve().parent / "data" / "adhkar_hisn_muslim.json"

_categories: list[dict] = []
_duas: list[dict] = []
_norm: list[str] = []
_loaded = False


def _load() -> bool:
    global _loaded, _categories, _duas, _norm
    if _loaded:
        return bool(_duas)
    _loaded = True
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        _categories = data.get("categories", [])
        _duas = data.get("duas", [])
        _norm = [normalize(d.get("ar", "")) for d in _duas]
    except (OSError, ValueError) as exc:
        import logging
        logging.getLogger("dailymuslim.hisn_index").warning("hisn index: %r", exc)
        _categories, _duas, _norm = [], [], []
    return bool(_duas)


def available() -> bool:
    return _load()


def categories() -> list[dict]:
    _load()
    return _categories


def by_book(book: int) -> list[dict]:
    _load()
    return [d for d in _duas if d.get("book") == book]


def random_dua() -> dict | None:
    import random
    _load()
    return dict(random.choice(_duas)) if _duas else None


def search(q: str, limit: int = 30) -> list[dict]:
    """Recherche un terme dans le texte arabe normalise des invocations."""
    if not _load():
        return []
    nq = normalize(q)
    if not nq:
        return []
    out = []
    for i, ver in enumerate(_norm):
        if nq in ver:
            d = dict(_duas[i])
            d["score"] = len(nq) / max(1, len(ver))
            out.append(d)
            if len(out) >= limit:
                break
    out.sort(key=lambda x: -x["score"])
    return out
