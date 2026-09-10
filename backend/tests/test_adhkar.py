"""Parité des adhkars.

La collection est dupliquée : copie embarquée dans `frontend/index.html`
(accès hors-ligne) et `backend/data/adhkar.json` servie par `/api/adhkar`.
Ces deux sources doivent rester rigoureusement identiques, sinon les
utilisateurs en ligne et hors-ligne voient des contenus différents.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

FRONTEND_HTML = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
CATEGORIES = ["morning", "evening", "post_prayer", "sleep", "wake", "travel",
              "protection", "gratitude"]
LANGS = ["fr", "en", "nl", "ar"]


def embedded_categories() -> dict:
    """Parse la variable `ADHKAR_CATEGORIES` de index.html (JS) en dict."""
    html = FRONTEND_HTML.read_text(encoding="utf-8")
    m = re.search(r"const ADHKAR_CATEGORIES = (\{.*?\n\};)", html, re.S)
    assert m, "bloc ADHKAR_CATEGORIES introuvable dans index.html"
    # Transforme le littéral JS (clés nues) en JSON (clés entre guillemets).
    block = re.sub(r"([,{]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)", r'\1"\2"\3',
                   m.group(1).rstrip(";"))
    return json.loads(block)


def _norm(items: list) -> list:
    """Rangée comparable : texte arabe, objectif et traductions (4 langues)."""
    return [
        {"ar": it["ar"], "tgt": it["tgt"],
         "tr": {lang: (it.get("tr", {}) or {}).get(lang, "") for lang in LANGS}}
        for it in items
    ]


def test_adhkar_categories_match():
    assert set(embedded_categories()) == set(CATEGORIES)


def test_adhkar_endpoint_mirrors_embedded(app_client):
    fe = embedded_categories()
    for cat in CATEGORIES:
        r = app_client.get(f"/api/adhkar/{cat}")
        assert r.status_code == 200, cat
        be = r.json()["items"]
        assert _norm(be) == _norm(fe[cat]), (
            f"Dérive adhkar [{cat}] : /api/adhkar et la copie embarquée de "
            f"index.html doivent être identiques (textes, ordre, langues "
            f"{LANGS}, objectifs). Mettre à jour les deux sources."
        )