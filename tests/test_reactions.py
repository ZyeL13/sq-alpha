"""Opening reactions: human-reaction openers replacing the 10 angles
on the JIT path (spec 5.3). Same deck machinery as the angle deck —
day-scoped, no repeats per cycle, no adjacent repeats — plus
record-on-win: pool rounds draw tentatively and only the winner's
reaction is recorded as used.
"""
import json
import re

import pytest

import prompts.reactions as reactions
from prompts.reactions import (
    REACTIONS,
    _pick_from_deck,
    draw_reaction,
    record_reaction_used,
    reset_reaction_deck,
    trigger_matches,
)
from prompts.styles import EDITORIAL_FORBIDDEN


@pytest.fixture(autouse=True)
def _isolated_reaction_state(tmp_path, monkeypatch):
    """Point the persistent reaction state at a tmp file and start
    each test with an empty deck, so tests never touch the real
    cache."""
    monkeypatch.setattr(reactions, "REACTION_STATE_FILE",
                        str(tmp_path / "reactions.json"))
    reset_reaction_deck()
    yield
    reset_reaction_deck()


def _token(**overrides):
    token = {
        "symbol": "TEST",
        "price": 1.25,
        "price_change_percent": 1.0,
        "volume_24h": 2_800_000,
        "high_24h": 1.35,
        "low_24h": 1.08,
    }
    token.update(overrides)
    return token


# ------------------------------------------------------------ pool
def test_pool_has_eight_distinct_reactions():
    assert set(REACTIONS) == {
        "surprise", "dejavu", "shrug", "disbelief",
        "question", "contrast", "caution", "smug",
    }
    assert len(set(REACTIONS.values())) == len(REACTIONS)
    for name, text in REACTIONS.items():
        assert re.fullmatch(r"[a-z_]+", name), name
        assert len(text) > 40, name


def test_reactions_contain_no_forbidden_phrases():
    for name, text in REACTIONS.items():
        lowered = text.lower()
        for phrase in EDITORIAL_FORBIDDEN:
            assert phrase not in lowered, (name, phrase)


def test_reactions_avoid_reasoning_leak_triggers():
    # The model echoes instruction language; a post containing one of
    # these is hard-rejected by the quality gate.
    triggers = ["hold on", "let me", "i need to", "we need to",
                "let's", "hmm", "the rules say", "first line:"]
    for name, text in REACTIONS.items():
        lowered = text.lower()
        for phrase in triggers:
            assert phrase not in lowered, (name, phrase)


# -------------------------------------------------------- triggers
def test_trigger_surprise():
    assert trigger_matches("surprise", _token(price_change_percent=6.0))
    assert trigger_matches("surprise", _token(price_change_percent=-5.0))
    assert trigger_matches("surprise", _token(price_change_percent=1.0,
                                              volume_ratio_7d=2.5))
    assert not trigger_matches("surprise", _token(price_change_percent=1.0))


def test_trigger_dejavu_needs_memory_same_direction():
    mem_up = {"change": 4.0}
    assert trigger_matches("dejavu", _token(price_change_percent=2.0), mem_up)
    assert not trigger_matches("dejavu", _token(price_change_percent=-2.0), mem_up)
    assert not trigger_matches("dejavu", _token(price_change_percent=2.0))
    assert not trigger_matches("dejavu", _token(price_change_percent=0.0), mem_up)
    assert not trigger_matches("dejavu", _token(price_change_percent=2.0),
                               {"change": 0.0})


def test_trigger_shrug_weak_only():
    assert trigger_matches("shrug", _token(price_change_percent=1.5))
    assert trigger_matches("shrug", _token(price_change_percent=-2.9))
    assert not trigger_matches("shrug", _token(price_change_percent=3.0))


def test_trigger_disbelief_extremes():
    assert trigger_matches("disbelief", _token(price_change_percent=16.0))
    assert trigger_matches("disbelief", _token(price_change_percent=1.0,
                                               volume_ratio_7d=3.5))
    # The volume-without-price rule ignores the news catalyst.
    assert trigger_matches("disbelief", _token(price_change_percent=1.0,
                                               volume_ratio_7d=3.5,
                                               news_catalyst="x"))
    assert trigger_matches("disbelief", _token(price_change_percent=11.0))
    assert not trigger_matches("disbelief", _token(price_change_percent=11.0,
                                                    news_catalyst="big news"))
    assert not trigger_matches("disbelief", _token(price_change_percent=5.0))


def test_trigger_question_always_matches():
    assert trigger_matches("question", _token())
    assert trigger_matches("question", _token(price_change_percent=-20.0))


def test_trigger_contrast_needs_btc_relative():
    assert trigger_matches("contrast", _token(price_change_percent=8.0,
                                              btc_change_24h=2.0))
    assert trigger_matches("contrast", _token(price_change_percent=-1.0,
                                              btc_change_24h=3.0))
    assert not trigger_matches("contrast", _token(price_change_percent=3.0,
                                                  btc_change_24h=2.0))
    assert not trigger_matches("contrast", _token(price_change_percent=8.0))


def test_trigger_caution_range_edge_plus_move():
    # Price at the 24h high (range position 1.0) + big move.
    assert trigger_matches("caution", _token(price_change_percent=6.0,
                                             price=1.35))
    # Mid-range: no match despite the move.
    assert not trigger_matches("caution", _token(price_change_percent=6.0,
                                                 price=1.21))
    # Range edge but small move: no match.
    assert not trigger_matches("caution", _token(price_change_percent=2.0,
                                                 price=1.35))


def test_trigger_smug_memory_continuation():
    mem = {"change": 5.0}
    assert trigger_matches("smug", _token(price_change_percent=4.0), mem)
    assert not trigger_matches("smug", _token(price_change_percent=2.0), mem)
    assert not trigger_matches("smug", _token(price_change_percent=-4.0), mem)
    assert not trigger_matches("smug", _token(price_change_percent=4.0))


def test_trigger_unknown_name_never_matches():
    assert not trigger_matches("nope", _token())


def test_trigger_bad_numbers_do_not_crash():
    token = _token(price_change_percent="n/a", volume_ratio_7d="x",
                   btc_change_24h="y")
    for name in REACTIONS:
        trigger_matches(name, token, {"change": "n/a"})


# ------------------------------------------------------------ deck
def test_pick_prefers_trigger_match_in_deck_order():
    deck = ["shrug", "question", "contrast"]
    # Only contrast's trigger matches; it is picked despite deck order.
    assert _pick_from_deck(deck, _token(price_change_percent=8.0,
                                         btc_change_24h=2.0)) == "contrast"


def test_pick_falls_back_to_last_name():
    # No trigger matches except question; deck without question.
    deck = ["shrug", "caution"]
    assert _pick_from_deck(deck, _token(price_change_percent=4.0,
                                         price=1.21)) == "caution"


def test_pick_skips_excluded_while_alternatives_exist():
    deck = ["question", "shrug"]
    assert _pick_from_deck(deck, _token(price_change_percent=1.0),
                           exclude="shrug") == "question"
    assert _pick_from_deck(["shrug"], _token(), exclude="shrug") == "shrug"


def test_draw_cycles_all_reactions_without_repeat():
    reset_reaction_deck(seed=7)
    names = [draw_reaction(_token())[0] for _ in range(8)]
    assert sorted(names) == sorted(REACTIONS)
    # Ninth draw refills: still a valid reaction, never a crash.
    name, text = draw_reaction(_token())
    assert name in REACTIONS and text == REACTIONS[name]


def test_no_adjacent_repeat_across_refill():
    reset_reaction_deck(seed=3)
    names = []
    for _ in range(24):
        name, _ = draw_reaction(_token())
        record_reaction_used(name)
        names.append(name)
    for a, b in zip(names, names[1:]):
        assert a != b


def test_tentative_draw_does_not_record():
    state = reactions.REACTION_STATE_FILE
    draw_reaction(_token())
    draw_reaction(_token())
    assert not json.loads(open(state).read())["used"]
    name, _ = draw_reaction(_token())
    record_reaction_used(name)
    assert json.loads(open(state).read())["used"] == [name]


def test_recorded_reaction_excluded_after_restart():
    name, _ = draw_reaction(_token())
    record_reaction_used(name)
    # Simulate a restart: empty in-memory deck, keep the state file.
    reset_reaction_deck(clear_file=False)
    names = [draw_reaction(_token())[0] for _ in range(7)]
    assert name not in names


def test_corrupt_state_file_degrades_to_empty_deck(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    monkeypatch.setattr(reactions, "REACTION_STATE_FILE", str(bad))
    reset_reaction_deck(clear_file=False)
    name, _ = draw_reaction(_token())
    assert name in REACTIONS


def test_stale_day_state_file_is_ignored(tmp_path, monkeypatch):
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps({"reset_key": "2000-01-01_07:00",
                                 "used": list(REACTIONS)}))
    monkeypatch.setattr(reactions, "REACTION_STATE_FILE", str(stale))
    reset_reaction_deck(clear_file=False)
    names = [draw_reaction(_token())[0] for _ in range(8)]
    assert sorted(names) == sorted(REACTIONS)


def test_unwritable_state_file_never_crashes(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("file, not dir")
    monkeypatch.setattr(reactions, "REACTION_STATE_FILE",
                        str(blocker / "reactions.json"))
    reset_reaction_deck()
    name, _ = draw_reaction(_token())
    record_reaction_used(name)
    assert name in REACTIONS
