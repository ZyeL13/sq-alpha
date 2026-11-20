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
    the content, "angle" the echoed drawn angle.
    """
    calls = {}

    def _fake_generate(*a, **k):
        content = calls.get("content", "$NOVA test post.")
        if content is None:
            return None
        return {"event": "e", "fact": "f", "interpretation": "i",
                "angle": calls.get("angle", "smug"), "post": content}

    monkeypatch.setattr(orch, "select_post_format",
                        lambda *a, **k: calls.get("fmt", "short"))
    monkeypatch.setattr(orch, "get_format_counts", lambda: {})
    monkeypatch.setattr(orch, "generate_post", _fake_generate)
    monkeypatch.setattr(orch, "generate_longform",
                        lambda *a, **k: calls.get("longform"))
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


def test_finalize_longform_cover_failure_keeps_article(monkeypatch, _stubs):
    _stubs["fmt"] = "longform"
    _stubs["longform"] = ("Title Here", "Body " * 200)
    draft = orch.prepare_draft(_token(), "GAINERS", {})
    assert draft.fmt == "longform"
    assert draft.title == "Title Here"

    def _boom(*a, **k):
        raise CardRenderError("nope")
    monkeypatch.setattr(orch, "render_card", _boom)
    content, fmt, title, paths = orch.finalize_draft(draft)
    assert fmt == "longform"
    assert paths is None
    assert title == "Title Here"


def test_finalize_longform_cover_uses_plain_style(monkeypatch, _stubs):
    _stubs["fmt"] = "longform"
    _stubs["longform"] = ("Title Here", "Body " * 200)
    draft = orch.prepare_draft(_token(), "GAINERS", {})
    seen = {}
    monkeypatch.setattr(orch, "render_card",
                        lambda *a, **k: seen.update(k) or "cover.png")
    _, fmt, _, paths = orch.finalize_draft(draft)
    assert seen == {"style": "plain"}
    assert paths == ["cover.png"]


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
