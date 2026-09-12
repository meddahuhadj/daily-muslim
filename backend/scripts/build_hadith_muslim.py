"""Reconstruit backend/data/hadith_muslim.json depuis le dataset ouvert
fawazahmed0/hadith-api (arabe + traduction francaise, alignes hadith par hadith).

    python scripts/build_hadith_muslim.py

Source (CC0 / donnees ouvertes, aucune cle API requise) :
    https://github.com/fawazahmed0/hadith-api
Editions utilisees : ara-muslim (arabe complet, diacritise) et fra-muslim
(traduction francaise). Meme format de sortie que build_hadith_bukhari.py.
"""
import json
import os
import sys
import urllib.request

BASE = "https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions"
ARA_URL = f"{BASE}/ara-muslim.min.json"
FRA_URL = f"{BASE}/fra-muslim.min.json"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "hadith_muslim.json")


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


def main() -> None:
    print("Telechargement Sahih Muslim (arabe)...")
    ara = _get(ARA_URL)
    print("Telechargement Sahih Muslim (francais)...")
    fra = _get(FRA_URL)

    ara_h = ara["hadiths"]
    fra_h = fra["hadiths"]
    sections = ara["metadata"]["sections"]
    fra_by_num = {h["hadithnumber"]: h for h in fra_h}

    out, missing = [], 0
    for h in ara_h:
        num = h["hadithnumber"]
        fh = fra_by_num.get(num)
        book = h.get("reference", {}).get("book")
        rec = {
            "collection": "muslim",
            "text": h.get("text", ""),
            "ref": f"Sahih Muslim {num}",
            "book": book,
            "book_name": sections.get(str(book), "") if book is not None else "",
        }
        if fh and fh.get("text"):
            rec["translations"] = {"fr": fh["text"]}
        else:
            missing += 1
        out.append(rec)

    print(f"{len(out)} hadiths ({missing} sans traduction francaise)")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"hadiths": out}, f, ensure_ascii=False, separators=(",", ":"))
    print("Ecrit:", OUT)


if __name__ == "__main__":
    main()
