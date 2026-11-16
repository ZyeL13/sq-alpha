"""Durable per-symbol post memory (spec 5.4): the reaction openers
need to know what the bot last wrote about a token. Missing/corrupt
files degrade to empty memory, never a crash.
"""
import json
import time

import pytest

import storage.memory_store as memory_store
from storage.memory_store import (
    format_memory_block,
    get_memory,
    record_memory,
)


@pytest.fixture(autouse=True)
def _isolated_memory_file(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_store, "MEMORY_FILE",
                        str(tmp_path / "post_memory.json"))


def test_record_and_get_round_trip():
    record_memory("NOVA", 4.2, "$NOVA woke up.\nSecond line here.")
    rec = get_memory("NOVA")
    assert rec["change"] == 4.2
    assert rec["direction"] == "up"
    assert rec["first_line"] == "$NOVA woke up."
    assert abs(rec["time"] - time.time()) < 5


def test_direction_down_and_flat():
    record_memory("AAA", -3.0, "x")
    assert get_memory("AAA")["direction"] == "down"
    record_memory("BBB", 0.0, "x")
    assert get_memory("BBB")["direction"] == "flat"


def test_first_line_truncated_to_120_chars():
    record_memory("NOVA", 1.0, "$NOVA " + "word " * 40)
    assert len(get_memory("NOVA")["first_line"]) == 120


def test_symbol_case_insensitive():
    record_memory("nova", 1.0, "x")
    assert get_memory("NOVA") is not None
    assert get_memory("Nova") is not None


def test_unknown_symbol_is_none():
    assert get_memory("NEVERPOSTED") is None


def test_rerecord_replaces_old_record():
    record_memory("NOVA", 1.0, "first")
    record_memory("NOVA", -2.0, "second")
    rec = get_memory("NOVA")
    assert rec["change"] == -2.0
    assert rec["first_line"] == "second"


def test_prune_entries_older_than_30_days(tmp_path):
    old = time.time() - 31 * 24 * 3600
    recent = time.time() - 24 * 3600
    path = memory_store.MEMORY_FILE
    with open(path, "w") as f:
        json.dump({
            "OLD": {"time": old, "change": 1.0, "direction": "up",
                    "first_line": "old"},
            "NEW": {"time": recent, "change": 1.0, "direction": "up",
                    "first_line": "new"},
        }, f)
    record_memory("FRESH", 1.0, "fresh")
    assert get_memory("OLD") is None
    assert get_memory("NEW") is not None
    assert get_memory("FRESH") is not None


def test_corrupt_file_recovers(tmp_path):
    path = memory_store.MEMORY_FILE
    with open(path, "w") as f:
        f.write("{not json")
    assert get_memory("NOVA") is None
    record_memory("NOVA", 1.0, "recovered")
    assert get_memory("NOVA")["first_line"] == "recovered"


def test_non_dict_file_is_empty(tmp_path):
    path = memory_store.MEMORY_FILE
    with open(path, "w") as f:
        f.write("[1, 2, 3]")
    assert get_memory("NOVA") is None


def test_unwritable_path_never_raises(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("file, not dir")
    monkeypatch.setattr(memory_store, "MEMORY_FILE",
                        str(blocker / "post_memory.json"))
    record_memory("NOVA", 1.0, "x")  # must not raise
    assert get_memory("NOVA") is None


def test_format_memory_block():
    # 2026-11-15 10:00 WIB = 03:00 UTC.
    rec = {"time": 1794711600, "change": 5.0, "direction": "up",
           "first_line": "$NOVA woke up."}
    block = format_memory_block(rec, "NOVA", -2.5)
    assert block == ("You last wrote about $NOVA on 15 Nov 2026 when it "
                     "was +5.0% ($NOVA woke up.). Now it is -2.5%.")


def test_format_memory_block_without_record_or_line():
    assert format_memory_block(None, "NOVA", 1.0) == ""
    rec = {"time": 1794711600, "change": 1.0, "first_line": ""}
    assert "Now it is +1.0%." in format_memory_block(rec, "NOVA", 1.0)


def test_format_memory_block_bad_record_never_raises():
    assert format_memory_block({"time": "n/a"}, "NOVA", 1.0) == ""
