"""
hadith_index.py — Normalisation et recherche de hadith.

Fournit `normalize()` (comme quran_index) et la recherche dans
backend/data/hadith_index.json (texte normalise, hors-ligne).
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

_INDEX_PATH = Path(__file__).resolve().parent / "data" / "hadith_index.json"

_DIAC = re.compile(
    "[ؐ-ًؚ-ٰٟۖ-ۜ۟-ۨ"
    "۪-ۭ࣓-ࣿـ]"
)
_NOT_LETTER = re.compile("[^ء-ي]")

_refs: list[dict] = []
_norm: list[str] = []
_loaded = False


def normalize(s: str) -> str:
    """Retire harakat / tatwil, unifie alif / ya / ta-marbuta, garde les lettres seules."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = _DIAC.sub("", s)
    s = (
        s.replace("آ", "ا")
        .replace("أ", "ا")
        .replace("إ", "ا")
        .replace("ٱ", "ا")
        .replace("ى", "ي")
        .replace("ئ", "ي")
        .replace("ة", "ه")
        .replace("ؤ", "و")
    )
    return _NOT_LETTER.sub("", s)


def _load() -> bool:
    global _loaded, _refs, _norm
    if _loaded:
        return bool(_refs)
    _loaded = True
    try:
        data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        _refs = data.get("hadiths", [])
        _norm = [normalize(h.get("text", "")) for h in _refs]
    except (OSError, ValueError) as exc:
        import logging
        logging.getLogger("dailymuslim.hadith_index").warning("hadith index: %r", exc)
        _refs, _norm = [], []
    return bool(_refs)


def available() -> bool:
    return _load()


def search(q: str, limit: int = 30) -> list[dict]:
    """Recherche un terme dans les hadiths normalises. Retourne une liste de results."""
    if not _load():
        return []
    nq = normalize(q)
    if not nq:
        return []
    out = []
    for i, ver in enumerate(_norm):
        if nq in ver:
            h = dict(_refs[i])
            h["score"] = len(nq) / max(1, len(ver))
            out.append(h)
            if len(out) >= limit:
                break
    out.sort(key=lambda x: -x["score"])
    return out