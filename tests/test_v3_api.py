# tests/test_v3_api.py — SQ-Alpha V3 Phase 1 (API integration)
"""Payload shapes per format, media-upload fallback, queue migration,
format-aware cleaning/gate, long-form generation. No network, no
publishing: requests.post/put and upload_image are mocked."""
import json
import sqlite3
import time

import pytest


# ---------------------------------------------------------------- clean
def test_clean_short_keeps_900_cap_and_strips():
    from schedulers.poster import clean_for_square

    long_text = "x" * 1500
    assert len(clean_for_square(long_text)) == 900
    assert clean_for_square("$BTC *bold* #tag — test") == "$BTC bold tag  test"


def test_clean_longform_uses_article_cap():
    from schedulers.poster import ArticleTooLongError, clean_for_square
    import config

    # Exactly at the cap passes through untouched.
    assert len(clean_for_square("x" * config.ARTICLE_MAX_CHARS,
                                format="longform")) == config.ARTICLE_MAX_CHARS
    # Over the cap is a loud refusal, never a silent cut (spec §6.6c).
    long_text = "x" * (config.ARTICLE_MAX_CHARS + 1)
    with pytest.raises(ArticleTooLongError) as excinfo:
        clean_for_square(long_text, format="longform")
    assert excinfo.value.length == config.ARTICLE_MAX_CHARS + 1
    # Short format on the same text still caps at 900 (unchanged path).
    assert len(clean_for_square(long_text)) == 900


# ------------------------------------------------------- poster helpers
class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"success": True, "data": {"shareLink": "https://sq.example/x"}}

    def json(self):
        return self._payload


@pytest.fixture
def poster_env(monkeypatch):
    """Poster with keys set, limit checks neutralised, no Telegram."""
    import schedulers.poster as poster

    monkeypatch.setattr(poster, "BINANCE_SQUARE_KEY", "test-key")
    monkeypatch.setattr(poster, "BINANCE_SQUARE_URL", "https://example.invalid/content/add")
    monkeypatch.setattr(poster, "TELEGRAM_BOT_TOKEN", None)
    monkeypatch.setattr(poster, "TELEGRAM_CHAT_ID", None)
    monkeypatch.setattr(poster, "can_post", lambda: True)
    monkeypatch.setattr(poster, "shutdown_if_limit_reached", lambda: None)
    monkeypatch.setattr(poster, "increment_post_counter", lambda: None)
    return poster


@pytest.fixture
def mock_http(monkeypatch):
    """Capture requests.post calls made by the poster; return success."""
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return _Resp(200)

    import schedulers.poster as poster

    monkeypatch.setattr(poster.requests, "post", fake_post)
    return calls


def test_post_to_square_short_payload_byte_identical(poster_env, mock_http):
    body = "$BTC volume is climbing while price holds near the highs today."
    assert poster_env.post_to_square(body) is True
    assert len(mock_http) == 1
    # Historical payload: exactly {"bodyTextOnly": ...}, no contentType.
    assert mock_http[0]["json"] == {"bodyTextOnly": body}


def test_post_to_square_image_payload(poster_env, mock_http, monkeypatch):
    monkeypatch.setattr(
        poster_env, "upload_image",
        lambda p: f"https://cdn.example/{p.split('/')[-1]}",
    )
    body = "$BTC chart shows a clean higher low forming under resistance today."
    assert poster_env.post_to_square(body, format="image", image_paths=["/tmp/a.png", "/tmp/b.png"]) is True
    payload = mock_http[0]["json"]
    assert payload["contentType"] == 1
    assert payload["bodyTextOnly"] == body
    assert payload["imageList"] == ["https://cdn.example/a.png", "https://cdn.example/b.png"]


def test_post_to_square_image_all_uploads_fail_falls_back_to_text(poster_env, mock_http, monkeypatch):
    monkeypatch.setattr(poster_env, "upload_image", lambda p: None)
    body = "$BTC chart shows a clean higher low forming under resistance today."
    assert poster_env.post_to_square(body, format="image", image_paths=["/tmp/a.png"]) is True
    # Text-only fallback payload, no imageList key at all.
    assert mock_http[0]["json"] == {"bodyTextOnly": body}


def test_post_to_square_longform_payload(poster_env, mock_http, monkeypatch):
    monkeypatch.setattr(
        poster_env, "upload_image", lambda p: "https://cdn.example/cover.png",
    )
    body = "$BTC " + ("analysis text. " * 200)
    assert poster_env.post_to_square(
        body, format="longform", title="BTC: 24h Read", image_paths=["/tmp/cover.png"],
    ) is True
    payload = mock_http[0]["json"]
    assert payload["contentType"] == 2
    assert payload["title"] == "BTC: 24h Read"
    assert payload["cover"] == "https://cdn.example/cover.png"
    assert payload["bodyTextOnly"].startswith("$BTC")


def test_post_to_square_longform_cover_failure_publishes_without_cover(
    poster_env, mock_http, monkeypatch
):
    monkeypatch.setattr(poster_env, "upload_image", lambda p: None)
    body = "$BTC " + ("analysis text. " * 200)
    assert poster_env.post_to_square(
        body, format="longform", title="BTC: 24h Read", image_paths=["/tmp/cover.png"],
    ) is True
    payload = mock_http[0]["json"]
    assert payload["contentType"] == 2
    assert "cover" not in payload


def test_post_to_square_longform_missing_title_refuses(poster_env, mock_http):
    body = "$BTC " + ("analysis text. " * 200)
    assert poster_env.post_to_square(body, format="longform", title=None) is False
    assert mock_http == []


def test_post_to_square_504_treated_as_success(poster_env, mock_http, monkeypatch):
    def fake_504(url, headers=None, json=None, timeout=None):
        mock_http.append({"url": url, "json": json})
        return _Resp(504, {})

    monkeypatch.setattr(poster_env.requests, "post", fake_504)
    assert poster_env.post_to_square("$BTC volume is climbing today, buyers active.") is True


def test_post_to_square_upload_limit_fails_without_shutdown(poster_env, mock_http, monkeypatch):
    def fake_limit(url, headers=None, json=None, timeout=None):
        mock_http.append({"url": url, "json": json})
        return _Resp(200, {"success": False, "code": "220014"})

    monkeypatch.setattr(poster_env.requests, "post", fake_limit)
    monkeypatch.setattr(poster_env, "upload_image", lambda p: "https://cdn.example/a.png")
    body = "$BTC chart shows a clean higher low forming under resistance today."
    assert poster_env.post_to_square(body, format="image", image_paths=["/tmp/a.png"]) is False


def test_post_to_targets_passes_format_through(poster_env, mock_http, monkeypatch):
    import schedulers.poster as poster

    monkeypatch.setattr(poster, "log_post", lambda **kw: None)
    body = "$BTC " + ("analysis text. " * 200)
    assert poster_env.post_to_targets(
        body, "HOT", symbol="BTC", format="longform", title="BTC: 24h Read",
    ) is True
    assert mock_http[0]["json"]["contentType"] == 2


# ------------------------------------------------------------- square_media
def test_upload_image_rejects_unknown_format_and_missing_file(monkeypatch):
    import schedulers.square_media as media

    monkeypatch.setattr(media, "BINANCE_SQUARE_KEY", "test-key")
    assert media.upload_image("/tmp/does-not-exist.png") is None
    assert media.upload_image("/tmp/file.bmp") is None


def test_upload_image_happy_path(monkeypatch, tmp_path):
    import schedulers.square_media as media

    monkeypatch.setattr(media, "BINANCE_SQUARE_KEY", "test-key")
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    calls = {"posts": [], "puts": []}

    class Resp:
        def __init__(self, status_code=200, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.ok = status_code < 400

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["posts"].append((url, json))
        if url.endswith("/image/presignedUrl"):
            return Resp(200, {"code": "000000", "data": {
                "presignedUrl": "https://s3.example/upload",
                "fileTicket": "ticket-1",
            }})
        return Resp(200, {"code": "000000", "data": {
            "status": 1, "imageUrl": "https://public.bnbstatic.com/img.png",
        }})

    def fake_put(url, headers=None, data=None, timeout=None):
        calls["puts"].append((url, headers))
        return Resp(200)

    monkeypatch.setattr(media.requests, "post", fake_post)
    monkeypatch.setattr(media.requests, "put", fake_put)
    monkeypatch.setattr(media.time, "sleep", lambda s: None)

    assert media.upload_image(str(img)) == "https://public.bnbstatic.com/img.png"
    assert calls["posts"][0][0].endswith("/image/presignedUrl")
    assert calls["posts"][0][1] == {"imageName": "chart.png"}
    assert calls["puts"][0][1] == {"Content-Type": "image/png"}


def test_upload_image_processing_failure_returns_none(monkeypatch, tmp_path):
    import schedulers.square_media as media

    monkeypatch.setattr(media, "BINANCE_SQUARE_KEY", "test-key")
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    class Resp:
        def __init__(self, payload=None):
            self.status_code = 200
            self._payload = payload or {}
            self.ok = True

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    def fake_post(url, headers=None, json=None, timeout=None):
        if url.endswith("/image/presignedUrl"):
            return Resp({"code": "000000", "data": {
                "presignedUrl": "https://s3.example/upload",
                "fileTicket": "ticket-1",
            }})
        return Resp({"code": "000000", "data": {
            "status": 2, "failedReason": "bad image",
        }})

    monkeypatch.setattr(media.requests, "post", fake_post)
    monkeypatch.setattr(media.requests, "put", lambda *a, **k: Resp())
    monkeypatch.setattr(media.time, "sleep", lambda s: None)

    assert media.upload_image(str(img)) is None


# ------------------------------------------------------------ queue migration
def test_queue_migrates_old_schema_and_roundtrips_v3_fields(tmp_path):
    from storage.scheduled_post_queue import ScheduledPostQueue

    db_path = str(tmp_path / "scheduled.db")
    # Old schema: no format/title/image_paths columns, one old row.
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE scheduled_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post TEXT NOT NULL, category TEXT NOT NULL, symbol TEXT NOT NULL,
            hook TEXT, session TEXT, provider TEXT,
            scheduled_time REAL NOT NULL,
            created_at REAL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "INSERT INTO scheduled_posts (post, category, symbol, scheduled_time) "
        "VALUES (?, ?, ?, ?)", ("$OLD old post", "HOT", "OLD", time.time() - 1),
    )
    conn.commit()
    conn.close()

    q = ScheduledPostQueue(db_path=db_path)
    cols = {row[1] for row in sqlite3.connect(db_path).execute("PRAGMA table_info(scheduled_posts)")}
    assert {"format", "title", "image_paths"} <= cols

    due = q.get_due_posts(limit=5)
    assert len(due) == 1
    # Indices 0-6 identical to the pre-V3 shape; new fields default.
    assert due[0][3] == "OLD"
    assert due[0][7] == "short"
    assert due[0][8] is None
    assert due[0][9] is None

    q.add_post(post="$NEW article body", category="ALPHA", symbol="NEW",
               scheduled_time=time.time() - 1, format="longform",
               title="NEW: 24h Read", image_paths=["/tmp/c.png"])
    due = q.get_due_posts(limit=5)
    new_row = [r for r in due if r[3] == "NEW"][0]
    assert new_row[7] == "longform"
    assert new_row[8] == "NEW: 24h Read"
    assert new_row[9] == ["/tmp/c.png"]


# ------------------------------------------------------------------- gate
def _article_body(symbol="$KITE", words=700):
    filler = ("the token is holding near the highs while volume stays "
              "elevated through the session. ")
    body = f"{symbol} volume is climbing while price holds near the highs. "
    body += "\nTHESIS\n\n" + filler * 12
    body += "\nWHAT HAPPENED\n\n" + filler * 6
    body += "\nWHY IT MATTERS\n\n" + filler * 6
    body += "\nBULL CASE\n\n1. buyers step in on every dip.\n2. volume confirms the move.\n\n" + filler * 6
    body += "\nBEAR CASE\n\n" + filler * 6
    body += "\nLIMITS AND INVALIDATION\n\n" + filler * 6
    body += "\nCONCLUSION\n\n" + filler * 6
    assert len(body) >= words
    return body


def test_validate_longform_allows_lists_that_short_gate_rejects():
    from generators.quality_gate import validate_longform, validate_post

    body = _article_body()
    valid, _ = validate_longform("KITE: 24h Read", body, symbol="KITE")
    assert valid is True
    # The same numbered list is planning notes for a short post.
    valid_short, reason = validate_post(body, symbol="KITE")
    assert valid_short is False
    assert "Reasoning leak" in reason


def test_validate_longform_rejects_missing_title_short_body_and_leak():
    from generators.quality_gate import validate_longform

    body = _article_body()
    assert validate_longform("", body, symbol="KITE")[0] is False
    assert validate_longform("T", "too short", symbol="KITE")[0] is False
    assert validate_longform("KITE: $KITE Read", body, symbol="KITE")[0] is False
    leak = body + "\n\nLet's draft: first line, word count check."
    assert validate_longform("KITE: 24h Read", leak, symbol="KITE")[0] is False


def test_build_longform_prompt_structure():
    from generators.post_generator import build_longform_prompt

    token = {"symbol": "KITE", "price": 0.0210, "price_change_percent": -48.8,
             "high_24h": 0.0470, "low_24h": 0.0190,
             "volume_24h": 8_500_000, "range_position": 0.55}
    prompt = build_longform_prompt(token, "GAINERS", {})
    for section in ("THESIS", "WHAT HAPPENED", "WHY IT MATTERS", "BULL CASE",
                    "BEAR CASE", "LIMITS AND INVALIDATION", "CONCLUSION"):
        assert section in prompt
    assert "550-750 words" in prompt
    assert "600-900 words" not in prompt
    assert "single JSON object" in prompt
    assert "RESEARCH PACK" in prompt
    assert "<post>" not in prompt
    assert "BEARISH" in prompt
    assert "$KITE" in prompt
    # The old prompt repeated the caution ~7x; the new prompt states
    # each caution string at most once (spec §8).
    lowered = prompt.lower()
    for phrase in ("never invent", "no fabricated certainty",
                   "state the limits"):
        assert lowered.count(phrase) <= 1, phrase


def _kite_article_json():
    """A minimal article JSON that passes every §6 gate for the KITE
    token above (price $0.0210, -48.8%, volume $8.5M, high $0.0470,
    low $0.0190, no catalyst). Numbers are cited only from the
    token dict; LIMITS names the pack's missing items verbatim."""
    return {
        "title": "KITE: 24h Read",
        "stance": "BEARISH",
        "thesis": (
            "$KITE collapsed 48.8% to $0.0210, a bearish session with "
            "sustained selling rather than a single print. The move erased "
            "nearly half the token's value in one day, leaving price pinned "
            "near the session low of $0.0190. Nothing in the tape suggests "
            "buyers stepped in at size, and the decline stands as the "
            "dominant fact for holders. The read is bearish until price "
            "reclaims higher ground with volume."),
        "what_happened": (
            "Price opened near $0.0470, the session high, then slid through "
            "the day to $0.0210, closing just above the $0.0190 low. Volume "
            "reached $8.5M across the session, heavy for a token of this "
            "size. The range spanned $0.0190 to $0.0470, and price now sits "
            "in the bottom tenth of that band. Each hourly close printed "
            "lower than the last through the afternoon, with no intraday "
            "bounce strong enough to hold. The tape shows steady "
            "distribution, not a flash crash."),
        "why_it_matters": (
            "A 48.8% loss in one session reprices the token for every "
            "holder, not just traders. Liquidity thins fast when a token "
            "halves, because market makers widen quotes and buyers wait for "
            "a floor that has not formed yet. The $8.5M volume shows the "
            "move had participation behind it, so this was a real transfer "
            "of ownership at lower prices rather than an empty quote "
            "drifting down. Holders who bought near $0.0470 now face a "
            "position worth less than half its morning value, which changes "
            "how the token trades next."),
        "bull_case": (
            "The bull case rests on the bounce from the low: price touched "
            "$0.0190 and held above it into the close, so sellers did not "
            "push through the session floor. Volume of $8.5M means the move "
            "was widely traded, and a widely traded low can mark a selling "
            "climax when buyers return. A recovery toward $0.0470 would "
            "need fresh demand, but the low itself gives bulls a clear line "
            "to defend."),
        "bear_case": (
            "The bear case is the tape itself: a 48.8% decline with price "
            "closing near $0.0190 shows sellers in control through the "
            "session. Volume of $8.5M confirms participation on the way "
            "down, and the absence of a bounce leaves no evidence of demand "
            "stepping in. The token now trades at $0.0210, closer to its low "
            "than its high, and every rally attempt during the day faded. "
            "This describes damage to date, not a forecast."),
        "limits": (
            "The read is bounded by what the pack does not contain. No news "
            "catalyst was identified in the feeds, so the trigger for the "
            "selling is unnamed. The pack also lacks >24h price history, "
            "funding rates and open interest, holder flows, and market cap "
            "at move time, so the move cannot be placed in a longer trend. "
            "The read fails if price reclaims $0.0470 on volume above "
            "$8.5M, which would show buyers absorbing supply."),
        "conclusion": (
            "The stance stays bearish: $KITE lost 48.8% to $0.0210 on $8.5M "
            "of volume, with price pinned near the $0.0190 low and no "
            "catalyst to explain the selling. Watch whether price reclaims "
            "$0.0470; until it does, the tape favors sellers."),
        "headline": "KITE COLLAPSES 48.8% AND HOLDS NEAR LOW",
        "deck": ("Price halved in a day on heavy volume, with sellers in "
                 "control into the close."),
    }


def test_generate_longform_splits_title_and_uses_longform_budget(monkeypatch):
    import json

    import generators.post_generator as pg

    token = {"symbol": "KITE", "price": 0.0210, "price_change_percent": -48.8,
             "high_24h": 0.0470, "low_24h": 0.0190,
             "volume_24h": 8_500_000, "range_position": 0.55}
    seen = {}

    def fake_generate(prompt, system_prompt=None, category=None,
                      max_tokens=None, **kw):
        seen["max_tokens"] = max_tokens
        seen["output_format"] = kw.get("output_format")
        seen["system_prompt"] = system_prompt
        return json.dumps(_kite_article_json())

    monkeypatch.setattr(pg, "generate", fake_generate)
    monkeypatch.setattr(pg, "is_similar_to_recent", lambda c: False)
    monkeypatch.setattr(pg, "add_to_recent", lambda c: None)
    monkeypatch.setattr(pg.llm, "last_call_meta",
                        {"provider": "test", "model": "test-model",
                         "finish_reason": "stop"})

    result = pg.generate_longform(token, "GAINERS", {})
    assert result is not None
    title, out_body = result
    assert title == "KITE: 24h Read"
    assert out_body.startswith("THESIS")
    assert out_body.count("$KITE") == 1
    assert "WHAT HAPPENED" in out_body
    assert "CONCLUSION" in out_body
    assert seen["max_tokens"] == 3500
    assert seen["output_format"] == "json"
    from prompts.rebate import REBATE_SYSTEM_CORE
    assert seen["system_prompt"] is REBATE_SYSTEM_CORE
    # The validated article JSON + research pack are stashed for the
    # banner (worker B reads LAST_DRAFT_META["article"]).
    assert pg.LAST_DRAFT_META["article"]["stance"] == "BEARISH"
    assert pg.LAST_DRAFT_META["research_pack"]["stance"] == "BEARISH"


def test_generate_longform_retries_once_then_skips(monkeypatch):
    import json

    import generators.post_generator as pg

    token = {"symbol": "KITE", "price": 0.0210, "price_change_percent": -48.8,
             "high_24h": 0.0470, "low_24h": 0.0190,
             "volume_24h": 8_500_000, "range_position": 0.55}
    calls = {"n": 0}

    def fake_generate(prompt, system_prompt=None, category=None,
                      max_tokens=None, **kw):
        calls["n"] += 1
        # Missing keys every time: gate 6b fails on both attempts.
        return json.dumps({"title": "KITE: 24h Read"})

    monkeypatch.setattr(pg, "generate", fake_generate)
    monkeypatch.setattr(pg.llm, "last_call_meta",
                        {"provider": "test", "model": "test-model",
                         "finish_reason": "stop"})

    assert pg.generate_longform(token, "GAINERS", {}) is None
    assert calls["n"] == 2


# ------------------------------------------------------------------ config
def test_v3_config_constants():
    import config

    assert config.LONGFORM_MAX_PER_DAY == 1
    assert config.IMAGE_MAX_PER_DAY == 3
    assert config.V3_IMAGE_PROVIDER == "local"
    assert config.ARTICLE_MAX_CHARS == 6000
    assert config.LONGFORM_MAX_TOKENS == 3500


def test_log_post_records_format(tmp_path, monkeypatch):
    import utils.performance_logger as pl

    monkeypatch.setattr(pl, "LOG_PATH", tmp_path / "post_performance.jsonl")
    pl.log_post(symbol="BTC", category="HOT", hook="h", angle="a",
                session="asia", post_content="$BTC test post content",
                format="longform")
    entry = json.loads((tmp_path / "post_performance.jsonl").read_text().splitlines()[0])
    assert entry["format"] == "longform"
