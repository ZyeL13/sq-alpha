"""Opening-angle variety: consecutive posts must not open the same way.

Regresi dari observasi user 2026-11-15: 4 post berurutan ($HOME, $LDO,
$SOXSB, $SOL) semuanya dibuka "$X slipped N%...". Penyebabnya:
Editorial v2 menghapus hook verbatim dari prompt, jadi model
mengimprovisasi pembuka — dan improvisasi konvergen ke pembuka
default yang paling mungkin untuk tiap kategori. Larangan di system
prompt ("repeatedly starting posts with token price movements")
tidak cukup tanpa mekanisme positif.

Perbaikannya: setiap post mendapat SATU opening angle (instruksi,
bukan teks verbatim) dari deck yang berputar — tiap angle dipakai
sekali per siklus sebelum ada yang berulang.
"""
import re

from generators.post_generator import build_prompt
from prompts.styles import (
    EDITORIAL_FORBIDDEN,
    OPENING_ANGLES,
    next_opening_angle,
    reset_opening_deck,
)


def _token(symbol="TEST"):
    return {
        "symbol": symbol,
        "price": 1.25,
        "price_change_percent": -5.8,
        "volume_24h": 2_800_000,
        "range_position": 0.4,
    }


def test_pool_has_enough_distinct_angles():
    assert len(OPENING_ANGLES) >= 8
    assert len(set(OPENING_ANGLES.values())) == len(OPENING_ANGLES)
    for name, text in OPENING_ANGLES.items():
        assert re.fullmatch(r"[a-z_]+", name), name
        assert len(text) > 40, name


def test_angles_contain_no_forbidden_phrases():
    for name, text in OPENING_ANGLES.items():
        lowered = text.lower()
        for phrase in EDITORIAL_FORBIDDEN:
            assert phrase not in lowered, f"{name} contains {phrase!r}"


def test_full_cycle_uses_each_angle_once():
    reset_opening_deck()
    drawn = [next_opening_angle()[0] for _ in range(len(OPENING_ANGLES))]
    assert len(set(drawn)) == len(OPENING_ANGLES)
    assert set(drawn) == set(OPENING_ANGLES)


def test_no_adjacent_repeats_across_cycles():
    reset_opening_deck()
    drawn = [next_opening_angle()[0] for _ in range(3 * len(OPENING_ANGLES))]
    for prev, cur in zip(drawn, drawn[1:]):
        assert prev != cur


def test_seeded_reset_is_deterministic():
    reset_opening_deck(seed=42)
    first = [next_opening_angle()[0] for _ in range(len(OPENING_ANGLES))]
    reset_opening_deck(seed=42)
    second = [next_opening_angle()[0] for _ in range(len(OPENING_ANGLES))]
    assert first == second


def test_build_prompt_carries_opening_angle():
    reset_opening_deck(seed=7)
    prompt = build_prompt(_token(), "LOSERS")
    assert "OPENING ANGLE:" in prompt
    assert any(text in prompt for text in OPENING_ANGLES.values())
    # Anti-default instruction present, without naming the banned verb
    # (naming it would prime the model to use it).
    assert "do NOT open with a plain price-move sentence" in prompt
    assert "slipped" not in prompt.lower()


def test_build_prompt_honors_explicit_angle():
    prompt = build_prompt(_token(), "LOSERS",
                          opening_angle=("custom", "Open with a custom angle."))
    assert "Open with a custom angle." in prompt


def test_consecutive_prompts_get_different_angles():
    reset_opening_deck()
    prompts = [build_prompt(_token(), "LOSERS") for _ in range(4)]
    angles = []
    for prompt in prompts:
        for name, text in OPENING_ANGLES.items():
            if text in prompt:
                angles.append(name)
    assert len(angles) == 4
    assert len(set(angles)) == 4


def test_cashtag_rule_still_in_prompt():
    prompt = build_prompt(_token(), "LOSERS")
    assert "exactly ONCE, in the first line" in prompt
