import main
from main import Room


def test_code_generation_unambiguous():
    code = main._gen_code()
    assert len(code) == 6
    assert not (set(code) & set("O0I1"))


def test_active_target_langs_from_listeners_and_defaults():
    r = Room("ABC123")
    r.default_langs = ["fr"]
    r.listeners = {"en": {object()}, "ar": {object()}, "nl": set()}
    langs = r.active_target_langs()
    assert "ar" not in langs           # l'original n'est jamais une cible
    assert set(langs) == {"fr", "en"}  # nl vide ignoré


def test_history_since_returns_only_missed():
    r = Room("ABC123")
    for i in range(1, 6):
        r.history.append({
            "seq": i, "ts": i, "arabic": f"a{i}", "translations": {"fr": f"t{i}"},
            "is_quran": False, "quran_ref": None,
        })
    missed = r.history_since("fr", 3)
    assert [p["seq"] for p in missed] == [4, 5]
    assert r.history_since("fr", 10) == []


def test_find_record():
    r = Room("ABC123")
    r.history.append({"seq": 7, "ts": 1, "arabic": "x", "translations": {},
                      "is_quran": False, "quran_ref": None})
    assert r.find_record(7)["arabic"] == "x"
    assert r.find_record(99) is None


def test_phrase_payload_projects_language():
    rec = {
        "seq": 1, "ts": 1, "arabic": "نص عربي",
        "translations": {"fr": "texte", "en": "text"},
        "is_quran": True, "quran_ref": "2:255", "is_hadith": False,
    }
    assert main._phrase_payload(rec, "fr")["text"] == "texte"
    assert main._phrase_payload(rec, "ar")["text"] == "نص عربي"
    assert main._phrase_payload(rec, "de")["text"] == ""   # langue absente
    assert main._phrase_payload(rec, "fr")["quran_ref"] == "2:255"


def test_fill_quran_ref_only_when_missing():
    rec = {"is_quran": True, "quran_ref": None, "arabic": "قُلْ هُوَ اللَّهُ أَحَدٌ"}
    main._fill_quran_ref(rec)
    assert rec["quran_ref"] == "112:1"
    assert rec["quran_ref_guessed"] is True

    kept = {"is_quran": True, "quran_ref": "S. 112", "arabic": "قل هو الله احد"}
    main._fill_quran_ref(kept)
    assert kept["quran_ref"] == "S. 112"
    assert "quran_ref_guessed" not in kept

    not_q = {"is_quran": False, "quran_ref": None, "arabic": "قل هو الله احد"}
    main._fill_quran_ref(not_q)
    assert not_q["quran_ref"] is None


def _rec(seq, ar, **tr):
    return {"seq": seq, "ts": seq, "arabic": ar, "translations": tr,
            "is_quran": False, "quran_ref": None}


def test_sliding_context_returns_last_segments_in_preferred_lang():
    r = Room("ABC123")
    r.default_langs = ["fr", "en"]
    for i in range(1, 6):
        r.history.append(_rec(i, f"ar{i}", fr=f"fr{i}", en=f"en{i}"))
    ctx = main._sliding_context(r)
    assert [c["arabic"] for c in ctx] == ["ar3", "ar4", "ar5"]     # borné à 3
    assert [c["translated"] for c in ctx] == ["fr3", "fr4", "fr5"]  # langue par défaut
    # un limit supérieur à la taille de l'historique ne crée pas d'entrées
    assert [c["arabic"] for c in main._sliding_context(r, limit=10)] == \
        ["ar1", "ar2", "ar3", "ar4", "ar5"]


def test_sliding_context_before_seq_excludes_corrected_phrase():
    r = Room("ABC123")
    r.default_langs = ["fr"]
    for i in range(1, 5):
        r.history.append(_rec(i, f"ar{i}", fr=f"fr{i}"))
    # correction de la phrase 3 : le contexte est antérieur à 3
    ctx = main._sliding_context(r, before_seq=3)
    assert [c["arabic"] for c in ctx] == ["ar1", "ar2"]
    assert main._sliding_context(r, before_seq=1) == []


def test_sliding_context_falls_back_to_any_translation():
    r = Room("ABC123")
    r.default_langs = []                       # aucune langue par défaut -> repli "fr"
    r.history.append(_rec(1, "ar1", en="only-en"))
    r.history.append(_rec(2, "ar2", es="only-es"))   # ni fr ni en : repli sur es
    ctx = main._sliding_context(r)
    assert ctx == [{"arabic": "ar1", "translated": "only-en"},
                   {"arabic": "ar2", "translated": "only-es"}]
