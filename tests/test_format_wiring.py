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
def orch(monkeypatch, tmp_path):
    """Orchestrator with generation + rendering + snapshot mocked, counts at zero."""
    import schedulers.orchestrator as orch
    import prompts.styles as styles
    from schedulers.snapshot import CardSnapshot

    # Card-type angle mapping reads the persistent deck state: isolate it.
    monkeypatch.setattr(styles, "ANGLE_STATE_FILE", str(tmp_path / "angles.json"))
    styles.reset_opening_deck()

    calls = {"generate_post": [], "generate_longform": [], "render": [],
             "snapshots": [], "gen_tokens": [], "angles": [],
             "closing": [], "card_types": [], "questions": []}
    snapshot = CardSnapshot(token=_token(), closes=[2.0] * 24,
                            volume_7d_avg=1_000_000, btc_change=2.0)

    def fake_post(token, category, scores, opening_angle=None,
                  closing_question=False, reaction=None, memory=None,
                  **kwargs):
        calls["generate_post"].append(token["symbol"])
        calls["gen_tokens"].append(dict(token))
        calls["angles"].append(opening_angle)
        calls["closing"].append(closing_question)
        calls["reactions"] = calls.get("reactions", []) + [reaction]
        # Step 1: generate_post returns the JSON dict; prepare_draft
        # unwraps the "post" field.
        return {
            "event": f"{token['symbol']} moved",
            "fact": "numbers from the token",
            "interpretation": "the tape is telling",
            "angle": (opening_angle[0] if opening_angle else "smug"),
            "post": (f"${token['symbol']} short body that is long enough "
                     f"to pass. Does the tape stay this loud?"),
        }

    def fake_longform(token, category, scores):
        calls["generate_longform"].append(token["symbol"])
        return (f"{token['symbol']}: 24h Read", f"${token['symbol']} article body.")

    def fake_render(token, snapshot=None, card_type=None, question=None,
                    **kwargs):
        calls["render"].append(token["symbol"])
        calls["snapshots"].append(snapshot)
        calls["card_types"].append(card_type)
        calls["questions"].append(question)
        return "/tmp/cards/KITE_1.png"

    def fake_snapshot(token):
        return snapshot

    monkeypatch.setattr(orch, "generate_post", fake_post)
    monkeypatch.setattr(orch, "generate_longform", fake_longform)
    monkeypatch.setattr(orch, "render_card", fake_render)
    monkeypatch.setattr(orch, "build_snapshot", fake_snapshot)
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


def test_prepare_post_image_passes_snapshot_and_enriched_token(orch):
    orch_mod, calls = orch

    token = _token(price_change_percent=12.0)
    content, fmt, title, image_paths = orch_mod.prepare_post(token, "GAINERS", {"anomaly": 0.2})
    assert fmt == "image"
    assert calls["snapshots"] != [None]  # the render got the snapshot
    assert calls["snapshots"][0].volume_7d_avg == 1_000_000
    gen_token = calls["gen_tokens"][0]
    assert gen_token["volume_7d_avg"] == 1_000_000
    assert gen_token["volume_ratio_7d"] == pytest.approx(3.0)  # 3M / 1M
    assert gen_token["btc_change_24h"] == 2.0
    assert "volume_7d_avg" not in token  # the caller's token is untouched


def test_prepare_post_image_missing_snapshot_degrades_to_short(orch, monkeypatch):
    orch_mod, calls = orch

    monkeypatch.setattr(orch_mod, "build_snapshot", lambda token: None)
    token = _token(price_change_percent=12.0)
    content, fmt, title, image_paths = orch_mod.prepare_post(token, "GAINERS", {"anomaly": 0.2})
    assert fmt == "short"  # slot not consumed: counts increment on final fmt
    assert image_paths is None
    assert calls["render"] == []
    assert content.startswith("$KITE")  # the post is never dropped


def test_prepare_post_image_uses_mapped_angle_and_question(orch):
    orch_mod, calls = orch

    token = _token(price_change_percent=12.0)
    content, fmt, title, image_paths = orch_mod.prepare_post(token, "GAINERS", {"anomaly": 0.2})
    assert fmt == "image"
    # Volume ratio 3.0 -> volume_spike -> participation/contrast angle.
    angle_name, _ = calls["angles"][0]
    assert angle_name in ("participation", "contrast")
    assert calls["closing"] == [True]
    assert calls["card_types"] == ["volume_spike"]
    assert calls["questions"] == ["Does the tape stay this loud?"]
    assert calls["generate_post"] == ["KITE"]  # exactly one generation call


def test_prepare_post_short_uses_no_mapped_angle(orch):
    orch_mod, calls = orch

    orch_mod.prepare_post(_token(), "HOT", {"anomaly": 0.2})
    assert calls["angles"] == [None]
    assert calls["closing"] == [False]


def test_prepare_post_no_card_type_degrades_to_short(orch, monkeypatch):
    orch_mod, calls = orch
    from schedulers.snapshot import CardSnapshot

    # Big move (image format) but ordinary snapshot signals: ratio
    # 1.0, wide range, no BTC lag -> no card type matches.
    flat = CardSnapshot(token=_token(), closes=[2.0] * 24,
                        volume_7d_avg=3_000_000, btc_change=2.0)
    monkeypatch.setattr(orch_mod, "build_snapshot", lambda token: flat)
    token = _token(price_change_percent=12.0)
    content, fmt, title, image_paths = orch_mod.prepare_post(token, "GAINERS", {"anomaly": 0.2})
    assert fmt == "short"
    assert image_paths is None
    assert calls["render"] == []
    assert calls["angles"] == [None]  # generated as a plain short post
    assert content.startswith("$KITE")


def test_prepare_post_longform_does_not_fetch_snapshot(orch, monkeypatch):
    orch_mod, calls = orch

    seen = []
    monkeypatch.setattr(orch_mod, "build_snapshot",
                        lambda token: seen.append(token["symbol"]))
    content, fmt, title, image_paths = orch_mod.prepare_post(_token(), "HOT", {"anomaly": 0.9})
    assert fmt == "longform"
    assert seen == []  # long-form covers keep the plain renderer


def test_prepare_post_image_render_failure_degrades_to_short(orch, monkeypatch):
    orch_mod, calls = orch
    from schedulers.card_renderer import CardRenderError

    def failing_render(token, snapshot=None, **kwargs):
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
                        lambda token, snapshot=None, **kw: (_ for _ in ()).throw(CardRenderError("boom")))
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

    monkeypatch.setattr(orch_mod, "generate_post", lambda t, c, s, **kw: None)
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
