"""
quran_index.py — Repli de detection de reference coranique.

Quand Gemini renvoie `is_quran = true` mais `quran_ref = null`, on cherche le
segment arabe dans un index local du texte coranique (data/quran_index.json,
texte sans diacritiques, ~715 Kio) et on renvoie "sourate:verset" si on le
retrouve. 100 % hors-ligne, aucun appel reseau a l'execution.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

logger = logging.getLogger("dailymuslim.quran_index")

_INDEX_PATH = Path(__file__).resolve().parent / "data" / "quran_index.json"

# Harakat, petites lettres sur/sous, signes coraniques, tatwil (kashida).
_DIAC = re.compile(
    "[ؐ-ًؚ-ٰٟۖ-ۜ۟-ۨ"
    "۪-ۭ࣓-ࣿـ]"
)
# Ne garder que les lettres arabes de base U+0621..U+064A.
_NOT_LETTER = re.compile("[^ء-ي]")

_refs: list[str] = []
_norm: list[str] = []
_loaded = False


def normalize(s: str) -> str:
    """Retire harakat / tatwil, unifie alif / ya / ta-marbuta, garde les lettres seules."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = _DIAC.sub("", s)
    s = (
        s.replace("آ", "ا")  # alif madda   -> alif
        .replace("أ", "ا")   # alif hamza a. -> alif
        .replace("إ", "ا")   # alif hamza b. -> alif
        .replace("ٱ", "ا")   # alif wasla    -> alif
        .replace("ى", "ي")   # alif maqsura  -> ya
        .replace("ئ", "ي")   # ya hamza      -> ya
        .replace("ة", "ه")   # ta marbuta    -> ha
        .replace("ؤ", "و")   # waw hamza     -> waw
    )
    return _NOT_LETTER.sub("", s)


def _load() -> bool:
    global _loaded, _refs, _norm
    if _loaded:
        return bool(_refs)
    _loaded = True
    try:
        data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        _refs = data["refs"]
        _norm = data["norm"]
        if len(_refs) != len(_norm) or not _refs:
            _refs, _norm = [], []
    except (OSError, ValueError, KeyError) as exc:
        logger.warning("index coranique indisponible: %r", exc)
        _refs, _norm = [], []
    return bool(_refs)


def available() -> bool:
    return _load()


def _consecutive_range(hits: list[int]) -> str | None:
    if not hits:
        return None
    if len(hits) == 1:
        return _refs[hits[0]]
    first_s, first_a = _refs[hits[0]].split(":")
    last_s, last_a = _refs[hits[-1]].split(":")
    if first_s == last_s and hits[-1] - hits[0] == len(hits) - 1:
        return f"{first_s}:{first_a}-{last_a}"
    return _refs[hits[0]]


def search(term: str, limit: int = 50) -> list[tuple[str, str]]:
    """Recherche `term` dans le texte coranique normalise.

    Renvoie les couples (ref 'S:A', texte normalise) des versets contenant le
    terme, jusqu'a `limit`. Aucun appel reseau (index local charge une fois).
    """
    if not _load():
        return []
    seg = normalize(term)
    if not seg:
        return []
    hits: list[tuple[str, str]] = []
    for i, ver in enumerate(_norm):
        if seg in ver:
            hits.append((_refs[i], ver))
            if len(hits) >= limit:
                break
    return hits


def count_ayat() -> dict[int, int]:
    """Nombre de versets par sourate, derive des refs 'S:A' de l'index."""
    out: dict[int, int] = {}
    if not _load():
        return out
    cur_s, cur_a = 0, 0
    for ref in _refs:
        s, a = (int(x) for x in ref.split(":"))
        if s == cur_s:
            cur_a = max(cur_a, a)
        else:
            if cur_s:
                out[cur_s] = cur_a
            cur_s, cur_a = s, a
    if cur_s:
        out[cur_s] = cur_a
    return out


def iter_verses() -> list[tuple[str, str]]:
    """Tous les couples (ref 'S:A', texte normalise) — index charge au besoin."""
    if not _load():
        return []
    return list(zip(_refs, _norm))


def get(ref: str) -> str | None:
    """Texte normalise du verset 'S:A', ou None s'il est introuvable."""
    for _r, _t in zip(_refs, _norm):
        if _r == ref:
            return _t
    return None


def find_ref(arabic_text: str, min_len: int = 8) -> str | None:
    """Cherche `arabic_text` dans le Coran. Renvoie 'S:A', 'S:A1-A2' ou None.

    Confiance :
      - segment court (< 20 lettres) : il doit couvrir >= 55 % du verset trouve
        (evite de matcher un fragment minuscule au milieu d'un long verset) ;
      - segment tres court (< min_len) : rejete.
    """
    if not _load():
        return None
    seg = normalize(arabic_text)
    if len(seg) < min_len:
        return None

    # 1) Le segment est une portion d'un verset -> plus court verset qui le contient.
    best_i, best_len = -1, 10 ** 9
    for i, ver in enumerate(_norm):
        if len(ver) >= len(seg) and seg in ver and len(ver) < best_len:
            best_i, best_len = i, len(ver)
    if best_i >= 0:
        if len(seg) >= 20 or len(seg) / best_len >= 0.55:
            return _refs[best_i]

    # 2) Un ou plusieurs versets entiers sont contenus dans le segment.
    hits = [i for i, ver in enumerate(_norm) if len(ver) >= min_len and ver in seg]
    if hits:
        return _consecutive_range(hits)

    return None
