# tests/test_card_types.py — card-type selection, angle mapping,
# closing-question prompt + extraction (Fase 3 step 4).
"""No network, no publishing: the LLM is mocked where generate_post
is exercised, and the angle state file is isolated per test."""
import json

import pytest

import prompts.styles as styles
from prompts.styles import (
    OPENING_ANGLES,
    card_type_angle,
    next_opening_angle,
    record_angle_used,
    reset_opening_deck,
    select_card_type,
)


@pytest.fixture(autouse=True)
def _isolated_angle_state(tmp_path, monkeypatch):
    monkeypatch.setattr(styles, "ANGLE_STATE_FILE", str(tmp_path / "angles.json"))
    reset_opening_deck()
    yield
    reset_opening_deck()


# --------------------------------------------------- select_card_type
def test_relative_weakness_trigger_and_boundary():
    assert select_card_type(change=-7.9, btc_relative=-10.0) == "relative_weakness"
    assert select_card_type(change=3.1, btc_relative=-5.0) == "relative_weakness"
    assert select_card_type(change=-7.9, btc_relative=-4.9) is None


def test_relative_weakness_needs_btc_context():
    # No BTC context: weakness is unknowable, other rules still apply.
    assert select_card_type(change=-7.9, btc_relative=None) is None
    assert select_card_type(change=-7.9, volume_ratio=3.0,
                            btc_relative=None) == "volume_spike"


def test_volume_spike_trigger_and_boundary():
    assert select_card_type(change=18.4, volume_ratio=3.2) == "volume_spike"
    assert select_card_type(change=-12.6, volume_ratio=2.0) == "volume_spike"
    assert select_card_type(change=18.4, volume_ratio=1.99) is None


def test_range_squeeze_trigger():
    assert select_card_type(change=1.2, volume_ratio=0.6,
                            range_width_pct=2.1,
                            range_position=0.48) == "range_squeeze"
    # Width at the boundary, or position outside the middle band: no match.
    assert select_card_type(change=1.2, volume_ratio=0.6,
                            range_width_pct=3.0,
                            range_position=0.48) is None
    assert select_card_type(change=1.2, volume_ratio=0.6,
                            range_width_pct=2.1,
                            range_position=0.9) is None
    assert select_card_type(change=1.2, volume_ratio=0.6,
                            range_width_pct=None,
                            range_position=0.48) is None


def test_thin_tape_trigger_and_boundary():
    assert select_card_type(change=0.8, volume_ratio=0.3) == "thin_tape"
    assert select_card_type(change=0.8, volume_ratio=0.5) is None
    assert select_card_type(change=3.0, volume_ratio=0.3) is None


def test_priority_weakness_over_spike_over_squeeze_over_tape():
    # Matches weakness + spike: weakness wins.
    assert select_card_type(change=-12.6, volume_ratio=4.1,
                            btc_relative=-10.0) == "relative_weakness"
    # Matches spike + squeeze: spike wins.
    assert select_card_type(change=1.2, volume_ratio=2.5,
                            range_width_pct=2.1,
                            range_position=0.5) == "volume_spike"
    # Matches squeeze + tape: squeeze wins.
    assert select_card_type(change=1.2, volume_ratio=0.3,
                            range_width_pct=2.1,
                            range_position=0.5) == "range_squeeze"


def test_ordinary_token_matches_no_type():
    assert select_card_type(change=2.0, volume_ratio=1.0,
                            range_width_pct=12.0, range_position=0.5,
                            btc_relative=-1.0) is None


# --------------------------------------------------- angle mapping
def test_card_type_angle_mapping():
    assert card_type_angle("thin_tape")[0] in ("absence", "understatement")
    assert card_type_angle("volume_spike")[0] in ("participation", "contrast")
    assert card_type_angle("range_squeeze")[0] == "range_position"
    assert card_type_angle("relative_weakness")[0] == "contrast"
    for name, text in [card_type_angle(t) for t in
                       ("thin_tape", "volume_spike", "range_squeeze",
                        "relative_weakness")]:
        assert text == OPENING_ANGLES[name]


def test_card_type_angle_prefers_unused_then_mapping_wins():
    record_angle_used("participation")
    assert card_type_angle("volume_spike")[0] == "contrast"
    record_angle_used("contrast")
    # Both mapped angles used: the mapping still wins over the deck.
    assert card_type_angle("volume_spike")[0] == "participation"


def test_card_type_angle_unknown_type_raises():
    with pytest.raises(KeyError):
        card_type_angle("bogus")


def test_record_angle_used_no_double_record(tmp_path):
    record_angle_used("contrast")
    record_angle_used("contrast")
    with open(styles.ANGLE_STATE_FILE) as f:
        assert json.load(f)["used"] == ["contrast"]


def test_deck_skips_recorded_angle():
    record_angle_used("contrast")
    reset_opening_deck(clear_file=False)  # restart: state file survives
    drawn = [next_opening_angle()[0] for _ in range(9)]
    assert "contrast" not in drawn
    assert len(set(drawn)) == 9


# ------------------------------------------- closing question prompt
def _token(**overrides):
    token = {
        "symbol": "KITE",
        "price": 2.40,
        "price_change_percent": -5.8,
        "volume_24h": 2_800_000,
        "range_position": 0.4,
    }
    token.update(overrides)
    return token


def test_build_prompt_closing_question_rule_only_when_flagged():
    from generators.post_generator import build_prompt

    plain = build_prompt(_token(), "HOT")
    assert "No forced closing line, no forced question" in plain
    assert "End the post with a closing question" not in plain

    flagged = build_prompt(_token(), "HOT", closing_question=True)
    assert "End the post with a closing question" in flagged
    assert "No forced closing line, no forced question" not in flagged
    # Cashtag rule untouched in both.
    assert "exactly ONCE, in the first line" in flagged


def test_data_section_snapshot_lines_need_enrichment_marker():
    from generators.post_generator import build_prompt

    plain = build_prompt(_token(), "HOT")
    assert "volume vs 7-day average" not in plain
    assert "BTC 24h change" not in plain

    # BTC alone (every token carries it) adds nothing: only the
    # snapshot enrichment marker switches the lines on.
    assert "BTC 24h change" not in build_prompt(
        _token(btc_change_24h=2.1), "HOT")

    enriched = build_prompt(_token(volume_ratio_7d=3.2, btc_change_24h=2.1),
                            "HOT")
    assert "volume vs 7-day average: 3.2x" in enriched
    assert "BTC 24h change: +2.1% (this token -7.9 pts vs BTC)" in enriched


def test_extract_closing_question():
    from generators.post_generator import extract_closing_question

    assert extract_closing_question(
        "First sentence here. Second one here. Does it hold?") == "Does it hold?"
    assert extract_closing_question("No question at all. Just a statement.") is None
    assert extract_closing_question("A question mid-post? Then a statement.") is None
    assert extract_closing_question("  Trailing space?  \n") == "Trailing space?"
    assert extract_closing_question("") is None
    assert extract_closing_question(None) is None


# ------------------------------------------- generate_post explicit angle
POST_WITH_QUESTION = (
    "$KITE volume ran 3.2x its 7-day average while price moved 12%. "
    "Participation showed up before the move did, which is the part "
    "worth noting. The advance held through the session without "
    "giving much back.\n\n"
    "Does the tape stay this loud past the weekend?"
)


def test_generate_post_explicit_angle_is_used_and_recorded(monkeypatch, tmp_path):
    from generators import post_generator

    seen = {}

    def fake_generate(prompt, **kwargs):
        seen["prompt"] = prompt
        return POST_WITH_QUESTION

    monkeypatch.setattr(post_generator, "generate", fake_generate)
    monkeypatch.setattr(post_generator, "is_similar_to_recent", lambda c: False)
    monkeypatch.setattr(post_generator, "add_to_recent", lambda c: None)

    result = post_generator.generate_post(
        _token(), "GAINERS", {},
        opening_angle=("participation", OPENING_ANGLES["participation"]),
        closing_question=True)
    assert result is not None
    assert result.endswith("?")
    assert "who showed up" in seen["prompt"]  # the mapped instruction
    assert "End the post with a closing question" in seen["prompt"]
    with open(styles.ANGLE_STATE_FILE) as f:
        assert "participation" in json.load(f)["used"]
