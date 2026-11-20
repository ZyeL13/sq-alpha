"""Reaction + memory prompt wiring: build_prompt/generate_post accept
an optional reaction (replacing the angle) and a MEMORY block. The
angle path stays byte-identical — the existing prompt tests guard it;
these tests pin the reaction path's shape.
"""
import json

import generators.post_generator as pg
from generators.post_generator import build_prompt, generate_post
from generators.quality_gate import is_reasoning_leak


def _token(**overrides):
    token = {
        "symbol": "NOVA",
        "price": 1.29,
        "price_change_percent": 4.2,
        "volume_24h": 3_200_000,
        "range_position": 0.4,
    }
    token.update(overrides)
    return token


def test_reaction_prompt_uses_reaction_block_not_angle():
    prompt = build_prompt(_token(), "GAINERS", {},
                          reaction=("smug", "SMUG INSTRUCTION"))
    assert "OPENING REACTION: SMUG INSTRUCTION" in prompt
    assert "OPENING ANGLE" not in prompt


def test_reaction_prompt_allows_first_person_only_after_cashtag():
    prompt = build_prompt(_token(), "GAINERS", {},
                          reaction=("smug", "SMUG INSTRUCTION"))
    assert ('First person ("I") is allowed ONLY AFTER the cashtag in the '
            "opening line") in prompt
    assert "never as the first word" in prompt
    assert 'No first or second person: no "i", "we", "you".' not in prompt


def test_angle_prompt_keeps_strict_person_rule():
    prompt = build_prompt(_token(), "GAINERS", {},
                          opening_angle=("contrast", "ANGLE TEXT"))
    assert 'No first or second person: no "i", "we", "you".' in prompt
    assert "OPENING REACTION" not in prompt
    assert "First person" not in prompt
    assert "exactly once: weave the cashtag into the\nangle" in prompt


def test_memory_block_appended_to_data_section():
    prompt = build_prompt(_token(), "GAINERS", {},
                          reaction=("dejavu", "DEJAVU TEXT"),
                          memory="You last wrote about $NOVA on 15 Nov 2026.")
    assert "MEMORY: You last wrote about $NOVA on 15 Nov 2026." in prompt


def test_no_memory_block_when_none():
    prompt = build_prompt(_token(), "GAINERS", {},
                          reaction=("smug", "SMUG INSTRUCTION"))
    assert "MEMORY:" not in prompt


def test_reaction_prompt_keeps_cashtag_rule():
    prompt = build_prompt(_token(), "GAINERS", {},
                          reaction=("smug", "SMUG INSTRUCTION"))
    assert "exactly ONCE, in the first line" in prompt


def test_reaction_prompt_requires_cashtag_first():
    # Regression (2026-11-17): the old wording invited reaction-first
    # openers ("weave the cashtag into the reaction"), and the quality
    # gate rejects every post that does not start with the cashtag —
    # 100% of live short-form drafts died on "Reasoning leak detected".
    prompt = build_prompt(_token(), "GAINERS", {},
                          reaction=("smug", "SMUG INSTRUCTION"))
    assert "MUST begin with $NOVA as the very first characters" in prompt
    assert "reaction voice AFTER the cashtag in the same first line" in prompt
    assert "weave the cashtag into the" not in prompt


def test_reaction_prompt_forbids_leading_reaction_words():
    prompt = build_prompt(_token(), "GAINERS", {},
                          reaction=("smug", "SMUG INSTRUCTION"))
    assert ("Do NOT open with any reaction word or phrase before the\n"
            "cashtag") in prompt
    assert ("no leading I, Wait, Hmm, Hold on, So, Now, Again,") in prompt
    assert "Surprise, or any other word before the cashtag" in prompt


def test_generate_post_with_reaction_draws_no_angle(monkeypatch):
    # The angle deck must not move: any draw attempt fails loudly.
    monkeypatch.setattr(pg, "next_opening_angle",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("angle draw on reaction path")))
    monkeypatch.setattr(pg, "record_angle_used",
                        lambda name: (_ for _ in ()).throw(
                            AssertionError("angle record on reaction path")))
    monkeypatch.setattr(pg, "generate",
                        lambda *a, **k: json.dumps({
                            "event": "NOVA reacted",
                            "fact": "+4.2% to $1.29",
                            "interpretation": "buyers showed up",
                            "angle": "smug",
                            "post": "$NOVA reacted. " + "x" * 120}))
    result = generate_post(_token(), "GAINERS", {},
                           reaction=("smug", "SMUG INSTRUCTION"))
    assert result is not None
    assert result["post"].startswith("$NOVA")


def test_generate_post_reaction_skips_insufficient_insight(monkeypatch):
    # A token with nothing to observe is skipped before any LLM call,
    # reaction or not.
    monkeypatch.setattr(pg, "insufficient_insight", lambda *a, **k: "flat tape")
    monkeypatch.setattr(pg, "generate",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("LLM call despite skip")))
    assert generate_post(_token(), "GAINERS", {},
                         reaction=("smug", "SMUG")) is None


# Gate contract the reaction prompt must satisfy: the quality gate
# (generators/quality_gate.py, untouched by the JIT fix) rejects any
# short-form post that does not start with the cashtag. Reaction
# voice is only safe AFTER the cashtag on the first line.
def test_gate_accepts_cashtag_first_reaction_openers():
    passing = [
        "$ASTER faded again on thin volume, the third soft session in a "
        "row, and buyers are nowhere to be seen.",
        "$SHELL did it again, third fade this week, and volume is not "
        "even bothering to show up this time.",
        "$NOVA did it again, and I called this fade last week when "
        "volume first started thinning out.",
    ]
    for sample in passing:
        assert not is_reasoning_leak(sample), sample


def test_gate_still_rejects_reaction_first_openers():
    rejected = [
        "I did not expect $ASTER to fade this hard on thin volume, and "
        "the tape agrees with me here today.",
        "Wait, $SHELL just did the same fade for the third time this "
        "week and volume barely showed up at all.",
        "Again, $XPL is drifting lower while the rest of the market "
        "holds its ground into the close today.",
        "Surprise: $KAVA ripped higher on volume nobody saw coming and "
        "the move is still holding here.",
        "Honestly, $GTC looks stretched here with price pinned near the "
        "top of its range all session long.",
        "Hmm, $ERN is quiet again today, barely moving while volume "
        "stays far below its weekly average here.",
        "Hold on, $GOOGLB just printed a move that makes no sense "
        "against a flat tape everywhere else today.",
    ]
    for sample in rejected:
        assert is_reasoning_leak(sample), sample
