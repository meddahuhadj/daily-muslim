"""translator.py — chaîne de repli multi-fournisseurs (HTTP entièrement mocké)."""
import json

import pytest

import translator


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


def _gemini_ok(obj):
    return _Resp(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]})


def _openai_ok(obj):
    return _Resp(200, {"choices": [{"message": {"content": json.dumps(obj)}}]})


def _azure_ok(pairs):
    return _Resp(200, [{"translations": [{"to": k, "text": v} for k, v in pairs.items()]}])


class FakeHttp:
    """Client factice : route .post() selon l'URL, via des handlers fournis par le test."""
    def __init__(self, handlers):
        self.handlers = handlers          # liste de (motif_url, fonction(url,kw)->_Resp)
        self.calls = []

    async def post(self, url, **kw):
        self.calls.append(url)
        for needle, fn in self.handlers:
            if needle in url:
                return fn(url, kw)
        raise AssertionError(f"URL non gérée par le test : {url}")


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    translator._cache.clear()
    translator._last_error = ""
    translator._last_provider = ""
    translator._gemini_key_idx = 0
    monkeypatch.setattr(translator, "GEMINI_KEYS", ["gk1"])
    monkeypatch.setattr(translator, "GROQ_KEY", "")
    monkeypatch.setattr(translator, "OPENROUTER_KEY", "")
    monkeypatch.setattr(translator, "AZURE_KEY", "")
    monkeypatch.setattr(translator, "AZURE_REGION", "")
    monkeypatch.setattr(translator, "TRANSLATE_PROVIDERS",
                        ["gemini", "groq", "openrouter", "azure"])


def _use(monkeypatch, *handlers):
    fake = FakeHttp(list(handlers))
    monkeypatch.setattr(translator, "_http", lambda: fake)
    return fake


async def test_gemini_success(monkeypatch):
    obj = {"arabic": "نص", "is_quran": True, "quran_ref": "2:255",
           "translations": [{"lang": "fr", "text": "texte"}, {"lang": "en", "text": "text"}]}
    _use(monkeypatch, ("generativelanguage", lambda u, k: _gemini_ok(obj)))
    r = await translator.translate_segment("نص عربي", ["fr", "en"])
    assert r["translations"] == {"fr": "texte", "en": "text"}
    assert r["is_quran"] and r["quran_ref"] == "2:255"
    assert translator.last_provider() == "gemini"
    assert translator.last_error() == ""


async def test_falls_back_to_groq_on_gemini_quota(monkeypatch):
    monkeypatch.setattr(translator, "GROQ_KEY", "grq")
    obj = {"arabic": "x", "is_quran": False,
           "translations": [{"lang": "fr", "text": "via groq"}]}
    _use(monkeypatch,
         ("generativelanguage", lambda u, k: _Resp(429, {}, "quota")),
         ("groq.com", lambda u, k: _openai_ok(obj)))
    r = await translator.translate_segment("x", ["fr"])
    assert r["translations"]["fr"] == "via groq"
    assert translator.last_provider() == "groq"
    assert translator.last_error() == ""


async def test_gemini_key_rotation_on_quota(monkeypatch):
    monkeypatch.setattr(translator, "GEMINI_KEYS", ["k1", "k2"])
    seen = []

    def gh(url, kw):
        seen.append(kw["params"]["key"])
        if kw["params"]["key"] == "k1":
            return _Resp(429, {}, "quota")
        return _gemini_ok({"arabic": "x", "is_quran": False,
                           "translations": [{"lang": "fr", "text": "ok k2"}]})

    _use(monkeypatch, ("generativelanguage", gh))
    r = await translator.translate_segment("x", ["fr"])
    assert r["translations"]["fr"] == "ok k2"
    assert seen == ["k1", "k2"]


async def test_azure_is_pure_mt(monkeypatch):
    monkeypatch.setattr(translator, "AZURE_KEY", "ak")
    monkeypatch.setattr(translator, "AZURE_REGION", "westeurope")
    monkeypatch.setattr(translator, "TRANSLATE_PROVIDERS", ["azure"])
    _use(monkeypatch,
         ("cognitive.microsofttranslator", lambda u, k: _azure_ok({"fr": "paix", "en": "peace"})))
    r = await translator.translate_segment("سلام", ["fr", "en"])
    assert r["translations"] == {"fr": "paix", "en": "peace"}
    assert r["is_quran"] is False and r["quran_ref"] is None
    assert translator.last_provider() == "azure"


async def test_all_providers_fail_reports_quota(monkeypatch):
    monkeypatch.setattr(translator, "GROQ_KEY", "grq")
    _use(monkeypatch,
         ("generativelanguage", lambda u, k: _Resp(429, {}, "q")),
         ("groq.com", lambda u, k: _Resp(429, {}, "q")))
    r = await translator.translate_segment("x", ["fr"])
    assert r is None
    assert translator.last_error() == "quota"


async def test_missing_language_filled_empty(monkeypatch):
    obj = {"arabic": "x", "is_quran": False, "translations": [{"lang": "fr", "text": "ok"}]}
    _use(monkeypatch, ("generativelanguage", lambda u, k: _gemini_ok(obj)))
    r = await translator.translate_segment("x", ["fr", "de"])
    assert r["translations"] == {"fr": "ok", "de": ""}


async def test_context_is_injected_into_prompt(monkeypatch):
    """Le contexte glissant doit figurer dans le message utilisateur, sans être
    confondu avec le segment à traduire, et être borné à 3 segments."""
    obj = {"arabic": "h", "is_quran": False,
           "translations": [{"lang": "fr", "text": "traduc"}]}
    captured = {}

    def gh(url, kw):
        captured["user"] = kw["json"]["contents"][0]["parts"][0]["text"]
        return _gemini_ok(obj)

    _use(monkeypatch, ("generativelanguage", gh))
    ctx = [{"arabic": "أ", "translated": "A"}, {"arabic": "ب", "translated": "B"},
           {"arabic": "ج", "translated": "C"}, {"arabic": "د", "translated": "D"}]
    r = await translator.translate_segment("ها", ["fr"], context=ctx)
    assert r["translations"]["fr"] == "traduc"
    low = captured["user"]
    assert "CONTEXTE" in low
    assert "« أ »" not in low                                # le plus ancien tronqué
    assert "« ب »" in low and "« ج »" in low and "« د »" in low  # 3 derniers conservés
    assert "SEGMENT" in low and low.index("« ب »") < low.index("SEGMENT")
    # le segment à traduire n'est pas dans le contexte
    assert low.rstrip().endswith("ها")


async def test_context_participates_in_cache_key(monkeypatch):
    """Deux appels avec le même contexte partagent le cache ; un contexte différent
    produit un nouvel appel fournisseur."""
    obj = {"arabic": "x", "is_quran": False, "translations": [{"lang": "fr", "text": "ok"}]}
    fake = _use(monkeypatch, ("generativelanguage", lambda u, k: _gemini_ok(obj)))
    c1 = [{"arabic": "أ", "translated": "A"}]
    c2 = [{"arabic": "أ", "translated": "A"}]
    assert await translator.translate_segment("x", ["fr"], context=c1) is not None
    assert await translator.translate_segment("x", ["fr"], context=c2) is not None
    assert len(fake.calls) == 1
    c3 = [{"arabic": "ب", "translated": "B"}]
    assert await translator.translate_segment("x", ["fr"], context=c3) is not None
    assert len(fake.calls) == 2


async def test_cache_hit_avoids_second_call(monkeypatch):
    obj = {"arabic": "x", "is_quran": False, "translations": [{"lang": "fr", "text": "ok"}]}
    fake = _use(monkeypatch, ("generativelanguage", lambda u, k: _gemini_ok(obj)))
    await translator.translate_segment("répétée", ["fr"])
    await translator.translate_segment("répétée", ["fr"])
    assert len(fake.calls) == 1
    await translator.translate_segment("répétée", ["fr"], use_cache=False)
    assert len(fake.calls) == 2


async def test_no_provider_configured(monkeypatch):
    monkeypatch.setattr(translator, "GEMINI_KEYS", [])
    assert translator.has_api_key() is False
    assert await translator.translate_segment("x", ["fr"]) is None
    assert translator.last_error() == "no_provider"


async def test_no_target_langs():
    assert await translator.translate_segment("نص", ["ar"]) is None
    assert await translator.translate_segment("", ["fr"]) is None


def test_system_prompt_is_the_real_one_not_the_fallback():
    assert translator.SYSTEM_PROMPT != translator._FALLBACK_PROMPT
    assert len(translator.SYSTEM_PROMPT) > 800
    low = translator.SYSTEM_PROMPT.lower()
    assert "is_quran" in low and "quran_ref" in low


def test_provider_status_reflects_configuration(monkeypatch):
    # _reset donne GEMINI_KEYS=[gk1] et tout le reste vide
    st = translator.provider_status()
    assert st == {"gemini": True, "groq": False,
                  "openrouter": False, "azure": False}
    monkeypatch.setattr(translator, "GROQ_KEY", "grq")
    monkeypatch.setattr(translator, "AZURE_KEY", "ak")
    monkeypatch.setattr(translator, "AZURE_REGION", "westeurope")
    st = translator.provider_status()
    assert st == {"gemini": True, "groq": True,
                  "openrouter": False, "azure": True}


async def test_context_max_is_used_at_call_time(monkeypatch):
    monkeypatch.setattr(translator, "CONTEXT_MAX", 5)
    ctx = [{"arabic": f"seg{i}"} for i in range(6)]
    norm = translator._normalize_context(ctx)
    assert [c["arabic"] for c in norm] == ["seg1", "seg2", "seg3", "seg4", "seg5"]
    monkeypatch.setattr(translator, "CONTEXT_MAX", 1)
    assert translator._normalize_context(ctx) == [{"arabic": "seg5", "translated": ""}]


async def test_stt_prefers_groq_then_gemini(monkeypatch):
    monkeypatch.setattr(translator, "GROQ_KEY", "grq")
    monkeypatch.setattr(translator, "STT_PROVIDERS", ["groq", "gemini"])
    _use(monkeypatch, ("groq.com/openai/v1/audio", lambda u, k: _Resp(200, {}, "نص مسموع")))
    assert await translator.transcribe_audio(b"xxxx", "audio/webm") == "نص مسموع"

    _use(monkeypatch,
         ("groq.com/openai/v1/audio", lambda u, k: _Resp(500, {}, "err")),
         ("generativelanguage", lambda u, k: _gemini_ok_text("نص من جيميني")))
    assert await translator.transcribe_audio(b"xxxx", "audio/webm") == "نص من جيميني"


def _gemini_ok_text(t):
    return _Resp(200, {"candidates": [{"content": {"parts": [{"text": t}]}}]})
