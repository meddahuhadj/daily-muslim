"""Endpoints Daily Muslim : prières, Qibla, adhkar, assistant.

Le fournisseur IA de l'assistant est mocké pour les réponses (pipeline déterministe).
"""

import pytest
from pathlib import Path


@pytest.fixture
def no_key_client(monkeypatch):
    from fastapi.testclient import TestClient

    import main
    import translator

    monkeypatch.setattr(translator, "has_api_key", lambda: False)
    with TestClient(main.app) as client:
        yield client


def test_prayer_times_paris(app_client):
    r = app_client.get(
        "/api/prayer-times",
        params={"lat": 48.856, "lng": 2.352, "date": "2026-09-08",
                "method": "MWL", "tz": 2},
    )
    assert r.status_code == 200
    data = r.json()
    for key in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"):
        assert key in data
        if data[key] is not None:
            assert 0 <= data[key] < 24
    assert 12 <= data["dhuhr"] <= 14


def test_prayer_times_bad_date(app_client):
    r = app_client.get(
        "/api/prayer-times",
        params={"lat": 48.856, "lng": 2.352, "date": "2026-13-99"},
    )
    assert r.status_code == 400


def test_prayer_times_bad_coords(app_client):
    r = app_client.get(
        "/api/prayer-times",
        params={"lat": 99, "lng": 2.352, "date": "2026-09-08"},
    )
    assert r.status_code == 422


def test_prayer_times_solar_geometry(app_client):
    """Vérifie la géométrie solaire des horaires (précision Phase 7a).

    - Ordre strict des 6 temps (fajr < lever < dhuhr < asr < coucher < isha).
    - Dhuhr = midi solaire local = point milieu entre lever et coucher (±2 min).
    - Dhuhr cohérent avec l'équation de longitude/fuseau : 12 − lng/15 + tz
      (±12 min, independant de l'équation du temps).
    - Cas fontionnel équateur/équinoxe : jour ≈ 12 h (±20 min).
    """
    def fetch(lat, lng, tz):
        r = app_client.get(
            "/api/prayer-times",
            params={"lat": lat, "lng": lng, "date": "2026-09-08",
                    "method": "MWL", "tz": tz},
        )
        assert r.status_code == 200
        return r.json()

    d = fetch(48.856, 2.352, 2)
    names = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")
    for a, b in zip(names, names[1:]):
        assert d[a] is not None and d[b] is not None
        assert d[a] < d[b], f"{a} ({d[a]}) doit precede {b} ({d[b]})"

    # Dhuhr = point milieu lever/coucher (heure locale, déjà dans le fuseau).
    mid = (d["sunrise"] + d["maghrib"]) / 2
    assert abs(mid - d["dhuhr"]) * 60 <= 2.5

    # Midi solaire moyen (sans équation du temps) : 12 − lng/15 + tz (heures).
    noon = 12 - 2.352 / 15 + 2
    assert abs(d["dhuhr"] - noon) * 60 <= 12, \
        f"dhuhr {d['dhuhr']} vs midi géométrique {noon}"

    # Équateur / équinoxe : aube≈06:00, crépuscule≈18:00, jour ≈ 12 h.
    e = fetch(0, 0, 0)
    day = e["maghrib"] - e["sunrise"]
    assert abs(day - 12.0) * 60 <= 20, f"longueur du jour {day*60:.0f} min"
    assert 5.5 <= e["sunrise"] <= 6.75
    assert 17.25 <= e["maghrib"] <= 18.5
    assert abs(e["dhuhr"] - 12.0) * 60 <= 12

    # Fuseau : le même instant physique ne doit pas dépendre du tz transmis.
    d_same = fetch(48.856, 2.352, 3)
    assert abs((d_same["dhuhr"] - d["dhuhr"]) - 1.0) < 1e-6


def test_qibla_paris(app_client):
    r = app_client.get("/api/qibla", params={"lat": 48.856, "lng": 2.352})
    assert r.status_code == 200
    data = r.json()
    # Paris → Makkah ~119-120°.
    assert 115 <= data["bearing"] <= 125


def test_adhkar_list(app_client):
    r = app_client.get("/api/adhkar")
    assert r.status_code == 200
    cats = r.json()["categories"]
    assert {"morning", "evening", "post_prayer", "sleep", "wake",
            "travel", "protection", "gratitude"} <= set(cats)
    item = cats["morning"][0]
    assert item["ar"] and item["tr"] and item["tgt"] >= 1


def test_adhkar_category_not_found(app_client):
    r = app_client.get("/api/adhkar/nope")
    assert r.status_code == 404


def test_assistant_no_key_503(no_key_client):
    r = no_key_client.post("/api/assistant", json={"message": "Salam"})
    assert r.status_code == 503


def test_assistant_empty_message(app_client):
    r = app_client.post("/api/assistant", json={"message": "   "})
    assert r.status_code == 400


def test_assistant_with_key(app_client, monkeypatch):
    # Mocke la chaîne de fournisseurs : réponse déterministe.
    async def fake_chat(user_msg, history=None):
        return {"reply": "Réponse test", "provider": "mock"}

    from main import app
    import translator

    monkeypatch.setattr(translator, "chat_assistant", fake_chat)
    r = app_client.post("/api/assistant", json={
        "message": "Quand est la prière ?",
        "history": [{"role": "user", "content": "salut"}],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["reply"] == "Réponse test"
    assert data["provider"] == "mock"
    assert data["offline"] is False
    assert data["disclaimer"]


def test_assistant_all_providers_fail(app_client, monkeypatch):
    async def fake_chat(user_msg, history=None):
        return None

    import translator

    monkeypatch.setattr(translator, "chat_assistant", fake_chat)
    r = app_client.post("/api/assistant", json={"message": "test"})
    assert r.status_code == 503


def test_assistant_rate_limited(app_client, monkeypatch):
    async def fake_chat(user_msg, history=None):
        return {"reply": "ok", "provider": "mock"}

    from routers import assistant
    import translator

    monkeypatch.setattr(translator, "chat_assistant", fake_chat)
    assistant.assistant_limiter.reset()
    codes = []
    for _ in range(assistant._LIMIT_MAX + 3):
        r = app_client.post("/api/assistant", json={"message": "salam"})
        codes.append(r.status_code)
    assert codes.count(429) == 3
    assert codes[:assistant._LIMIT_MAX] == [200] * assistant._LIMIT_MAX


def test_cors_same_origin_echo(app_client):
    # Origine identique au Host -> header reflété.
    r = app_client.get("/api/languages", headers={"Origin": "http://testserver"})
    assert r.headers.get("access-control-allow-origin") == "http://testserver"


def test_cors_cross_origin_blocked(app_client):
    # Origine étrangère -> pas de header CORS (le navigateur refusera).
    r = app_client.get("/api/languages", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    # Et le pré-vol est refusé (204 sans autorisation CORS).
    r = app_client.options("/api/languages", headers={"Origin": "https://evil.example"})
    assert r.status_code == 204
    assert "access-control-allow-origin" not in r.headers


# ----------------------------- Géo / voyage ------------------------------- #


def test_travel_check_paris_london(app_client):
    r = app_client.get("/api/travel-check",
                       params={"homeLat": 48.856, "homeLng": 2.352,
                               "lat": 51.507, "lng": -0.128})
    assert r.status_code == 200
    data = r.json()
    assert data["is_traveling"] is True
    # Paris → Londres ≈ 342 km.
    assert 300 <= data["distance_km"] <= 390


def test_travel_check_close_home(app_client):
    r = app_client.get("/api/travel-check",
                       params={"homeLat": 48.856, "homeLng": 2.352,
                               "lat": 48.50, "lng": 2.30})
    assert r.status_code == 200
    data = r.json()
    assert data["is_traveling"] is False
    assert data["distance_km"] < 50


def test_geocode_mocked(app_client, monkeypatch):
    from routers import location

    def fake_fetch(url, headers):
        assert "nominatim.openstreetmap.org" in url
        return {"address": {"city": "Paris", "state": "Île-de-France",
                            "country": "France"}}

    monkeypatch.setattr(location, "_fetch_json", fake_fetch)
    window = app_client.get("/api/geocode", params={"lat": 48.856, "lng": 2.352})
    assert window.status_code == 200
    data = window.json()
    assert data == {"city": "Paris", "region": "Île-de-France", "country": "France"}


def test_geocode_fallback(app_client, monkeypatch):
    from routers import location

    def boom(url, headers):
        raise OSError("offline")

    monkeypatch.setattr(location, "_fetch_json", boom)
    r = app_client.get("/api/geocode", params={"lat": 0.0, "lng": 0.0})
    assert r.status_code == 200
    assert r.json() == {"city": "", "region": "", "country": ""}


def test_geocode_cached(app_client, monkeypatch):
    from routers import location

    location._CACHE.clear()
    calls = {"n": 0}

    def fake_fetch(url, headers):
        calls["n"] += 1
        return {"address": {"city": "Alger", "country": "Algérie"}}

    monkeypatch.setattr(location, "_fetch_json", fake_fetch)
    for _ in range(3):
        app_client.get("/api/geocode", params={"lat": 36.75, "lng": 3.06})
    assert calls["n"] == 1
    location._CACHE.clear()


# ----------------------------- Apprentissage ------------------------------ #


def test_learning_schema(app_client):
    r = app_client.get("/api/learning")
    assert r.status_code == 200
    mods = r.json()["modules"]
    ids = [m["id"] for m in mods]
    assert ids == ["quran_study", "tajwid", "arabic", "memorize", "hadith"]
    for m in mods:
        assert len(m["lessons"]) >= 1
        for lesson in m["lessons"]:
            # Chaque leçon est traduite dans les 4 langues de l'application.
            for lang in ("fr", "en", "nl", "ar"):
                assert lesson["t"].get(lang)
                assert lesson["b"].get(lang)
            assert "languages" in lesson
            assert set(lesson["languages"]) >= {"fr", "en", "nl", "ar"}


def test_learning_mirrors_frontend(app_client):
    r = app_client.get("/api/learning")
    server = {m["id"]: m["lessons"] for m in r.json()["modules"]}

    front_html = (
        Path(__file__).resolve().parent.parent.parent / "frontend" / "index.html"
    )
    if not front_html.exists():
        pytest.skip("frontend/index.html introuvable")
    html = front_html.read_text(encoding="utf-8")
    start = html.index("const LEARNING_MODULES = {")
    end = html.index("\nfunction learningRenderModule", start)
    js = html[start:end]

    import re

    # Extrait toutes les traductions fermées : {fr:"...",en:"...",nl:"...",ar:"..."}.
    # Les valeurs ne contiennent jamais de guillemet et peuvent être suivies
    # de sauts de ligne + indentation (grâce à \s* entre les clés).
    blocks = re.findall(
        r'\{(fr|en|nl|ar):"([^"]*)",\s*(en|fr|nl|ar):"([^"]*)",\s*'
        r'(en|fr|nl|ar):"([^"]*)",\s*(en|fr|nl|ar):"([^"]*)"\}',
        js, re.S)
    assert blocks, "aucun bloc de traduction extrait du frontend"
    expected_lessons = 4 * 2 * 2  # 4 modules × 2 leçons × (titre t + corps b)
    assert len(blocks) == expected_lessons, \
        f"{len(blocks)} blocs trouvés, attendu {expected_lessons}"

    merged = {}
    for a, va, b, vb, c, vc, dd, vd in blocks:
        merged = {a.strip(): va, b.strip(): vb, c.strip(): vc, dd.strip(): vd}
        for lang, val in merged.items():
            # Toutes les traductions du frontend existent sur le serveur.
            assert any(
                lesson["b"].get(lang) == val
                for m in server.values() for lesson in m
            ) or any(
                lesson["t"].get(lang) == val
                for m in server.values() for lesson in m
            ), f"traduction absente du serveur : {val[:40]}…"