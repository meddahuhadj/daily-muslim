"""
routers/quran.py - Recherche et navigation dans le Coran.

Exposes:
  GET /api/quran/search?q=...      -> liste des versets contenant le terme
  GET /api/quran/verse            -> texte arabe d'un verset (depuis l'index local)
  GET /api/quran/surahs           -> liste des 114 sourates (nom, #versets)
  GET /api/quran/verse-of-the-day -> un verset aleatoire (fixe jusqu'a Fajr)

Aucun appel reseau : tout est lu dans backend/data/quran_index.json
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

import quran_index

router = APIRouter(prefix="/api", tags=["quran"])

SURAH_AR = ["الفاتحة", "البقرة", "آل عمران", "النساء", "المائدة", "الأنعام", "الأعراف", "الأنفال", "التوبة", "يونس", "هود", "يوسف", "الرعد", "إبراهيم", "الحجر", "النحل", "الإسراء", "الكهف", "مريم", "طه", "الأنبياء", "الحج", "المؤمنون", "النور", "الفرقان", "الشعراء", "النمل", "القصص", "العنكبوت", "الروم", "لقمان", "السجدة", "الأحزاب", "سبأ", "فاطر", "يس", "الصافات", "ص", "الزمر", "غافر", "فصلت", "الشورى", "الزخرف", "الدخان", "الجاثية", "الأحقاف", "محمد", "الفتح", "الحجرات", "ق", "الذاريات", "الطور", "النجم", "القمر", "الرحمن", "الواقعة", "الحديد", "المجادلة", "الحشر", "الممتحنة", "الصف", "الجمعة", "المنافقون", "التغابن", "الطلاق", "التحريم", "الملك", "القلم", "الحاقة", "المعارج", "نوح", "الجن", "المزمل", "المدثر", "القيامة", "الإنسان", "المرسلات", "النبأ", "النازعات", "عبس", "التكوير", "الانفطار", "المطففين", "الانشقاق", "البروج", "الطارق", "الأعلى", "الغاشية", "الفجر", "البلد", "الشمس", "الليل", "الضحى", "الشرح", "التين", "العلق", "القدر", "البينة", "الزلزلة", "العاديات", "القارعة", "التكاثر", "العصر", "الهمزة", "الفيل", "قريش", "الماعون", "الكوثر", "الكافرون", "النصر", "المسد", "الإخلاص", "الفلق", "الناس"]

def _surah_name(idx: int) -> str:
    if 1 <= idx <= len(SURAH_AR):
        return SURAH_AR[idx - 1]
    return str(idx)


@router.get("/quran/search")
async def search_quran(
    q: str = Query(..., min_length=1, description="Terme de recherche"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Recherche un terme dans le texte arabe normalise du Coran."""
    if not quran_index.available():
        raise HTTPException(status_code=503, detail="Quran index not available")

    results = []
    for ref, text in quran_index.search(q, limit):
        s, a = ref.split(":")
        surah = int(s)
        ayah = int(a)
        results.append({
            "surah": surah,
            "surah_name": _surah_name(surah),
            "ayah": ayah,
            "text": text,
            "ref": f"{_surah_name(surah)}:{ayah}",
        })

    return {"query": q, "results": results, "count": len(results)}


@router.get("/quran/verse")
async def get_verse(
    surah: int = Query(..., ge=1, le=114),
    ayah: int = Query(..., ge=1),
) -> dict[str, Any]:
    """Retourne le texte arabe d'un verset specifique (index local normalise)."""
    if not quran_index.available():
        raise HTTPException(status_code=503, detail="Quran index not available")
    text = quran_index.get(f"{surah}:{ayah}")
    if text is None:
        raise HTTPException(status_code=404, detail="Verse not found")
    return {
        "surah": surah,
        "surah_name": _surah_name(surah),
        "ayah": ayah,
        "text": text,
        "ref": f"{_surah_name(surah)}:{ayah}",
    }


@router.get("/quran/surahs")
async def list_surahs() -> dict[str, Any]:
    """Liste des 114 sourates avec leur nombre de versets."""
    counts = quran_index.count_ayat()

    surahs = []
    for i in range(1, len(SURAH_AR) + 1):
        surahs.append({
            "index": i,
            "name": SURAH_AR[i - 1],
            "ayat": counts.get(i, 0),
        })

    return {"surahs": surahs, "count": len(surahs)}


@router.get("/quran/verse-of-the-day")
async def verse_of_the_day() -> dict[str, Any]:
    """Verset du jour, fixe jusqu'a la prochaine Fajr (minuit + 1h)."""
    if not quran_index.available():
        raise HTTPException(status_code=503, detail="Quran index not available")
    now = datetime.now()
    today = now.date()
    seed = today.toordinal()

    verses = quran_index.iter_verses()
    if not verses:
        raise HTTPException(status_code=503, detail="Quran index not available")

    rng = random.Random(seed)
    ref, text = rng.choice(verses)
    s, a = ref.split(":")
    surah = int(s)
    ayah = int(a)
    return {
        "surah": surah,
        "surah_name": _surah_name(surah),
        "ayah": ayah,
        "text": text,
        "ref": f"{_surah_name(surah)}:{ayah}",
        "date": today.isoformat(),
    }
