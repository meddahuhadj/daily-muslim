"""Tests du moteur de prière — ancrés sur une référence externe (aladhan.com).

Les valeurs attendues sont les timings de aladhan.com (/v1/timings,
méthode 3 = MWL, école 0 = Shafi, date 2026-09-09), une implémentation
indépendante de l'algorithme PrayTimes classique. Elles ne sont pas
recalculées au test : toute édition de `routers/prayer.py` est vérifiée ici.

Tolérance : ± 3 min (arrondi à la minute côté aladhan).
"""

from datetime import date
from math import isclose

import pytest

from routers.prayer import prayer_times_for

# (ville, lat, lng, tz, méthode, {horaire: "HH:MM"}) — source : api.aladhan.com,
# 2026-09-09. Méthodes : MWL=3, UOIF=12, école 0 (Shafi).
REFERENCE_ALADHAN = [
    ("Paris", 48.856, 2.352, 2, "MWL", {
        "fajr": "05:27", "sunrise": "07:19", "dhuhr": "13:48",
        "asr": "17:24", "maghrib": "20:16", "isha": "22:01",
    }),
    ("Makkah", 21.4225, 39.8262, 3, "MWL", {
        "fajr": "04:51", "sunrise": "06:06", "dhuhr": "12:18",
        "asr": "15:44", "maghrib": "18:30", "isha": "19:40",
    }),
    ("Cairo", 30.0444, 31.2357, 3, "MWL", {
        "fajr": "05:15", "sunrise": "06:36", "dhuhr": "12:52",
        "asr": "16:25", "maghrib": "19:08", "isha": "20:24",
    }),
    ("Los Angeles", 34.0522, -118.2437, -7, "MWL", {
        "fajr": "05:07", "sunrise": "06:32", "dhuhr": "12:50",
        "asr": "16:25", "maghrib": "19:08", "isha": "20:28",
    }),
    ("Nairobi", -1.2921, 36.8219, 3, "MWL", {
        "fajr": "05:18", "sunrise": "06:27", "dhuhr": "12:30",
        "asr": "15:40", "maghrib": "18:33", "isha": "19:38",
    }),
    ("Paris (UOIF)", 48.856, 2.352, 2, "UOIF", {
        "fajr": "06:08", "sunrise": "07:19", "dhuhr": "13:48",
        "asr": "17:24", "maghrib": "20:16", "isha": "21:27",
    }),
]

PRAYER_KEYS = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")
DAY = date(2026, 9, 9)
TOL_H = 3 / 60  # ±3 minutes


def _to_hours(hhmm: str) -> float:
    h, m = map(int, hhmm.split(":"))
    return h + m / 60


@pytest.mark.parametrize("city,lat,lng,tz,method,expected", REFERENCE_ALADHAN)
def test_paris_mwl_matches_aladhan(city, lat, lng, tz, method, expected):
    got = prayer_times_for(DAY, lat, lng, method, hanafi=False, tz=tz)
    assert got is not None
    for key in PRAYER_KEYS:
        assert isclose(got[key], _to_hours(expected[key]), abs_tol=TOL_H), (
            f"{city} {key}: {got[key]:.4f}h vs aladhan {expected[key]}"
        )


def test_jafari_maghrib_after_sunset_and_ordered():
    """Jafari (angle maghrib 4°) : maghrib après sunset, et ordre fajr < ... < isha."""
    got = prayer_times_for(DAY, 48.856, 2.352, "JAFARI", tz=2)
    assert got is not None
    assert got["maghrib"] > got["sunrise"] + 12  # maghrib après l'horizontale midday
    for a, b in zip(PRAYER_KEYS, PRAYER_KEYS[1:]):
        assert got[a] < got[b], f"{a} ({got[a]:.4f}) >= {b} ({got[b]:.4f})"


def test_hanafi_asr_later_than_shafi():
    """Le calcul Hanafi (ombre × 2) retarde Asr par rapport à Shafi (× 1)."""
    shafi = prayer_times_for(DAY, 48.856, 2.352, "MWL", hanafi=False, tz=2)
    hanafi = prayer_times_for(DAY, 48.856, 2.352, "MWL", hanafi=True, tz=2)
    assert hanafi["asr"] > shafi["asr"] + 15 / 60


def test_unknown_method_falls_back_to_mwl():
    got = prayer_times_for(DAY, 48.856, 2.352, "INEXISTANT", tz=2)
    ref = prayer_times_for(DAY, 48.856, 2.352, "MWL", tz=2)
    assert got == ref


def test_polar_day_returns_none():
    # Svalbard en juin : soleil de minuit → lever/coucher impossibles.
    assert prayer_times_for(date(2026, 6, 21), 78.22, 15.65, "MWL", tz=2) is None


def test_sunrise_and_sunset_symmetric_around_noon():
    """Sunrise/maghrib (sunset pour MWL) encadrent le midi solaire de ~symétrique."""
    got = prayer_times_for(DAY, 48.856, 2.352, "MWL", tz=2)
    before = got["dhuhr"] - got["sunrise"]
    after = got["maghrib"] - got["dhuhr"]
    # Symétrie à ±2 min près (l'équation du temps varie légèrement dans la journée).
    assert abs(before - after) < 2 / 60