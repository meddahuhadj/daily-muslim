"""Fixtures communes. Gemini est toujours mocké : aucun appel réseau dans les tests."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Autorise la création de session sans clé (les tests mockent la traduction).
os.environ.setdefault("ALLOW_NO_API_KEY", "1")
os.environ.setdefault("GEMINI_API_KEY", "")


@pytest.fixture
def fake_translate():
    """Retourne une fonction de traduction déterministe et son compteur d'appels."""
    calls = []

    async def _t(arabic, langs, glossary="", *, context=None, use_cache=True):
        calls.append({"arabic": arabic, "langs": list(langs), "glossary": glossary,
                      "context": context})
        low = arabic.strip()
        is_q = low.startswith("قل هو الله") or "الحمد لله رب العالمين" in low
        return {
            "arabic": arabic,
            "is_quran": is_q,
            "quran_ref": "1:2" if "الحمد لله رب العالمين" in low else None,
            "is_hadith": low.startswith("قال رسول"),
            "translations": {l: f"[{l}] {arabic[:20]}" for l in langs},
        }

    _t.calls = calls
    return _t


@pytest.fixture
def app_client(monkeypatch, fake_translate):
    """TestClient FastAPI avec traducteur mocké et état des rooms remis à zéro."""
    from fastapi.testclient import TestClient

    import main
    import translator

    monkeypatch.setattr(translator, "has_api_key", lambda: True)
    monkeypatch.setattr(translator, "translate_segment", fake_translate)
    monkeypatch.setattr(main.translator, "has_api_key", lambda: True)
    monkeypatch.setattr(main.translator, "translate_segment", fake_translate)
    monkeypatch.setattr(main.translator, "last_error", lambda: "quota")

    main.ROOMS.clear()
    main.session_limiter.reset()
    with TestClient(main.app) as client:
        client._fake = fake_translate
        yield client
    main.ROOMS.clear()
