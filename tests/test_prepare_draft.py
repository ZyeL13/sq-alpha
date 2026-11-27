"""prepare_post split (spec 5.1): prepare_draft generates without
rendering; finalize_draft renders the winner only; prepare_post stays
a thin wrapper. All pre-split fallbacks preserved. No network, no LLM
— generation and rendering are stubbed.
"""
import pytest

import schedulers.orchestrator as orch
from schedulers.card_renderer import CardRenderError
from schedulers.snapshot import CardSnapshot


def _token(**overrides):
    token = {
        "symbol": "NOVA",
        "price": 1.29,
        "price_change_percent": 18.4,
        "volume_24h": 3_200_000,
        "high_24h": 1.35,
        "low_24h": 1.08,
        "btc_change_24h": 2.1,
        "timestamp": 1794634800,
    }
    token.update(overrides)
    return token


def _snapshot(token):
    return CardSnapshot(token=dict(token), closes=[1.09 + i * 0.01 for i in range(24)],
                        volume_7d_avg=1_000_000, btc_change=2.1)


@pytest.fixture
def _stubs(monkeypatch):
    """Stub the format decision + generation; rendering is stubbed
    per-test so each test controls whether it may run.

    generate_post returns the step-1 JSON dict; the "post" field is
    the content, "angle" the echoed drawn angle. The format decision
    is select_post_format_with_reason (justification rides along);
    build_snapshot defaults to a fixture snapshot unless a test sets
    calls["snapshot"] (None simulates klines failure).
    """
    calls = {}

    def _fake_generate(*a, **k):
        content = calls.get("content", "$NOVA test post.")
        if content is None:
            return None
        return {"event": "e", "fact": "f", "interpretation": "i",
                "angle": calls.get("angle", "smug"), "post": content}

    def _fake_longform(*a, **k):
        calls["longform_kwargs"] = k
        calls["longform_args"] = a
        return calls.get("longform")

    monkeypatch.setattr(orch, "select_post_format_with_reason",
                        lambda *a, **k: (calls.get("fmt", "short"),
                                         calls.get("justification")))
    monkeypatch.setattr(orch, "get_format_counts", lambda: {})
    monkeypatch.setattr(orch, "build_snapshot",
                        lambda t: calls.get("snapshot", _snapshot(t)))
    monkeypatch.setattr(orch, "generate_post", _fake_generate)
    monkeypatch.setattr(orch, "generate_longform", _fake_longform)
    return calls


def test_draft_phase_never_renders(monkeypatch, _stubs):
    _stubs["fmt"] = "image"
    token = _token()
    monkeypatch.setattr(orch, "build_snapshot", lambda t: _snapshot(t))
    monkeypatch.setattr(orch, "select_card_type", lambda **k: "volume_spike")
    monkeypatch.setattr(orch, "card_type_angle",
                        lambda ct: ("participation", "PARTICIPATION"))
    rendered = []
    monkeypatch.setattr(orch, "render_card",
                        lambda *a, **k: rendered.append(1) or "x.png")
    draft = orch.prepare_draft(token, "GAINERS", {})
    assert draft is not None
    assert draft.fmt == "image"
    assert draft.card_type == "volume_spike"
    assert draft.snapshot is not None
    assert rendered == []


def test_finalize_renders_image_winner(monkeypatch, _stubs):
    _stubs["fmt"] = "image"
    token = _token()
    monkeypatch.setattr(orch, "build_snapshot", lambda t: _snapshot(t))
    monkeypatch.setattr(orch, "select_card_type", lambda **k: "volume_spike")
    monkeypatch.setattr(orch, "card_type_angle",
                        lambda ct: ("participation", "PARTICIPATION"))
    draft = orch.prepare_draft(token, "GAINERS", {})
    seen = {}
    monkeypatch.setattr(orch, "render_card",
                        lambda *a, **k: seen.update(k) or "card.png")
    content, fmt, title, paths = orch.finalize_draft(draft)
    assert fmt == "image"
    assert paths == ["card.png"]
    assert seen["card_type"] == "volume_spike"
    assert seen["snapshot"] is draft.snapshot


def test_finalize_render_failure_falls_back_to_short(monkeypatch, _stubs):
    _stubs["fmt"] = "image"
    token = _token()
    monkeypatch.setattr(orch, "build_snapshot", lambda t: _snapshot(t))
    monkeypatch.setattr(orch, "select_card_type", lambda **k: "volume_spike")
    monkeypatch.setattr(orch, "card_type_angle",
                        lambda ct: ("participation", "PARTICIPATION"))
    draft = orch.prepare_draft(token, "GAINERS", {})

    def _boom(*a, **k):
        raise CardRenderError("nope")
    monkeypatch.setattr(orch, "render_card", _boom)
    content, fmt, title, paths = orch.finalize_draft(draft)
    assert fmt == "short"
    assert paths is None
    assert content == draft.content


def test_finalize_longform_banner_failure_keeps_article(monkeypatch, _stubs):
    _stubs["fmt"] = "longform"
    _stubs["longform"] = ("Title Here", "Body " * 200)
    draft = orch.prepare_draft(_token(), "GAINERS", {})
    assert draft.fmt == "longform"
    assert draft.title == "Title Here"

    def _boom(*a, **k):
        raise CardRenderError("nope")
    monkeypatch.setattr(orch._banner, "render_article_banner", _boom)
    monkeypatch.setattr(orch, "render_card",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("long-form never renders plain")))
    content, fmt, title, paths = orch.finalize_draft(draft)
    assert fmt == "longform"
    assert paths is None
    assert title == "Title Here"


def test_finalize_longform_banner_assertion_failure_keeps_article(
        monkeypatch, _stubs):
    from schedulers.banner import BannerAssertionError

    _stubs["fmt"] = "longform"
    _stubs["longform"] = ("Title Here", "Body " * 200)
    draft = orch.prepare_draft(_token(), "GAINERS", {})

    def _boom(*a, **k):
        raise BannerAssertionError("style repeats last")
    monkeypatch.setattr(orch._banner, "render_article_banner", _boom)
    _, fmt, _, paths = orch.finalize_draft(draft)
    assert fmt == "longform"
    assert paths is None


def test_finalize_longform_cover_uses_banner(monkeypatch, _stubs):
    _stubs["fmt"] = "longform"
    _stubs["longform"] = ("Title Here", "Body " * 200)
    monkeypatch.setattr(
        orch._post_gen, "LAST_DRAFT_META",
        {"article": {"headline": "NOVA JUMPS 18.4% ON VOLUME",
                     "deck": "Volume ran hot into the close.",
                     "stance": "BULLISH"},
         "research_pack": {"facts": {"symbol": "NOVA",
                                     "change_24h": 18.4,
                                     "volume_24h": 3_200_000},
                           "stance": "BULLISH", "angle": "anomaly",
                           "catalyst": None,
                           "missing": {"fillable": [], "unavailable": []}}})
    draft = orch.prepare_draft(_token(), "GAINERS", {})
    assert draft.article_json["headline"] == "NOVA JUMPS 18.4% ON VOLUME"
    assert draft.research_pack["angle"] == "anomaly"

    seen = {}
    monkeypatch.setattr(orch._banner, "select_banner_style",
                        lambda pack, article: seen.update(
                            pack=pack, article=article) or "A")
    monkeypatch.setattr(orch._banner, "render_article_banner",
                        lambda *a, **k: seen.update(
                            args=a, kwargs=k) or "banner.png")
    monkeypatch.setattr(orch, "render_card",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("long-form never renders plain")))
    _, fmt, _, paths = orch.finalize_draft(draft)
    assert fmt == "longform"
    assert paths == ["banner.png"]
    # The banner gets the article headline/deck/stance, the snapshot
    # (with closes for the style-C decision), and the selected style.
    token, snapshot, stance, deck, headline = seen["args"]
    assert token["symbol"] == "NOVA"
    assert snapshot is draft.snapshot
    assert stance == "BULLISH"
    assert deck == "Volume ran hot into the close."
    assert headline == "NOVA JUMPS 18.4% ON VOLUME"
    assert seen["kwargs"] == {"style": "A"}
    # The selection pack carries the snapshot's closes (copied in).
    assert seen["pack"]["facts"]["closes"] == list(draft.snapshot.closes)


def test_finalize_longform_cover_falls_back_to_code_headline(
        monkeypatch, _stubs):
    # No article JSON (stubbed generation, empty LAST_DRAFT_META):
    # the banner gets the code-built {SYMBOL} {VERB} {chg}% headline
    # and no deck, with the stance derived from the change.
    _stubs["fmt"] = "longform"
    _stubs["longform"] = ("Title Here", "Body " * 200)
    monkeypatch.setattr(orch._post_gen, "LAST_DRAFT_META", {})
    draft = orch.prepare_draft(_token(), "GAINERS", {})
    assert draft.article_json is None

    seen = {}
    monkeypatch.setattr(orch._banner, "render_article_banner",
                        lambda *a, **k: seen.update(args=a) or "banner.png")
    _, fmt, _, paths = orch.finalize_draft(draft)
    assert fmt == "longform"
    assert paths == ["banner.png"]
    _, _, stance, deck, headline = seen["args"]
    assert headline == "NOVA JUMPS +18.4%"
    assert deck == ""
    assert stance == "BULLISH"


def test_longform_snapshot_built_and_klines_failure_coverless(
        monkeypatch, _stubs):
    _stubs["fmt"] = "longform"
    _stubs["justification"] = "anomaly"
    _stubs["longform"] = ("Title Here", "Body " * 200)
    draft = orch.prepare_draft(_token(), "GAINERS", {},
                               memory="MEMORY BLOCK")
    # The snapshot is built for long-form, and the justification +
    # snapshot + memory are passed into generate_longform.
    assert draft.fmt == "longform"
    assert draft.snapshot is not None
    assert _stubs["longform_kwargs"]["snapshot"] is draft.snapshot
    assert _stubs["longform_kwargs"]["justification"] == "anomaly"
    assert _stubs["longform_kwargs"]["memory"] == "MEMORY BLOCK"
    # Banner renders with a snapshot present.
    monkeypatch.setattr(orch._banner, "render_article_banner",
                        lambda *a, **k: "banner.png")
    _, fmt, _, paths = orch.finalize_draft(draft)
    assert fmt == "longform"
    assert paths == ["banner.png"]

    # Klines failure: the article still generates, snapshot None,
    # and finalize publishes coverless (format kept).
    _stubs["snapshot"] = None
    draft = orch.prepare_draft(_token(), "GAINERS", {})
    assert draft.fmt == "longform"
    assert draft.snapshot is None
    assert _stubs["longform_kwargs"]["snapshot"] is None
    monkeypatch.setattr(orch._banner, "render_article_banner",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("no banner without a snapshot")))
    _, fmt, _, paths = orch.finalize_draft(draft)
    assert fmt == "longform"
    assert paths is None


def test_klines_failure_downgrades_draft_to_short(monkeypatch, _stubs):
    _stubs["fmt"] = "image"
    monkeypatch.setattr(orch, "build_snapshot", lambda t: None)
    draft = orch.prepare_draft(_token(), "GAINERS", {})
    assert draft.fmt == "short"
    assert draft.snapshot is None
    assert draft.card_type is None


def test_no_card_type_downgrades_draft_to_short(monkeypatch, _stubs):
    _stubs["fmt"] = "image"
    monkeypatch.setattr(orch, "build_snapshot", lambda t: _snapshot(t))
    monkeypatch.setattr(orch, "select_card_type", lambda **k: None)
    draft = orch.prepare_draft(_token(), "GAINERS", {})
    assert draft.fmt == "short"
    assert draft.card_type is None


def test_longform_generation_failure_falls_back_once(monkeypatch, _stubs):
    _stubs["fmt"] = "longform"
    _stubs["longform"] = None
    calls = []
    monkeypatch.setattr(orch, "generate_post",
                        lambda *a, **k: calls.append(1) or {
                            "event": "e", "fact": "f", "interpretation": "i",
                            "angle": "smug", "post": "$NOVA fallback."})
    draft = orch.prepare_draft(_token(), "GAINERS", {})
    assert draft.fmt == "short"
    assert draft.content == "$NOVA fallback."
    assert len(calls) == 1


def test_generation_failure_returns_none(monkeypatch, _stubs):
    _stubs["content"] = None
    assert orch.prepare_draft(_token(), "GAINERS", {}) is None
    assert orch.prepare_post(_token(), "GAINERS", {}) is None


def test_reaction_replaces_card_type_angle(monkeypatch, _stubs):
    _stubs["fmt"] = "image"
    token = _token()
    monkeypatch.setattr(orch, "build_snapshot", lambda t: _snapshot(t))
    monkeypatch.setattr(orch, "select_card_type", lambda **k: "volume_spike")

    def _no_angle(ct):
        raise AssertionError("card_type_angle must not run on the JIT path")
    monkeypatch.setattr(orch, "card_type_angle", _no_angle)
    seen = {}
    monkeypatch.setattr(orch, "generate_post",
                        lambda *a, **k: seen.update(k) or {
                            "event": "e", "fact": "f", "interpretation": "i",
                            "angle": "smug", "post": "$NOVA reacted."})
    draft = orch.prepare_draft(
        token, "GAINERS", {},
        reaction=("smug", "SMUG TEXT"), memory="MEMORY BLOCK")
    assert draft.reaction == "smug"
    assert draft.angle == "smug"
    assert seen["reaction"] == ("smug", "SMUG TEXT")
    assert seen["memory"] == "MEMORY BLOCK"
    assert seen["opening_angle"] is None
    assert seen["closing_question"] is True
    assert seen["card_type"] == "volume_spike"


def test_old_path_still_uses_card_type_angle(monkeypatch, _stubs):
    _stubs["fmt"] = "image"
    _stubs["angle"] = "participation"
    token = _token()
    monkeypatch.setattr(orch, "build_snapshot", lambda t: _snapshot(t))
    monkeypatch.setattr(orch, "select_card_type", lambda **k: "volume_spike")
    monkeypatch.setattr(orch, "card_type_angle",
                        lambda ct: ("participation", "PARTICIPATION"))
    seen = {}
    monkeypatch.setattr(orch, "generate_post",
                        lambda *a, **k: seen.update(k) or {
                            "event": "e", "fact": "f", "interpretation": "i",
                            "angle": "participation", "post": "$NOVA angled."})
    draft = orch.prepare_draft(token, "GAINERS", {})
    assert draft.reaction is None
    assert draft.angle == "participation"
    assert seen["opening_angle"] == ("participation", "PARTICIPATION")
    assert seen.get("reaction") is None


def test_longform_success_ignores_reaction(monkeypatch, _stubs):
    _stubs["fmt"] = "longform"
    _stubs["longform"] = ("Title", "Body " * 200)
    draft = orch.prepare_draft(_token(), "GAINERS", {},
                               reaction=("smug", "SMUG"))
    assert draft.fmt == "longform"
    assert draft.reaction is None


def test_wrapper_returns_finalized_tuple(monkeypatch, _stubs):
    _stubs["fmt"] = "short"
    monkeypatch.setattr(orch, "render_card",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("short posts never render")))
    result = orch.prepare_post(_token(), "GAINERS", {})
    assert result == ("$NOVA test post.", "short", None, None)


def test_draft_carries_total_score(monkeypatch, _stubs):
    draft = orch.prepare_draft(_token(), "GAINERS", {}, total_score=0.77)
    assert draft.total_score == 0.77
    assert draft.token["symbol"] == "NOVA"
    assert draft.category == "GAINERS"


# ------------------------------------------------- worker C: mode wiring
_DAY1 = {"mode": "deep-signal",
         "hypothesis": "new long-form + specific question earns replies",
         "variable_tested": "format=Deep Signal",
         "visual": "banner"}
_DAY2 = {"mode": "pulse",
         "hypothesis": "hook strength",
         "variable_tested": "format=Market Pulse, headline fact+hook",
         "visual": "sketchnote card"}


def test_mode_deep_signal_forces_longform_with_question(monkeypatch, _stubs):
    # The format decision says "short"; the Day-1 plan overrides it
    # to long-form, and generate_longform gets require_question=True.
    _stubs["fmt"] = "short"
    _stubs["longform"] = ("Title Here", "Body " * 200)
    draft = orch.prepare_draft(_token(), "GAINERS", {}, mode="deep-signal",
                               day_plan=_DAY1)
    assert draft.fmt == "longform"
    assert draft.mode == "deep-signal"
    assert draft.visual == "banner"
    assert draft.hypothesis == _DAY1["hypothesis"]
    assert draft.variable_tested == "format=Deep Signal"
    assert _stubs["longform_kwargs"]["require_question"] is True


def test_mode_pulse_reaches_generate_post(monkeypatch, _stubs):
    _stubs["fmt"] = "short"
    monkeypatch.setattr(orch, "select_card_type", lambda **k: "volume_spike")
    monkeypatch.setattr(orch, "card_type_angle",
                        lambda ct: ("participation", "PARTICIPATION"))
    seen = {}
    monkeypatch.setattr(orch, "generate_post",
                        lambda *a, **k: seen.update(k) or {
                            "event": "e", "fact": "f", "interpretation": "i",
                            "angle": "smug", "post": "$NOVA pulsed."})
    # Mode derived from the day plan when not passed explicitly.
    draft = orch.prepare_draft(_token(), "GAINERS", {}, day_plan=_DAY2)
    # Day 2's visual is a card, so the short draft is forced through
    # the image path (snapshot + card type) instead of staying text.
    assert draft.fmt == "image"
    assert draft.card_type == "volume_spike"
    assert draft.mode == "pulse"
    assert draft.visual == "sketchnote card"
    assert seen["mode"] == "pulse"
    assert seen["closing_question"] is True


def test_mode_short_overrides_longform_decision(monkeypatch, _stubs):
    # A "longform" format decision on a Pulse day becomes a short
    # draft (then forced to image by the Day-2 visual).
    _stubs["fmt"] = "longform"
    _stubs["longform"] = ("Title Here", "Body " * 200)
    monkeypatch.setattr(orch, "select_card_type", lambda **k: "volume_spike")
    monkeypatch.setattr(orch, "card_type_angle",
                        lambda ct: ("participation", "PARTICIPATION"))
    monkeypatch.setattr(orch, "generate_post",
                        lambda *a, **k: {
                            "event": "e", "fact": "f", "interpretation": "i",
                            "angle": "smug", "post": "$NOVA pulsed."})
    draft = orch.prepare_draft(_token(), "GAINERS", {}, day_plan=_DAY2)
    assert draft.fmt == "image"
    assert draft.mode == "pulse"
    assert _stubs.get("longform_kwargs") is None  # long-form never ran


def test_visual_banner_renders_banner_not_card(monkeypatch, _stubs):
    _stubs["fmt"] = "image"
    _stubs["content"] = ("$NOVA jumped +18.4% to $1.35.\n"
                         "Volume ran hot into the close.\n\n"
                         "Buyers stayed active into the close.")
    monkeypatch.setattr(orch, "select_card_type", lambda **k: "volume_spike")
    monkeypatch.setattr(orch, "card_type_angle",
                        lambda ct: ("participation", "PARTICIPATION"))
    day1_pulse = dict(_DAY2, visual="banner")
    draft = orch.prepare_draft(_token(), "GAINERS", {}, day_plan=day1_pulse)
    assert draft.fmt == "image"
    assert draft.visual == "banner"

    seen = {}
    monkeypatch.setattr(orch._banner, "render_article_banner",
                        lambda *a, **k: seen.update(args=a, kwargs=k)
                        or "banner.png")
    monkeypatch.setattr(orch, "render_card",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("banner visual never renders card")))
    content, fmt, title, paths = orch.finalize_draft(draft)
    assert fmt == "image"
    assert paths == ["banner.png"]
    token, snapshot, stance, deck, headline = seen["args"]
    assert token["symbol"] == "NOVA"
    assert snapshot is draft.snapshot
    assert stance == "BULLISH"  # from the token's +18.4% change
    assert deck == ""
    assert headline == ("$NOVA jumped +18.4% to $1.35. "
                        "Volume ran hot into the close.")
    assert seen["kwargs"] == {"style": None}


def test_visual_chart_renders_card(monkeypatch, _stubs):
    _stubs["fmt"] = "image"
    monkeypatch.setattr(orch, "select_card_type", lambda **k: "volume_spike")
    monkeypatch.setattr(orch, "card_type_angle",
                        lambda ct: ("participation", "PARTICIPATION"))
    draft = orch.prepare_draft(_token(), "GAINERS", {}, day_plan=_DAY2)
    assert draft.visual == "sketchnote card"

    monkeypatch.setattr(orch._banner, "render_article_banner",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("chart visual never renders banner")))
    seen = {}
    monkeypatch.setattr(orch, "render_card",
                        lambda *a, **k: seen.update(k) or "card.png")
    _, fmt, _, paths = orch.finalize_draft(draft)
    assert fmt == "image"
    assert paths == ["card.png"]
    assert seen["card_type"] == "volume_spike"


def test_visual_banner_failure_falls_back_to_card(monkeypatch, _stubs):
    from schedulers.banner import BannerAssertionError

    _stubs["fmt"] = "image"
    monkeypatch.setattr(orch, "select_card_type", lambda **k: "volume_spike")
    monkeypatch.setattr(orch, "card_type_angle",
                        lambda ct: ("participation", "PARTICIPATION"))
    day1_pulse = dict(_DAY2, visual="banner")
    draft = orch.prepare_draft(_token(), "GAINERS", {}, day_plan=day1_pulse)

    def _boom(*a, **k):
        raise BannerAssertionError("style repeats last")
    monkeypatch.setattr(orch._banner, "render_article_banner", _boom)
    monkeypatch.setattr(orch, "render_card",
                        lambda *a, **k: "card.png")
    _, fmt, _, paths = orch.finalize_draft(draft)
    assert fmt == "image"
    assert paths == ["card.png"]


def test_visual_forcing_failure_records_none(monkeypatch, _stubs):
    # Klines fail on a Pulse day: short text, visual "none".
    _stubs["fmt"] = "short"
    monkeypatch.setattr(orch, "build_snapshot", lambda t: None)
    draft = orch.prepare_draft(_token(), "GAINERS", {}, day_plan=_DAY2)
    assert draft.fmt == "short"
    assert draft.visual == "none"
    assert draft.mode == "pulse"
