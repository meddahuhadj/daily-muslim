"""Tests des routes publices du Coran (routers/quran.py + quran_index).

Verifie que la recherche, le verset unitaire, la liste des sourates et le
verset du jour fonctionnent sur le nouvel index normalise (refs/norm) sans
aucun appel reseau.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_search_known_word_returns_verses():
    r = client.get("/api/quran/search", params={"q": "الناس", "limit": 30})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] > 0
    hit = data["results"][0]
    assert 1 <= hit["surah"] <= 114
    assert hit["ayah"] >= 1
    assert hit["text"] and "الناس" in hit["text"]


def test_search_full_ikhlas_matches_112_1():
    r = client.get("/api/quran/search", params={"q": "قل هو الله أحد"})
    assert r.status_code == 200
    refs = [h["ref"] for h in r.json()["results"]]
    assert "الإخلاص:1" in refs


def test_search_empty_query_rejected():
    r = client.get("/api/quran/search", params={"q": ""})
    assert r.status_code == 422


def test_search_blank_query_returns_empty():
    r = client.get("/api/quran/search", params={"q": "  "})
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_verse_fatiha():
    r = client.get("/api/quran/verse", params={"surah": 1, "ayah": 1})
    assert r.status_code == 200
    data = r.json()
    assert data["ref"] == "الفاتحة:1"
    assert "بسم" in data["text"]


def test_verse_unknown_ayah_404():
    r = client.get("/api/quran/verse", params={"surah": 1, "ayah": 999})
    assert r.status_code == 404


def test_surahs_count_and_ayat():
    r = client.get("/api/quran/surahs")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 114
    by_index = {s["index"]: s for s in data["surahs"]}
    assert by_index[1]["ayat"] == 7
    assert by_index[2]["ayat"] == 286
    assert by_index[114]["ayat"] == 6


def test_verse_of_the_day():
    r = client.get("/api/quran/verse-of-the-day")
    assert r.status_code == 200
    data = r.json()
    assert 1 <= data["surah"] <= 114
    assert data["ayah"] >= 1
    assert data["text"]
    assert data["date"] == date.today().isoformat()