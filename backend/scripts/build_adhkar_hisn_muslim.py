"""Reconstruit backend/data/adhkar_hisn_muslim.json depuis l'API publique
islamic.app (https://docs.islamic.app/api-reference/dhikr), qui numerise le
livre de reference Hisn al-Muslim (« La Citadelle du musulman ») de Sheikh
Sa'id bin Ali bin Wahf Al-Qahtani : 132 chapitres, 267 invocations.

    python scripts/build_adhkar_hisn_muslim.py

Arabe + anglais uniquement (pas de francais disponible sur cette API a ce
jour). Le petit jeu existant (data/adhkar.json, fr/en/nl/ar, 8 categories)
n'est pas touche et reste utilise pour le compteur rapide de dhikr.
"""
import json
import re
import sys
import time
import urllib.request

BASE = "https://api.islamic.app/v1/dhikr"
OUT = __import__("os").path.join(
    __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))),
    "data", "adhkar_hisn_muslim.json")

_REF_RE = re.compile(r'<span class="hisn_english_reference">(.*?)</span>', re.S)
_TAG_RE = re.compile(r'<[^>]+>')


def _get(url: str, retries: int = 3) -> dict:
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "daily-muslim-app/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(1.5)


def _strip_tags(s: str) -> str:
    return _TAG_RE.sub("", s).strip() if s else s


def _extract_reference(en_body: str) -> str:
    if not en_body:
        return ""
    m = _REF_RE.search(en_body)
    return _strip_tags(m.group(1)) if m else ""


def main() -> None:
    cats_resp = _get(BASE)
    categories = cats_resp["data"]["categories"]
    print(f"{len(categories)} categories", file=sys.stderr)

    out_categories, out_duas, seen = [], [], set()
    for c in categories:
        num = c["number"]
        out_categories.append({"number": int(num), "en": c["en"], "ar": c["ar"], "count": c["count"]})
        duas = _get(f"{BASE}/{num}")["data"]["duas"]
        for d in duas:
            dn = d.get("number")
            if dn in seen:
                continue
            seen.add(dn)
            en = d.get("en") or {}
            translit = d.get("transliteration", {}).get("en") if isinstance(d.get("transliteration"), dict) else None
            virtue = d.get("virtue", {}).get("en") if isinstance(d.get("virtue"), dict) else None
            source = d.get("source", {}).get("en") if isinstance(d.get("source"), dict) else None
            rec = {
                "number": dn,
                "slug": d.get("slug"),
                "book": int(d.get("category", {}).get("number", num)),
                "book_name_en": d.get("category", {}).get("en", c["en"]),
                "book_name_ar": d.get("category", {}).get("ar", c["ar"]),
                "ar": (d.get("ar") or {}).get("text", ""),
                "en": en.get("text", ""),
                "repeat": d.get("repeatCount") or 1,
            }
            if translit:
                rec["transliteration"] = translit
            if virtue:
                rec["virtue"] = virtue
            reference = source or _extract_reference(en.get("body", ""))
            if reference:
                rec["reference"] = reference
            out_duas.append(rec)
        time.sleep(0.15)

    print(f"{len(out_duas)} duas total", file=sys.stderr)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"categories": out_categories, "duas": out_duas}, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote", OUT, file=sys.stderr)


if __name__ == "__main__":
    main()
