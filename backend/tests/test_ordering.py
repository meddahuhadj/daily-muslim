"""Le point critique : la diffusion doit rester dans l'ordre des `seq` même si
la traduction du segment N+1 revient avant celle de N."""
import asyncio
import json

import main


def _sess(client, **b):
    d = client.post("/api/session", json=b or {}).json()
    return d["code"], d["broadcaster_token"]


def _recv(ws, kind, tries=12):
    for _ in range(tries):
        m = json.loads(ws.receive_text())
        if m["type"] == kind:
            return m
    raise AssertionError(f"{kind} non reçu")


def test_out_of_order_translation_is_reordered(app_client, monkeypatch):
    """Segment 1 : traduction lente. Segment 2 : rapide. L'auditeur doit
    quand même recevoir seq 1 puis seq 2."""
    delays = {"un": 0.20, "deux": 0.0}

    async def slow_then_fast(arabic, langs, glossary="", *, context=None, use_cache=True):
        await asyncio.sleep(delays.get(arabic.strip(), 0.0))
        return {"arabic": arabic, "is_quran": False, "quran_ref": None,
                "is_hadith": False, "translations": {l: f"[{l}] {arabic}" for l in langs}}

    monkeypatch.setattr(main.translator, "translate_segment", slow_then_fast)

    code, tok = _sess(app_client, target_langs=["fr"])
    with app_client.websocket_connect(f"/ws/broadcast/{code}?token={tok}") as b:
        _recv(b, "hello")
        with app_client.websocket_connect(f"/ws/listen/{code}?lang=fr") as l:
            _recv(l, "hello")
            b.send_text(json.dumps({"type": "transcript", "text": "un", "is_final": True}))
            b.send_text(json.dumps({"type": "transcript", "text": "deux", "is_final": True}))
            p1 = _recv(l, "phrase")
            p2 = _recv(l, "phrase")
            assert p1["seq"] == 1 and "un" in p1["text"]
            assert p2["seq"] == 2 and "deux" in p2["text"]

    room = main.get_room(code)
    assert [h["seq"] for h in room.history] == [1, 2]


def test_backlog_drops_oldest(app_client):
    room = main.Room("QUEUE1")
    room._seg_q = asyncio.Queue(maxsize=3)
    room._worker = asyncio.get_event_loop().create_future()  # "en cours", ne draine jamais
    for i in range(10):
        room.submit_segment(text=f"s{i}")
    assert room._seg_q.qsize() == 3
    assert room.dropped_segments == 7
    room._worker.cancel()


def test_max_rooms_returns_503(app_client, monkeypatch):
    monkeypatch.setattr(main, "MAX_ROOMS", 2)
    main.ROOMS.clear()
    assert app_client.post("/api/session", json={}).status_code == 200
    assert app_client.post("/api/session", json={}).status_code == 200
    r = app_client.post("/api/session", json={})
    assert r.status_code == 503


def test_purge_stale_removes_idle_never_started(app_client, monkeypatch):
    main.ROOMS.clear()
    r = main.create_room()
    r.created_at -= main.IDLE_ROOM_TTL + 10   # « créée il y a longtemps », jamais démarrée
    assert main._purge_stale() == 1
    assert r.code not in main.ROOMS


def test_healthz_enriched(app_client):
    d = app_client.get("/healthz").json()
    for k in ("rooms_live", "listeners", "segments_total", "segments_dropped"):
        assert k in d
