"""Variant rotation (spec 5.4): each reaction has 4 illustration
variants; a persisted per-reaction cursor cycles a -> b -> c -> d,
advancing only when a post with that reaction is scheduled.
"""
import json

import pytest

import prompts.reactions as reactions
from prompts.reactions import (
    advance_variant,
    current_variant,
    reset_variant_cursors,
)


@pytest.fixture(autouse=True)
def _isolated_variant_state(tmp_path, monkeypatch):
    monkeypatch.setattr(reactions, "VARIANT_STATE_FILE",
                        str(tmp_path / "variants.json"))
    reset_variant_cursors()
    yield
    reset_variant_cursors()


def test_default_variant_is_a_for_all_reactions():
    for name in reactions.REACTIONS:
        assert current_variant(name) == "a"


def test_advance_cycles_a_b_c_d_a():
    assert current_variant("smug") == "a"
    advance_variant("smug")
    assert current_variant("smug") == "b"
    advance_variant("smug")
    assert current_variant("smug") == "c"
    advance_variant("smug")
    assert current_variant("smug") == "d"
    advance_variant("smug")
    assert current_variant("smug") == "a"


def test_cursors_are_independent_per_reaction():
    advance_variant("smug")
    advance_variant("smug")
    assert current_variant("smug") == "c"
    assert current_variant("shrug") == "a"


def test_peek_does_not_advance():
    assert current_variant("smug") == "a"
    assert current_variant("smug") == "a"


def test_cursor_persists_in_file(tmp_path):
    advance_variant("smug")
    advance_variant("smug")
    data = json.loads(open(reactions.VARIANT_STATE_FILE).read())
    assert data == {"smug": 2}
    # A fresh read (simulated restart) sees the same cursor.
    assert current_variant("smug") == "c"


def test_corrupt_file_falls_back_to_a_and_recovers(tmp_path):
    path = reactions.VARIANT_STATE_FILE
    with open(path, "w") as f:
        f.write("{not json")
    assert current_variant("smug") == "a"
    advance_variant("smug")
    assert current_variant("smug") == "b"


def test_bad_values_in_file_are_ignored():
    path = reactions.VARIANT_STATE_FILE
    with open(path, "w") as f:
        json.dump({"smug": 7, "shrug": "x", "nope": 1, "caution": -1}, f)
    assert current_variant("smug") == "d"  # 7 % 4 == 3
    assert current_variant("shrug") == "a"
    assert current_variant("caution") == "d"  # -1 % 4 == 3


def test_unknown_reaction_yields_a_and_ignores_advance():
    assert current_variant("nope") == "a"
    advance_variant("nope")  # must not raise, must not write
    assert json.loads(open(reactions.VARIANT_STATE_FILE).read()) == {}


def test_unwritable_file_never_crashes(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("file, not dir")
    monkeypatch.setattr(reactions, "VARIANT_STATE_FILE",
                        str(blocker / "variants.json"))
    assert current_variant("smug") == "a"
    advance_variant("smug")  # must not raise
    assert current_variant("smug") == "a"
