"""
translator.py — Traduction & transcription avec **chaîne de repli multi-fournisseurs**.

API publique (inchangée) :
  - translate_segment(arabic_text, target_langs, glossary="", *, use_cache=True) -> dict | None
  - transcribe_audio(audio_bytes, mime_type) -> str | None
  - has_api_key() -> bool          (au moins un fournisseur est configuré)
  - last_error() -> str            (raison du dernier échec : quota / auth / network / ...)
  - last_provider() -> str         (fournisseur ayant produit la dernière traduction)
  - aclose()

Fournisseurs de TRADUCTION essayés dans l'ordre de TRANSLATE_PROVIDERS
(défaut : gemini,groq,openrouter,azure). Seuls ceux dont la/les clé(s) sont
présentes sont réellement tentés. Le premier qui répond gagne ; sinon → None
(le backend passe en mode dégradé : diffusion de l'arabe sans traduction).

  gemini      GEMINI_API_KEY  (ou GEMINI_API_KEYS="k1,k2,k3" pour la rotation),
              GEMINI_MODEL (défaut gemini-2.5-flash-lite)
  groq        GROQ_API_KEY, GROQ_MODEL (défaut llama-3.3-70b-versatile)   — OpenAI-compatible
  openrouter  OPENROUTER_API_KEY, OPENROUTER_MODEL
              (défaut meta-llama/llama-3.3-70b-instruct:free)              — OpenAI-compatible
  azure       AZURE_TRANSLATOR_KEY, AZURE_TRANSLATOR_REGION                — MT pure (2 M car./mois gratuits)

Fournisseurs de TRANSCRIPTION (STT_PROVIDERS, défaut : groq,gemini) :
  groq        GROQ_API_KEY  -> whisper-large-v3 (excellent en arabe / darija)
  gemini      GEMINI_API_KEY
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from collections import OrderedDict
from pathlib import Path

import httpx

logger = logging.getLogger("dailymuslim.translator")

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def _keys(*names: str) -> list[str]:
    out: list[str] = []
    for n in names:
        for part in os.getenv(n, "").split(","):
            k = part.strip()
            if k and k not in out:
                out.append(k)
    return out


GEMINI_KEYS = _keys("GEMINI_API_KEYS", "GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
MODEL = GEMINI_MODEL  # rétro-compat (affiché dans /healthz)
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

GROQ_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3").strip()
_GROQ_BASE = "https://api.groq.com/openai/v1"

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
).strip()
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"

AZURE_KEY = os.getenv("AZURE_TRANSLATOR_KEY", "").strip()
AZURE_REGION = os.getenv("AZURE_TRANSLATOR_REGION", "").strip()
_AZURE_URL = "https://api.cognitive.microsofttranslator.com/translate"
_AZURE_LANGS = {"fr", "en", "nl", "de", "es", "tr", "ur", "bn", "ha", "ar"}

TRANSLATE_PROVIDERS = [
    p.strip() for p in os.getenv(
        "TRANSLATE_PROVIDERS", "gemini,groq,openrouter,azure"
    ).split(",") if p.strip()
]
STT_PROVIDERS = [
    p.strip() for p in os.getenv("STT_PROVIDERS", "groq,gemini").split(",") if p.strip()
]

REQUEST_TIMEOUT = 22.0
CACHE_SIZE = 400
CACHE_TTL = 60 * 45

# --------------------------------------------------------------------------- #
# Prompt système (SYSTEM_PROMPT.md, repli inline)
# --------------------------------------------------------------------------- #

_FALLBACK_PROMPT = (
    "Tu es un traducteur spécialisé dans le prêche musulman (khutbah). Tu traduis "
    "fidèlement, sobrement et sans interprétation personnelle, segment par segment, "
    "de l'arabe vers les langues cibles demandées. Conserve les termes islamiques "
    "translittérés d'usage (salât, taqwa, sunnah...) avec au besoin une glose courte "
    "entre parenthèses à la première occurrence. « Allah » reste « Allah ». Rends les "
    "formules d'eulogie. Si le segment cite le Coran, mets is_quran=true et donne "
    "quran_ref si tu la reconnais avec certitude, sinon null ; traduis alors au plus "
    "près du texte. Ne complète jamais une phrase coupée. Réponds UNIQUEMENT en JSON "
    "conforme au schéma, une entrée par langue demandée, aucune langue omise."
)


def _load_system_prompt() -> str:
    for candidate in (
        Path(__file__).resolve().parent.parent / "SYSTEM_PROMPT.md",
        Path(__file__).resolve().parent / "SYSTEM_PROMPT.md",
    ):
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        marker = "\n---\n"
        idx = text.find(marker)
        body = (text[idx + len(marker):] if idx != -1 else text).strip()
        if len(body) > 200:
            return body
    return _FALLBACK_PROMPT


SYSTEM_PROMPT = _load_system_prompt()

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "arabic": {"type": "string"},
        "is_quran": {"type": "boolean"},
        "quran_ref": {"type": "string", "nullable": True},
        "is_hadith": {"type": "boolean"},
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"lang": {"type": "string"}, "text": {"type": "string"}},
                "required": ["lang", "text"],
            },
        },
    },
    "required": ["arabic", "is_quran", "translations"],
}

# --------------------------------------------------------------------------- #
# Cache LRU + TTL
# --------------------------------------------------------------------------- #

_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()


def _cache_get(key: str):
    hit = _cache.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.time() - ts > CACHE_TTL:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return value


def _cache_put(key: str, value: dict):
    _cache[key] = (time.time(), value)
    _cache.move_to_end(key)
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)


# --------------------------------------------------------------------------- #
# HTTP + état
# --------------------------------------------------------------------------- #

_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    return _client


async def aclose():
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


_last_error = ""       # "" | quota | auth | server | network | bad_response | no_provider
_last_provider = ""
_gemini_key_idx = 0     # rotation


def last_error() -> str:
    return _last_error


def last_provider() -> str:
    return _last_provider


def _provider_configured(name: str) -> bool:
    return {
        "gemini": bool(GEMINI_KEYS),
        "groq": bool(GROQ_KEY),
        "openrouter": bool(OPENROUTER_KEY),
        "azure": bool(AZURE_KEY and AZURE_REGION),
    }.get(name, False)


def has_api_key() -> bool:
    """Vrai si au moins un fournisseur de traduction est utilisable."""
    return any(_provider_configured(p) for p in TRANSLATE_PROVIDERS)


def provider_status() -> dict[str, bool]:
    """État de configuration (clé présente/région) de chaque fournisseur actif.
    N'appelle aucun fournisseur : diagnostic purement local, rapide."""
    return {name: _provider_configured(name) for name in TRANSLATE_PROVIDERS}


def _status_to_error(code: int) -> str:
    if code in (401, 403):
        return "auth"
    if code == 429:
        return "quota"
    if code >= 500:
        return "server"
    return "bad_response"


def _worst(errors: list[str]) -> str:
    for pref in ("quota", "auth", "server", "bad_response", "network"):
        if pref in errors:
            return pref
    return errors[0] if errors else "no_provider"


# --------------------------------------------------------------------------- #
# Prompt utilisateur commun + parsing JSON commun
# --------------------------------------------------------------------------- #

CONTEXT_MAX = 3          # nombre maximal de segments précédents fournis au LLM
_CONTEXT_SEG_CAP = 350   # longueur max (caractères) d'un segment de contexte


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(v, hi))


# Rendu configurable via l'environnement (ex: CONTEXT_SEGMENTS=5), borné 1..6
# pour maîtriser la consommation de tokens.
CONTEXT_MAX = _env_int("CONTEXT_SEGMENTS", CONTEXT_MAX, 1, 6)


def _normalize_context(context) -> list[dict]:
    """Contexte glissant : derniers segments déjà traduits, borné et nettoyé."""
    if not context:
        return []
    out: list[dict] = []
    for c in list(context)[-CONTEXT_MAX:]:
        if not isinstance(c, dict):
            continue
        ar = str(c.get("arabic") or "").strip()[:_CONTEXT_SEG_CAP]
        if not ar:
            continue
        out.append({
            "arabic": ar,
            "translated": str(c.get("translated") or "").strip()[:_CONTEXT_SEG_CAP],
        })
    return out


def _user_msg(arabic_text: str, langs: list[str], glossary: str,
              context: list[dict] | None = None) -> str:
    gloss = (
        ("GLOSSAIRE DE LA MOSQUÉE (à respecter strictement pour les noms propres, "
         "titres et translittérations) :\n" + glossary + "\n\n") if glossary else ""
    )
    ctx = ""
    if context:
        lines = [
            "CONTEXTE — les segments précédents te sont fournis pour comprendre les "
            "pronoms et les références du sermon (ne les traduis PAS, n'inclus jamais "
            "leur contenu dans ta réponse)."
        ]
        for i, c in enumerate(context, 1):
            line = f"[{i}] « {c['arabic']} »"
            if c.get("translated"):
                line += f"\n    → {c['translated']}"
            lines.append(line)
        ctx = "\n".join(lines) + "\n\n"
    return (
        gloss
        + ctx
        + "Langues cibles (codes) : " + ", ".join(langs) + ".\n"
        "Traduis le segment de khutbah suivant (arabe). Fournis une entrée par langue, "
        "dans cet ordre, sans en omettre aucune. Réponds UNIQUEMENT en JSON conforme "
        "au schéma { arabic, is_quran, quran_ref, is_hadith, "
        "translations:[{lang,text}] }.\n\nSEGMENT :\n" + arabic_text
    )


def _parse_llm_json(raw: str, langs: list[str], arabic_text: str) -> dict | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        s, e = raw.find("{"), raw.rfind("}")
        if s == -1 or e == -1:
            return None
        try:
            data = json.loads(raw[s:e + 1])
        except json.JSONDecodeError:
            return None

    tmap: dict[str, str] = {}
    items = data.get("translations")
    if isinstance(items, list):
        for it in items:
            code = str(it.get("lang", "")).strip()
            if code:
                tmap[code] = str(it.get("text", "")).strip()
    elif isinstance(items, dict):
        for code, txt in items.items():
            tmap[str(code).strip()] = str(txt).strip()
    for l in langs:
        tmap.setdefault(l, "")

    return {
        "arabic": str(data.get("arabic") or arabic_text).strip(),
        "is_quran": bool(data.get("is_quran")),
        "quran_ref": (data.get("quran_ref") or None),
        "is_hadith": bool(data.get("is_hadith")),
        "translations": tmap,
    }


# --------------------------------------------------------------------------- #
# Fournisseur : Gemini (format natif, rotation de clés)
# --------------------------------------------------------------------------- #

async def _prov_gemini(arabic_text, langs, glossary, context=None) -> tuple[dict | None, str]:
    global _gemini_key_idx
    if not GEMINI_KEYS:
        return None, "no_provider"
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": _user_msg(arabic_text, langs, glossary, context)}]}],
        "generationConfig": {
            "temperature": 0.2, "topP": 0.9, "candidateCount": 1,
            "maxOutputTokens": 2048, "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
        },
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_NONE"}
            for c in ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                      "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
        ],
    }
    url = f"{_GEMINI_BASE}/models/{GEMINI_MODEL}:generateContent"
    err = "network"
    n = len(GEMINI_KEYS)
    for _ in range(n):                       # essaie chaque clé une fois
        key = GEMINI_KEYS[_gemini_key_idx % n]
        _gemini_key_idx += 1
        try:
            r = await _http().post(url, params={"key": key}, json=payload)
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            logger.warning("gemini réseau: %r", exc)
            err = "network"
            continue
        if r.status_code == 200:
            try:
                parts = r.json()["candidates"][0]["content"]["parts"]
                raw = "".join(p.get("text", "") for p in parts)
            except (KeyError, IndexError, TypeError, ValueError):
                return None, "bad_response"
            return _parse_llm_json(raw, langs, arabic_text), ""
        err = _status_to_error(r.status_code)
        logger.warning("gemini HTTP %s (%s)", r.status_code, err)
        if err == "quota":                   # clé épuisée -> essaie la suivante
            continue
        if err == "server":
            continue
        return None, err                     # auth / bad_response : inutile d'insister
    return None, err


# --------------------------------------------------------------------------- #
# Fournisseurs OpenAI-compatibles : Groq, OpenRouter
# --------------------------------------------------------------------------- #

async def _prov_openai_compat(base, key, model, arabic_text, langs, glossary,
                              context=None, extra_headers=None) -> tuple[dict | None, str]:
    if not key:
        return None, "no_provider"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    body = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_msg(arabic_text, langs, glossary, context)},
        ],
    }
    try:
        r = await _http().post(f"{base}/chat/completions", headers=headers, json=body)
    except (httpx.HTTPError, asyncio.TimeoutError) as exc:
        logger.warning("openai-compat (%s) réseau: %r", base, exc)
        return None, "network"
    if r.status_code != 200:
        err = _status_to_error(r.status_code)
        logger.warning("openai-compat (%s) HTTP %s (%s): %.200s", base, r.status_code, err, r.text)
        return None, err
    try:
        raw = r.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        return None, "bad_response"
    return _parse_llm_json(raw, langs, arabic_text), ""


async def _prov_groq(arabic_text, langs, glossary, context=None):
    return await _prov_openai_compat(_GROQ_BASE, GROQ_KEY, GROQ_MODEL,
                                    arabic_text, langs, glossary, context)


async def _prov_openrouter(arabic_text, langs, glossary, context=None):
    return await _prov_openai_compat(
        _OPENROUTER_BASE, OPENROUTER_KEY, OPENROUTER_MODEL, arabic_text, langs, glossary,
        context, extra_headers={"HTTP-Referer": "https://github.com/", "X-Title": "khutbah-live"},
    )


# --------------------------------------------------------------------------- #
# Fournisseur : Azure AI Translator (MT pure — pas de détection Coran)
# --------------------------------------------------------------------------- #

async def _prov_azure(arabic_text, langs, glossary, context=None) -> tuple[dict | None, str]:
    if not (AZURE_KEY and AZURE_REGION):
        return None, "no_provider"
    targets = [l for l in langs if l in _AZURE_LANGS and l != "ar"]
    if not targets:
        return {"arabic": arabic_text, "is_quran": False, "quran_ref": None,
                "is_hadith": False, "translations": {l: "" for l in langs}}, ""
    params = [("api-version", "3.0"), ("from", "ar")] + [("to", t) for t in targets]
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_REGION,
        "Content-Type": "application/json",
    }
    try:
        r = await _http().post(_AZURE_URL, params=params, headers=headers,
                               json=[{"Text": arabic_text}])
    except (httpx.HTTPError, asyncio.TimeoutError) as exc:
        logger.warning("azure réseau: %r", exc)
        return None, "network"
    if r.status_code != 200:
        err = _status_to_error(r.status_code)
        logger.warning("azure HTTP %s (%s): %.200s", r.status_code, err, r.text)
        return None, err
    try:
        trans = r.json()[0]["translations"]
    except (KeyError, IndexError, TypeError, ValueError):
        return None, "bad_response"
    tmap = {t["to"]: t["text"] for t in trans}
    for l in langs:
        tmap.setdefault(l, "")
    return {"arabic": arabic_text, "is_quran": False, "quran_ref": None,
            "is_hadith": False, "translations": tmap}, ""


_TRANSLATE_IMPL = {
    "gemini": _prov_gemini,
    "groq": _prov_groq,
    "openrouter": _prov_openrouter,
    "azure": _prov_azure,
}


# --------------------------------------------------------------------------- #
# API publique : traduction
# --------------------------------------------------------------------------- #

async def translate_segment(
    arabic_text: str,
    target_langs: list[str],
    glossary: str = "",
    *,
    context: list[dict] | None = None,
    use_cache: bool = True,
) -> dict | None:
    """Traduit `arabic_text` vers `target_langs` via la chaîne de fournisseurs.

    `context` : derniers segments déjà diffusés ({arabic, translated}) pour que le
    LLM accorde correctement les pronoms et références (contexte glissant).
    Il est borné (CONTEXT_MAX segments, tronqués) et fait partie de la clé de cache.

    Retourne {arabic, is_quran, quran_ref, is_hadith, translations:{lang:text}}
    ou None si tous les fournisseurs échouent.
    """
    global _last_error, _last_provider

    arabic_text = (arabic_text or "").strip()
    glossary = (glossary or "").strip()[:4000]
    langs = [l for l in dict.fromkeys(target_langs) if l and l != "ar"]
    if not arabic_text or not langs:
        return None
    context = _normalize_context(context)

    ctx_key = ("\x1fctx" + json.dumps(context, ensure_ascii=False)
               if context else "")
    cache_key = arabic_text + "\x1f" + ",".join(sorted(langs)) + "\x1f" + glossary + ctx_key
    if use_cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    chain = [p for p in TRANSLATE_PROVIDERS if _provider_configured(p) and p in _TRANSLATE_IMPL]
    if not chain:
        _last_error = "no_provider"
        return None

    errors: list[str] = []
    for name in chain:
        try:
            result, err = await _TRANSLATE_IMPL[name](arabic_text, langs, glossary, context)
        except Exception as exc:  # défensif : jamais casser le flux
            logger.warning("fournisseur %s exception: %r", name, exc)
            result, err = None, "server"
        if result is not None:
            _last_error = ""
            _last_provider = name
            _cache_put(cache_key, result)
            return result
        errors.append(err)

    # Dernier repli : dictionnaire local de phrases courantes (hors-ligne)
    try:
        import fallback_translations
        fb = fallback_translations.fallback_translate(arabic_text, langs)
        if fb is not None:
            _last_error = ""
            _last_provider = "local"
            _cache_put(cache_key, fb)
            return fb
    except Exception as exc:
        logger.warning("fallback local: %r", exc)

    _last_error = _worst(errors)
    logger.error("traduction impossible — chaîne échouée (%s -> %s)", chain, errors)
    return None


# --------------------------------------------------------------------------- #
# API publique : transcription audio (repli du mode « Audio → serveur »)
# --------------------------------------------------------------------------- #

_STT_INSTRUCTION = (
    "Transcris fidèlement cet extrait audio d'un prêche en ARABE. "
    "Rends UNIQUEMENT le texte arabe prononcé, sans traduction, sans ponctuation "
    "superflue, sans commentaire, sans guillemets."
)


async def _stt_groq(audio_bytes: bytes, mt: str) -> str | None:
    if not GROQ_KEY:
        return None
    ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4",
           "audio/mpeg": "mp3", "audio/wav": "wav"}.get(mt, "webm")
    files = {
        "file": (f"chunk.{ext}", audio_bytes, mt or "audio/webm"),
        "model": (None, GROQ_STT_MODEL),
        "language": (None, "ar"),
        "temperature": (None, "0"),
        "response_format": (None, "text"),
    }
    try:
        r = await _http().post(f"{_GROQ_BASE}/audio/transcriptions",
                               headers={"Authorization": f"Bearer {GROQ_KEY}"}, files=files)
    except (httpx.HTTPError, asyncio.TimeoutError) as exc:
        logger.warning("groq-stt réseau: %r", exc)
        return None
    if r.status_code != 200:
        logger.warning("groq-stt HTTP %s: %.200s", r.status_code, r.text)
        return None
    return (r.text or "").strip().strip('"')


async def _stt_gemini(audio_bytes: bytes, mt: str) -> str | None:
    if not GEMINI_KEYS:
        return None
    b64 = base64.b64encode(audio_bytes).decode("ascii")
    payload = {
        "contents": [{"role": "user", "parts": [
            {"text": _STT_INSTRUCTION},
            {"inlineData": {"mimeType": mt or "audio/webm", "data": b64}},
        ]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 1024},
    }
    url = f"{_GEMINI_BASE}/models/{GEMINI_MODEL}:generateContent"
    try:
        r = await _http().post(url, params={"key": GEMINI_KEYS[0]}, json=payload)
    except (httpx.HTTPError, asyncio.TimeoutError) as exc:
        logger.warning("gemini-stt réseau: %r", exc)
        return None
    if r.status_code != 200:
        logger.warning("gemini-stt HTTP %s", r.status_code)
        return None
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError, ValueError):
        return None


_STT_IMPL = {"groq": _stt_groq, "gemini": _stt_gemini}


async def transcribe_audio(audio_bytes: bytes, mime_type: str) -> str | None:
    if not audio_bytes:
        return None
    mt = (mime_type or "audio/webm").split(";")[0].strip() or "audio/webm"
    for name in STT_PROVIDERS:
        impl = _STT_IMPL.get(name)
        if not impl:
            continue
        try:
            text = await impl(audio_bytes, mt)
        except Exception as exc:
            logger.warning("fournisseur STT %s exception: %r", name, exc)
            text = None
        if text:
            return text
    return None


# --------------------------------------------------------------------------- #
# Assistant (chat) : même chaîne de repli multi-fournisseurs, réponses en texte
# --------------------------------------------------------------------------- #

_ASSISTANT_PROMPT = (
    "Tu es « DailY Muslim », un assistant musulman bienveillant et utile. Tu réponds "
    "de façon concise, respectueuse et islamiquement juste, en t'appuyant sur le Coran "
    "et la Sunna authentique. Si une question touche à un jugement religieux délicat, "
    "tu précises qu'il faut consulter une personne qualifiée. Tu peux utiliser quelques "
    "citations (Coran/hadith) avec leurs références. Tu restes dans la langue de la "
    "question de l'utilisateur (fr, en, nl, ar...). Réponds UNIQUEMENT avec le texte "
    "de ta réponse, sans préambule ni méta-explication."
)

ASSISTANT_DISCLAIMER = (
    "Assistant informatif — consultez une personne qualifiée pour les décisions religieuses."
)


def _assistant_messages(user_msg: str, history: list[dict]) -> list[dict]:
    msgs: list[dict] = []
    if isinstance(history, list):
        for h in history[-8:]:
            if not isinstance(h, dict):
                continue
            role = h.get("role")
            content = str(h.get("content", "")).strip()
            if role in ("user", "assistant") and content:
                msgs.append({"role": role, "content": content[:4000]})
    msgs.append({"role": "user", "content": str(user_msg)[:8000]})
    return msgs


async def _chat_gemini(user_msg: str, history: list[dict]) -> tuple[str | None, str]:
    if not GEMINI_KEYS:
        return None, "no_provider"
    contents = []
    for m in _assistant_messages(user_msg, history):
        contents.append({"role": m["role"], "parts": [{"text": m["content"]}]})
    payload = {
        "systemInstruction": {"parts": [{"text": _ASSISTANT_PROMPT}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.4, "topP": 0.9, "candidateCount": 1,
            "maxOutputTokens": 1024,
        },
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_NONE"}
            for c in ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                      "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
        ],
    }
    url = f"{_GEMINI_BASE}/models/{GEMINI_MODEL}:generateContent"
    err = "network"
    n = len(GEMINI_KEYS)
    for _ in range(n):
        key = GEMINI_KEYS[0]
        try:
            r = await _http().post(url, params={"key": key}, json=payload)
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            logger.warning("gemini-chat réseau: %r", exc)
            err = "network"
            continue
        if r.status_code == 200:
            try:
                parts = r.json()["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts).strip()
            except (KeyError, IndexError, TypeError, ValueError):
                return None, "bad_response"
            return text or None, ""
        err = _status_to_error(r.status_code)
        logger.warning("gemini-chat HTTP %s (%s)", r.status_code, err)
        if err in ("quota", "server"):
            continue
        return None, err
    return None, err


async def _chat_openai_compat(base: str, key: str, model: str, user_msg: str,
                              history: list[dict], extra_headers=None) -> tuple[str | None, str]:
    if not key:
        return None, "no_provider"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    body = {
        "model": model,
        "temperature": 0.4,
        "max_tokens": 1024,
        "messages": [{"role": "system", "content": _ASSISTANT_PROMPT}]
                    + _assistant_messages(user_msg, history),
    }
    try:
        r = await _http().post(f"{base}/chat/completions", headers=headers, json=body)
    except (httpx.HTTPError, asyncio.TimeoutError) as exc:
        logger.warning("openai-compat chat (%s) réseau: %r", base, exc)
        return None, "network"
    if r.status_code != 200:
        err = _status_to_error(r.status_code)
        logger.warning("openai-compat chat (%s) HTTP %s (%s): %.200s", base, r.status_code, err, r.text)
        return None, err
    try:
        text = r.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        return None, "bad_response"
    return (str(text).strip() or None), ""


async def chat_assistant(user_msg: str, history: list[dict] | None = None) -> dict | None:
    """Répond à une question de l'assistant via la chaîne de fournisseurs.

    Retourne {reply, provider} ou None si aucun fournisseur ne répond.
    """
    global _last_error, _last_provider
    user_msg = (user_msg or "").strip()
    if not user_msg:
        return None
    history = history or []
    chain = [p for p in TRANSLATE_PROVIDERS if _provider_configured(p)]
    errors: list[str] = []
    for name in chain:
        try:
            if name == "gemini":
                text, err = await _chat_gemini(user_msg, history)
            elif name in ("groq", "openrouter"):
                kwargs = {"extra_headers": {
                    "HTTP-Referer": "https://github.com/",
                    "X-Title": "daily-muslim",
                }} if name == "openrouter" else {}
                text, err = await _chat_openai_compat(
                    {"groq": _GROQ_BASE, "openrouter": _OPENROUTER_BASE}[name],
                    {"groq": GROQ_KEY, "openrouter": OPENROUTER_KEY}[name],
                    {"groq": GROQ_MODEL, "openrouter": OPENROUTER_MODEL}[name],
                    user_msg, history, **kwargs)
            else:
                continue
        except Exception as exc:
            logger.warning("fournisseur chat %s exception: %r", name, exc)
            text, err = None, "server"
        if text:
            _last_error = ""
            _last_provider = name
            return {"reply": text, "provider": name}
        errors.append(err)

    _last_error = _worst(errors)
    logger.error("assistant — chaîne échouée (%s -> %s)", chain, errors)
    return None
