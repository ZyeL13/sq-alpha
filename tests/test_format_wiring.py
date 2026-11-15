# tests/test_format_wiring.py — V3 Phase 2 conditional format wiring.
"""Format selection (deterministic, cap-aware), per-format daily
counts (persistent, reset-windowed), and prepare_post wiring
(one generation call, render fallback, queue round-trip).
No network, no publishing: LLM + renderer are mocked."""
import json
import time

import pytest


def _token(**overrides):
    token = {
        "symbol": "KITE",
        "price": 2.40,
        "price_change_percent": 2.0,
        "volume_24h": 3_000_000,
        "high_24h": 2.80,
        "low_24h": 2.10,
        "range_position": 0.5,
    }
    token.update(overrides)
    return token


# ------------------------------------------------------- format selection
def test_ordinary_token_is_short():
    from prompts.styles import select_post_format

    assert select_post_format(_token(), "HOT", {"anomaly": 0.2}, {}) == "short"


def test_strong_anomaly_is_longform():
    from prompts.styles import select_post_format

    assert select_post_format(_token(), "HOT", {"anomaly": 0.9}, {}) == "longform"


def test_longform_cap_falls_through_to_image():
    from prompts.styles import select_post_format

    counts = {"image": 0, "longform": 1}
    assert select_post_format(_token(), "HOT", {"anomaly": 0.9}, counts) == "image"


def test_both_caps_full_is_short():
    from prompts.styles import select_post_format

    counts = {"image": 3, "longform": 1}
    assert select_post_format(_token(), "HOT", {"anomaly": 0.9}, counts) == "short"


def test_big_move_is_image():
    from prompts.styles import select_post_format

    token = _token(price_change_percent=12.0)
    assert select_post_format(token, "GAINERS", {"anomaly": 0.2}, {}) == "image"


def test_image_cap_full_is_short():
    from prompts.styles import select_post_format

    token = _token(price_change_percent=12.0)
    assert select_post_format(token, "GAINERS", {"anomaly": 0.2},
                              {"image": 3, "longform": 0}) == "short"


def test_contrarian_tape_is_longform():
    from prompts.styles import select_post_format

    # Day story +6%, but -4.8% since the news landed: contradiction.
    token = _token(price=1.00, price_change_percent=6.0,
                   news_catalyst="Some headline.", price_at_news=1.05)
    assert select_post_format(token, "HOT", {"anomaly": 0.2}, {}) == "longform"


def test_catalyst_followthrough_is_longform():
    from prompts.styles import select_post_format

    # +6% since the news landed, same direction as the day: a story
    # with a second act (not the contrarian rule).
    token = _token(price=1.06, price_change_percent=8.0,
                   news_catalyst="Some headline.", price_at_news=1.00)
    assert select_post_format(token, "HOT", {"anomaly": 0.2}, {}) == "longform"


def test_volume_event_since_news_is_longform():
    from prompts.styles import select_post_format

    token = _token(volume_24h=20_000_000, price_change_percent=1.0,
                   news_catalyst="Some headline.",
                   price_at_news=2.40, volume_at_news=10_000_000)
    assert select_post_format(token, "HOT", {"anomaly": 0.2}, {}) == "longform"


def test_range_edge_with_move_is_longform():
    from prompts.styles import select_post_format

    token = _token(price=9.95, high_24h=10.0, low_24h=9.0,
                   price_change_percent=6.0)
    assert select_post_format(token, "GAINERS", {"anomaly": 0.2}, {}) == "longform"


def test_range_edge_without_move_is_image():
    from prompts.styles import select_post_format

    token = _token(price=9.95, high_24h=10.0, low_24h=9.0,
                   price_change_percent=2.0)
    assert select_post_format(token, "HOT", {"anomaly": 0.2}, {}) == "image"


def test_big_volume_day_is_image():
    from prompts.styles import select_post_format

    token = _token(volume_24h=60_000_000, price_change_percent=4.0)
    assert select_post_format(token, "HOT", {"anomaly": 0.2}, {}) == "image"


def test_counts_none_means_zero():
    from prompts.styles import select_post_format

    assert select_post_format(_token(), "HOT", {"anomaly": 0.9}, None) == "longform"


# --------------------------------------------------------- format counter
@pytest.fixture
def counter_file(tmp_path, monkeypatch):
    import storage.format_counter as fc

    monkeypatch.setattr(fc, "FORMAT_COUNTER_FILE", str(tmp_path / "format_counter.json"))
    return fc


def test_counter_starts_at_zero(counter_file):
    assert counter_file.get_format_counts() == {"image": 0, "longform": 0}


def test_counter_persists_across_reads(counter_file):
    counter_file.increment_format_count("image")
    counter_file.increment_format_count("image")
    counter_file.increment_format_count("longform")
    # Fresh read from the file: counts survived (file-backed).
    assert counter_file.get_format_counts() == {"image": 2, "longform": 1}


def test_counter_ignores_short_and_unknown(counter_file):
    counter_file.increment_format_count("short")
    counter_file.increment_format_count("bogus")
    assert counter_file.get_format_counts() == {"image": 0, "longform": 0}


def test_counter_resets_on_new_reset_window(counter_file, tmp_path, monkeypatch):
    import storage.format_counter as fc

    stale = {"reset_key": "2000-01-01_07:00", "image": 3, "longform": 1}
    with open(fc.FORMAT_COUNTER_FILE, "w") as f:
        json.dump(stale, f)
    assert counter_file.get_format_counts() == {"image": 0, "longform": 0}
    counter_file.increment_format_count("image")
    assert counter_file.get_format_counts() == {"image": 1, "longform": 0}


def test_counter_tolerates_corrupt_file(counter_file, monkeypatch):
    import storage.format_counter as fc

    with open(fc.FORMAT_COUNTER_FILE, "w") as f:
        f.write("{not json")
    assert counter_file.get_format_counts() == {"image": 0, "longform": 0}


# ------------------------------------------------------------- prepare_post
@pytest.fixture
def orch(monkeypatch):
    """Orchestrator with generation + rendering mocked, counts at zero."""
    import schedulers.orchestrator as orch

    calls = {"generate_post": [], "generate_longform": [], "render": []}

    def fake_post(token, category, scores):
        calls["generate_post"].append(token["symbol"])
        return f"${token['symbol']} short body that is long enough to pass."

    def fake_longform(token, category, scores):
        calls["generate_longform"].append(token["symbol"])
        return (f"{token['symbol']}: 24h Read", f"${token['symbol']} article body.")

    def fake_render(token):
        calls["render"].append(token["symbol"])
        return "/tmp/cards/KITE_1.png"

    monkeypatch.setattr(orch, "generate_post", fake_post)
    monkeypatch.setattr(orch, "generate_longform", fake_longform)
    monkeypatch.setattr(orch, "render_card", fake_render)
    monkeypatch.setattr(orch, "get_format_counts", lambda: {"image": 0, "longform": 0})
    return orch, calls


def test_prepare_post_short_calls_generate_once_no_render(orch):
    orch_mod, calls = orch

    result = orch_mod.prepare_post(_token(), "HOT", {"anomaly": 0.2})
    assert result is not None
    content, fmt, title, image_paths = result
    assert fmt == "short"
    assert title is None
    assert image_paths is None
    assert content.startswith("$KITE")
    assert calls["generate_post"] == ["KITE"]
    assert calls["generate_longform"] == []
    assert calls["render"] == []


def test_prepare_post_image_renders_card(orch):
    orch_mod, calls = orch

    token = _token(price_change_percent=12.0)
    result = orch_mod.prepare_post(token, "GAINERS", {"anomaly": 0.2})
    content, fmt, title, image_paths = result
    assert fmt == "image"
    assert title is None
    assert image_paths == ["/tmp/cards/KITE_1.png"]
    assert calls["generate_longform"] == []  # exactly one generation call
    assert calls["render"] == ["KITE"]


def test_prepare_post_image_render_failure_degrades_to_short(orch, monkeypatch):
    orch_mod, calls = orch
    from schedulers.card_renderer import CardRenderError

    def failing_render(token):
        raise CardRenderError("boom")

    monkeypatch.setattr(orch_mod, "render_card", failing_render)
    token = _token(price_change_percent=12.0)
    content, fmt, title, image_paths = orch_mod.prepare_post(token, "GAINERS", {"anomaly": 0.2})
    assert fmt == "short"
    assert image_paths is None
    assert content.startswith("$KITE")  # the post is never dropped


def test_prepare_post_longform_renders_cover_one_call(orch):
    orch_mod, calls = orch

    result = orch_mod.prepare_post(_token(), "HOT", {"anomaly": 0.9})
    content, fmt, title, image_paths = result
    assert fmt == "longform"
    assert title == "KITE: 24h Read"
    assert image_paths == ["/tmp/cards/KITE_1.png"]
    assert calls["generate_longform"] == ["KITE"]
    assert calls["generate_post"] == []  # no second LLM call
    assert calls["render"] == ["KITE"]


def test_prepare_post_longform_render_failure_keeps_article_coverless(orch, monkeypatch):
    orch_mod, calls = orch
    from schedulers.card_renderer import CardRenderError

    monkeypatch.setattr(orch_mod, "render_card",
                        lambda token: (_ for _ in ()).throw(CardRenderError("boom")))
    content, fmt, title, image_paths = orch_mod.prepare_post(_token(), "HOT", {"anomaly": 0.9})
    assert fmt == "longform"  # not truncated to short
    assert title == "KITE: 24h Read"
    assert image_paths is None
    assert content.startswith("$KITE")


def test_prepare_post_longform_failure_falls_back_to_short(orch, monkeypatch):
    orch_mod, calls = orch

    def failing_longform(token, category, scores):
        calls["generate_longform"].append(token["symbol"])
        return None

    monkeypatch.setattr(orch_mod, "generate_longform", failing_longform)
    content, fmt, title, image_paths = orch_mod.prepare_post(_token(), "HOT", {"anomaly": 0.9})
    assert fmt == "short"
    assert title is None
    assert image_paths is None
    assert calls["generate_longform"] == ["KITE"]
    assert calls["generate_post"] == ["KITE"]  # the one allowed fallback call
    assert calls["render"] == []


def test_prepare_post_generate_failure_returns_none(orch, monkeypatch):
    orch_mod, calls = orch

    monkeypatch.setattr(orch_mod, "generate_post", lambda t, c, s: None)
    assert orch_mod.prepare_post(_token(), "HOT", {"anomaly": 0.2}) is None


# ------------------------------------------------------- queue round-trip
def test_image_row_roundtrips_through_claim(tmp_path, orch):
    """prepare_post output -> add_post -> claim_due_post keeps fmt/paths."""
    from storage.scheduled_post_queue import ScheduledPostQueue

    orch_mod, _ = orch
    token = _token(price_change_percent=12.0)
    content, fmt, title, image_paths = orch_mod.prepare_post(token, "GAINERS", {"anomaly": 0.2})

    queue = ScheduledPostQueue(db_path=str(tmp_path / "q.db"))
    queue.add_post(post=content, category="GAINERS", symbol="KITE",
                   scheduled_time=time.time() - 1, hook="h", session="s",
                   provider="test", format=fmt, title=title,
                   image_paths=image_paths)
    row = queue.claim_due_post()
    assert row is not None
    (_id, post, cat, sym, hook, session, provider,
     row_fmt, row_title, row_paths) = row
    assert row_fmt == "image"
    assert row_paths == ["/tmp/cards/KITE_1.png"]
    assert post == content
