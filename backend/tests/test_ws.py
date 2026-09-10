"""Flux WebSocket bout-en-bout (diffuseur -> serveur -> auditeur), Gemini mocké."""
import json


def _new_session(client, **body):
    d = client.post("/api/session", json=body or {}).json()
    return d["code"], d["broadcaster_token"]


def _drain(ws, wanted, tries=8):
    for _ in range(tries):
        m = json.loads(ws.receive_text())
        if m["type"] == wanted:
            return m
    raise AssertionError(f"message {wanted!r} non reçu")


def test_broadcast_requires_valid_token(app_client):
    code, _ = _new_session(app_client)
    try:
        with app_client.websocket_connect(f"/ws/broadcast/{code}?token=wrong") as ws:
            ws.receive_text()
        assert False, "token invalide accepté"
    except Exception:
        pass


def test_transcript_relayed_and_translated(app_client):
    code, tok = _new_session(app_client, target_langs=["fr"])
    with app_client.websocket_connect(f"/ws/broadcast/{code}?token={tok}") as b:
        _drain(b, "hello")
        with app_client.websocket_connect(f"/ws/listen/{code}?lang=fr") as l:
            _drain(l, "hello")
            b.send_text(json.dumps({"type": "transcript", "text": "مرحبا",
                                    "is_final": True, "manual": True}))
            p = _drain(l, "phrase")
            assert p["seq"] == 1
            assert p["text"].startswith("[fr]")
            assert p["degraded"] is False


def test_interim_pushed_without_translation(app_client):
    code, tok = _new_session(app_client, target_langs=["fr"])
    with app_client.websocket_connect(f"/ws/broadcast/{code}?token={tok}") as b:
        _drain(b, "hello")
        with app_client.websocket_connect(f"/ws/listen/{code}?lang=fr") as l:
            _drain(l, "hello")
            b.send_text(json.dumps({"type": "transcript", "text": "اختبار",
                                    "is_final": False}))
            m = _drain(l, "interim")
            assert m["arabic"] == "اختبار"


def test_quran_ref_backfilled_when_missing(app_client):
    code, tok = _new_session(app_client, target_langs=["fr"])
    with app_client.websocket_connect(f"/ws/broadcast/{code}?token={tok}") as b:
        _drain(b, "hello")
        with app_client.websocket_connect(f"/ws/listen/{code}?lang=fr") as l:
            _drain(l, "hello")
            # le mock renvoie is_quran=True, quran_ref=None pour ce texte
            b.send_text(json.dumps({"type": "transcript",
                                    "text": "قل هو الله احد",
                                    "is_final": True}))
            p = _drain(l, "phrase")
            assert p["is_quran"] is True
            assert p["quran_ref"] == "112:1"
            assert p["quran_ref_guessed"] is True


def test_resume_since_returns_only_missed(app_client):
    code, tok = _new_session(app_client, target_langs=["fr"])
    with app_client.websocket_connect(f"/ws/broadcast/{code}?token={tok}") as b:
        _drain(b, "hello")
        with app_client.websocket_connect(f"/ws/listen/{code}?lang=fr") as l:
            _drain(l, "hello")
            for txt in ("un", "deux", "trois"):
                b.send_text(json.dumps({"type": "transcript", "text": txt, "is_final": True}))
                _drain(l, "phrase")
        # reconnexion avec since=2 -> seule la phrase #3
        with app_client.websocket_connect(f"/ws/listen/{code}?lang=fr&since=2") as l2:
            hello = _drain(l2, "hello")
            assert hello["resumed"] is True
            assert [h["seq"] for h in hello["history"]] == [3]


def test_correction_rebroadcasts_with_flag(app_client):
    code, tok = _new_session(app_client, target_langs=["fr"])
    with app_client.websocket_connect(f"/ws/broadcast/{code}?token={tok}") as b:
        _drain(b, "hello")
        with app_client.websocket_connect(f"/ws/listen/{code}?lang=fr") as l:
            _drain(l, "hello")
            b.send_text(json.dumps({"type": "transcript", "text": "avant", "is_final": True}))
            p = _drain(l, "phrase")
            b.send_text(json.dumps({"type": "correct", "seq": p["seq"], "arabic": "apres"}))
            pc = _drain(l, "phrase")
            assert pc["seq"] == p["seq"]
            assert pc["corrected"] is True
            assert pc["arabic"] == "apres"


def test_listener_lang_change(app_client):
    code, tok = _new_session(app_client, target_langs=["fr", "en"])
    with app_client.websocket_connect(f"/ws/broadcast/{code}?token={tok}") as b:
        _drain(b, "hello")
        with app_client.websocket_connect(f"/ws/listen/{code}?lang=fr") as l:
            _drain(l, "hello")
            b.send_text(json.dumps({"type": "transcript", "text": "x", "is_final": True}))
            _drain(l, "phrase")
            l.send_text(json.dumps({"type": "set_lang", "lang": "en"}))
            lc = _drain(l, "lang_changed")
            assert lc["lang"] == "en"
            assert lc["history"][0]["text"].startswith("[en]")


def test_stats_pushed_to_broadcaster_on_listener_join(app_client):
    code, tok = _new_session(app_client)
    with app_client.websocket_connect(f"/ws/broadcast/{code}?token={tok}") as b:
        _drain(b, "hello")
        with app_client.websocket_connect(f"/ws/listen/{code}?lang=fr"):
            st = _drain(b, "stats")
            assert st["listeners"] == 1
            assert st["languages"].get("fr") == 1


def test_sliding_context_is_passed_to_translator(app_client):
    """Le 4e segment doit recevoir les 3 précédents comme contexte glissant,
    dans l'ordre, avec la traduction de la langue par défaut (fr)."""
    code, tok = _new_session(app_client, target_langs=["fr"])
    with app_client.websocket_connect(f"/ws/broadcast/{code}?token={tok}") as b:
        _drain(b, "hello")
        with app_client.websocket_connect(f"/ws/listen/{code}?lang=fr") as l:
            _drain(l, "hello")
            for txt in ("premier", "second", "troisieme", "quatrieme"):
                b.send_text(json.dumps({"type": "transcript", "text": txt, "is_final": True}))
                _drain(l, "phrase")
            assert len(app_client._fake.calls) == 4
            ctx = app_client._fake.calls[-1]["context"]
            assert [c["arabic"] for c in ctx] == ["premier", "second", "troisieme"]
            # traductions de référence = langue par défaut (fr), préfixées [fr]
            assert [c["translated"] for c in ctx] == ["[fr] premier", "[fr] second", "[fr] troisieme"]
            # le tout premier segment n'a pas de contexte
            assert app_client._fake.calls[0]["context"] == []
