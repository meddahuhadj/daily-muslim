"""
routers/prayer.py — Heures de prière & Qibla (calcul côté serveur).
Repli exact de l'algorithme frontend (journal astronomique classique) pour que
le mobile puisse récupérer les horaires même sans le moteur JS actif.
Fuseau horaire : fourni par le client (`tz`, en heures, ex. 2 pour Paris en été)
car le serveur ne connaît pas le fuseau local de l'utilisateur.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Callable

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api", tags=["prayer"])

# Angles (ou minutes après le coucher du soleil pour isha) par méthode.
# Les 7 premières répliquent exactement PRAY_METHODS du frontend (index.html)
# pour que le repli serveur donne les mêmes horaires que l'application.
METHODS: dict[str, dict] = {
    "PARIS":        {"fajr": 12.0, "isha": 12.0},
    "MWL":          {"fajr": 18.0, "isha": 17.0},
    "ISNA":         {"fajr": 15.0, "isha": 15.0},
    "EGYPT":        {"fajr": 19.5, "isha": 17.5},
    "MAKKAH":       {"fajr": 18.5, "isha_min": 90},
    "KARACHI":      {"fajr": 18.0, "isha": 18.0},
    "JAFARI":       {"fajr": 16.0, "isha": 14.0, "maghrib": 4.0},
    "UMM_AL_QURA":  {"fajr": 18.5, "isha_min": 90},
    "JAKIM":        {"fajr": 20.0, "isha": 18.0},
    "QATAR":        {"fajr": 18.0, "isha_min": 90},
    "KUWAIT":       {"fajr": 18.0, "isha_min": 90},
    "MOONSIGHTING": {"fajr": 18.0, "isha": 18.0},
    "UOIF":         {"fajr": 12.0, "isha": 12.0},
    "TEHRAN":       {"fajr": 17.7, "isha": 14.0},
    "INDIA":        {"fajr": 17.0, "isha": 18.0},
}

PRAYER_NAMES = {
    "fajr": "Fajr", "sunrise": "Sunrise", "dhuhr": "Dhuhr",
    "asr": "Asr", "maghrib": "Maghrib", "isha": "Isha",
}


def _fix_hour(h: float) -> float:
    h %= 24
    return h if h >= 0 else h + 24


def _jd_from_ymd(y: int, m: int, d: int) -> float:
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    # -1524.5 : JD « civil » à minuit local (équivaut au frontend JS).
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def _sun_pos(jd: float) -> tuple[float, float]:
    """Déclinaison (rad) et équation du temps (heures)."""
    d = jd - 2451545.0
    g = 357.529 + 0.98560028 * d
    q = 280.459 + 0.98564736 * d
    l = q + 1.915 * math.sin(math.radians(g)) + 0.020 * math.sin(math.radians(2 * g))
    e = 23.439 - 0.00000036 * d
    ra = math.degrees(math.atan2(math.cos(math.radians(e)) * math.sin(math.radians(l)),
                                 math.cos(math.radians(l))))
    dec = math.asin(math.sin(math.radians(e)) * math.sin(math.radians(l)))
    eqt = q / 15 - _fix_hour(ra / 15)
    return dec, eqt


def prayer_times_for(
    d: date, lat: float, lng: float, method: str = "MWL",
    hanafi: bool = False, tz: float = 0.0,
) -> dict[str, float] | None:
    """Horaires pour `d` à (lat, lng) dans le fuseau `tz` (heures décimales).
    Retourne None si levé/couché du soleil impossible (jour polaire)."""
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return None
    if method not in METHODS:
        method = "MWL"
    meth = METHODS[method]

    dec, eqt = _sun_pos(_jd_from_ymd(d.year, d.month, d.day))
    noon_utc = 12 - eqt - lng / 15
    c_lat, s_lat = math.cos(math.radians(lat)), math.sin(math.radians(lat))
    c_dec, s_dec = math.cos(dec), math.sin(dec)

    def angle_time(angle: float, ccw: bool) -> float | None:
        c = (math.sin(math.radians(angle)) - s_dec * s_lat) / (c_dec * c_lat)
        if c > 1 or c < -1:
            return None
        t = (1 / 15) * math.degrees(math.acos(c))
        return noon_utc - t if ccw else noon_utc + t

    sunrise = angle_time(-0.833, True)
    sunset = angle_time(-0.833, False)
    if sunrise is None or sunset is None:
        return None
    night = sunset - sunrise

    fajr = angle_time(-meth["fajr"], True) or (sunrise - night / 2)
    if "isha_min" in meth:
        isha = sunset + meth["isha_min"] / 60
    else:
        isha = angle_time(-meth["isha"], False) or (sunset + night / 2)
    if "maghrib" in meth:
        maghrib = angle_time(-meth["maghrib"], False) or sunset
    else:
        maghrib = sunset
    asr_angle = math.degrees(
        math.atan(1 / ((2 if hanafi else 1) + math.tan(math.radians(abs(lat - math.degrees(dec)))))))
    asr = angle_time(asr_angle, False)

    t: Callable[[float], float] = lambda h: _fix_hour(h + tz)
    return {
        "fajr": t(fajr),
        "sunrise": t(sunrise),
        "dhuhr": t(noon_utc),
        "asr": t(asr) if asr is not None else None,
        "maghrib": t(maghrib),
        "isha": t(isha),
    }


@router.get("/prayer-times")
async def prayer_times(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    date_str: str = Query(..., alias="date"),
    method: str = Query("MWL"),
    hanafi: bool = Query(False),
    tz: float = Query(0.0, ge=-14, le=14),
):
    try:
        the_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(400, "Date invalide (ISO souhaitée: YYYY-MM-DD)")
    result = prayer_times_for(the_date, lat, lng, method, hanafi, tz)
    if result is None:
        raise HTTPException(422, "Horaires impossibles à ces coordonnées/jour")
    out = {"date": the_date.isoformat(), "method": method,
           "names": PRAYER_NAMES}
    out.update({k: round(v, 4) if v is not None else None
                for k, v in result.items()})
    return out


@router.get("/qibla")
async def qibla(lat: float = Query(..., ge=-90, le=90),
                lng: float = Query(..., ge=-180, le=180)):
    """Azimut de la Kaaba depuis (lat, lng) en degrés (0=N, 90=E)."""
    phi1, phi2 = math.radians(lat), math.radians(21.4225)
    d_lng = math.radians(39.8262 - lng)
    y = math.sin(d_lng) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lng)
    bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
    return {"lat": lat, "lng": lng, "bearing": round(bearing, 2),
            "kaaba": {"lat": 21.4225, "lng": 39.8262}}