"""
fallback_translations.py — Traduction hors-ligne (dernier repli).

Quand tous les fournisseurs (Gemini, Groq, OpenRouter, Azure) échouent, on tente
une correspondance locale dans un dictionnaire de phrases courantes du prêche.
La couverture est partielle mais permet de diffuser une traduction grossière
plutôt que de laisser les auditeurs avec l'arabe seul.

Aucun appel réseau, 100 % local.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("dailymuslim.fallback")

_DATA_PATH = Path(__file__).resolve().parent / "data" / "fallback_translations.json"
_data: dict[str, dict[str, str]] = {}
_loaded = False


def _normalize(s: str) -> str:
    """Normalisation simple : minuscule, retrait ponctuation, espaces."""
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r"[\u0600-\u064f\u0650-\u06ff\u0750-\u077f\W]+", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load() -> bool:
    global _loaded, _data
    if _loaded:
        return bool(_data)
    _loaded = True
    try:
        raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        _data = raw.get("phrases", {})
    except (OSError, ValueError) as exc:
        logger.warning("fallback translations: %r", exc)
        _data = {}
    return bool(_data)


def available() -> bool:
    return load()


def fallback_translate(arabic_text: str, target_langs: list[str]) -> dict | None:
    """Tente une traduction locale par correspondance de phrase.

    Retourne {arabic, is_quran:False, quran_ref:None, is_hadith:False, translations:{lang:text}}
    ou None si aucune phrase ne correspond.
    """
    if not load() or not arabic_text:
        return None

    norm = _normalize(arabic_text)
    if not norm:
        return None

    # Cherche la phrase la plus longue qui est un préfixe ou un sous-ensemble
    best_key = None
    best_len = 0
    for key in _data:
        nkey = _normalize(key)
        if not nkey:
            continue
        # Correspondance : la phrase clé est contenue dans le segment (ordre normalisé)
        if nkey in norm and len(nkey) > best_len:
            best_key = key
            best_len = len(nkey)

    if not best_key:
        return None

    translations = _data[best_key]
    out: dict[str, str] = {}
    for lang in target_langs:
        out[lang] = translations.get(lang, "")

    return {
        "arabic": arabic_text,
        "is_quran": False,
        "quran_ref": None,
        "is_hadith": False,
        "translations": out,
    }