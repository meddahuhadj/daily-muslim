"""
routers/location.py — Géolocalisation inverse et contrôle du déplacement.

- GET /api/geocode   : géocodage inverse (coordonnées -> ville / région / pays)
                         via Nominatim (OpenStreetMap), mis en cache 24 h par
                         coordonnées arrondies (confidentialité + quota).
- GET /api/travel-check : distance à domicile (haversine) + statut « voyage ».
"""

from __future__ import annotations

import json
import logging
import math
import time
import urllib.parse
import urllib.request

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api", tags=["location"])

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_CACHE_TTL = 60 * 60 * 24
_LOG = logging.getLogger("uvicorn.error")


def _fetch_json(url: str, headers: dict[str, str]) -> dict:
    """Fonction réseau isolée (injectable dans les tests)."""
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _round_coords(lat: float, lng: float) -> tuple[float, float]:
    return (round(lat, 3), round(lng, 3))


_CACHE: dict[tuple[float, float], tuple[float, dict]] = {}


def reverse_geocode(lat: float, lng: float) -> dict:
    key = _round_coords(lat, lng)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    out = {"city": "", "region": "", "country": ""}
    try:
        query = urllib.parse.urlencode({
            "format": "jsonv2", "lat": lat, "lon": lng, "zoom": 10,
            "accept-language": "fr",
        })
        data = _fetch_json(_NOMINATIM_URL + "?" + query,
                           {"User-Agent": "DailyMuslimPWA/1.0 (contact: local)"})
        addr = data.get("address") or {}
        city = addr.get("city") or addr.get("town") or addr.get("village") \
            or addr.get("hamlet") or ""
        out = {
            "city": city or "",
            "region": addr.get("state") or "",
            "country": addr.get("country") or "",
        }
    except Exception as exc:  # défensif : jamais casser l'API
        _LOG.warning("geocode error: %r", exc)

    _CACHE[key] = (now, out)
    return out


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@router.get("/geocode")
def api_geocode(lat: float = Query(..., ge=-90, le=90),
                lng: float = Query(..., ge=-180, le=180)) -> dict:
    return reverse_geocode(lat, lng)


@router.get("/travel-check")
def api_travel_check(homeLat: float = Query(..., ge=-90, le=90),
                     homeLng: float = Query(..., ge=-180, le=180),
                     lat: float = Query(..., ge=-90, le=90),
                     lng: float = Query(..., ge=-180, le=180)) -> dict:
    distance = _haversine_km(homeLat, homeLng, lat, lng)
    return {"distance_km": round(distance, 1), "is_traveling": distance > 100}