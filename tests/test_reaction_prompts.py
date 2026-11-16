"""Reaction + memory prompt wiring: build_prompt/generate_post accept
an optional reaction (replacing the angle) and a MEMORY block. The
angle path stays byte-identical — the existing prompt tests guard it;
these tests pin the reaction path's shape.
"""
import generators.post_generator as pg
from generators.post_generator import build_prompt, generate_post


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


def test_reaction_prompt_relaxes_person_rule_for_opener_only():
    prompt = build_prompt(_token(), "GAINERS", {},
                          reaction=("smug", "SMUG INSTRUCTION"))
    assert 'First person ("I") is allowed ONLY in the opening line' in prompt
    assert 'No first or second person: no "i", "we", "you".' not in prompt


def test_angle_prompt_keeps_strict_person_rule():
    prompt = build_prompt(_token(), "GAINERS", {},
                          opening_angle=("contrast", "ANGLE TEXT"))
    assert 'No first or second person: no "i", "we", "you".' in prompt
    assert "OPENING REACTION" not in prompt
    assert "First person" not in prompt


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
    assert "exactly once: weave the cashtag into the" in prompt


def test_generate_post_with_reaction_draws_no_angle(monkeypatch):
    # The angle deck must not move: any draw attempt fails loudly.
    monkeypatch.setattr(pg, "next_opening_angle",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("angle draw on reaction path")))
    monkeypatch.setattr(pg, "record_angle_used",
                        lambda name: (_ for _ in ()).throw(
                            AssertionError("angle record on reaction path")))
    monkeypatch.setattr(pg, "generate",
                        lambda *a, **k: "$NOVA reacted. " + "x" * 120)
    content = generate_post(_token(), "GAINERS", {},
                            reaction=("smug", "SMUG INSTRUCTION"))
    assert content is not None
    assert content.startswith("$NOVA")


def test_generate_post_reaction_skips_insufficient_insight(monkeypatch):
    # A token with nothing to observe is skipped before any LLM call,
    # reaction or not.
    monkeypatch.setattr(pg, "insufficient_insight", lambda *a, **k: "flat tape")
    monkeypatch.setattr(pg, "generate",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("LLM call despite skip")))
    assert generate_post(_token(), "GAINERS", {},
                         reaction=("smug", "SMUG")) is None
