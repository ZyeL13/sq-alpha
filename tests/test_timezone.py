"""Timezone (WIB) + daily-limit reset coordination — Fase 3 langkah 5d.

Offline: datetimes are faked, the reset sleep is driven by the
module's threading Event, never a real multi-hour wait.
"""
import os
import sqlite3
import sys
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import WIB


class FakeDatetime(datetime):
    """datetime subclass whose now() returns a fixed WIB time."""

    _fixed = datetime(2026, 11, 8, 6, 0, 0, tzinfo=WIB)

    @classmethod
    def now(cls, tz=None):
        return cls._fixed


def _fake_datetime_at(hour):
    class _Fake(FakeDatetime):
        _fixed = datetime(2026, 11, 8, hour, 0, 0, tzinfo=WIB)

    return _Fake


def test_reset_time_is_7am_wib_before_reset(monkeypatch):
    import storage.post_counter as pc

    monkeypatch.setattr(pc, "datetime", _fake_datetime_at(6))
    reset = pc._get_reset_time()
    # Before 07:00 the current period started yesterday at 07:00 WIB.
    assert reset == datetime(2026, 11, 7, 7, 0, 0, tzinfo=WIB)
    assert reset.tzinfo is WIB


def test_reset_time_is_7am_wib_after_reset(monkeypatch):
    import storage.post_counter as pc

    monkeypatch.setattr(pc, "datetime", _fake_datetime_at(8))
    reset = pc._get_reset_time()
    assert reset == datetime(2026, 11, 8, 7, 0, 0, tzinfo=WIB)


def test_seconds_until_reset_counts_to_7am_wib(monkeypatch):
    import storage.post_counter as pc

    monkeypatch.setattr(pc, "datetime", _fake_datetime_at(6))
    assert pc.get_seconds_until_reset() == 3600


def test_session_uses_wib_hour(monkeypatch):
    import schedulers.timing as timing

    cases = [(8, "asia"), (13, "europe"), (19, "overlap"),
             (22, "us_late"), (3, "night")]
    for hour, expected in cases:
        monkeypatch.setattr(timing, "datetime", _fake_datetime_at(hour))
        assert timing.get_current_session() == expected, hour


def test_delete_old_entries_actually_deletes(tmp_path):
    from storage.persistent_queue import PersistentQueue

    q = PersistentQueue(str(tmp_path / "q.db"))
    q.put("binance", {"symbol": "FRESH"})
    conn = sqlite3.connect(str(tmp_path / "q.db"))
    conn.execute(
        "INSERT INTO queue (source, token_data, created_at) VALUES (?, ?, ?)",
        ("binance", '{"symbol": "OLD"}', "2020-01-01 00:00:00"),
    )
    conn.commit()
    conn.close()

    assert q.size() == 2
    deleted = q.delete_old_entries(max_age_hours=24)
    assert deleted == 1
    assert q.size() == 1
    assert q.get() == ("binance", {"symbol": "FRESH"})


def test_check_and_sleep_owner_returns_true_when_stopped(monkeypatch):
    import schedulers.orchestrator as orch

    monkeypatch.setattr(orch, "can_post", lambda: False)
    monkeypatch.setattr(orch, "get_seconds_until_reset", lambda: 3600)
    orch.stop_flag.set()
    try:
        assert orch.check_and_sleep() is True
    finally:
        orch.stop_flag.clear()
        orch._reset_in_progress.clear()


def test_check_and_sleep_waiter_survives_reset(monkeypatch):
    """A non-owner thread waits for the reset instead of breaking.

    This is the regression for the old _shutdown bug: other threads
    used to see the flag and exit their loops permanently.
    """
    import schedulers.orchestrator as orch

    monkeypatch.setattr(orch, "can_post", lambda: False)
    orch._reset_in_progress.set()

    result = {}

    def waiter():
        result["value"] = orch.check_and_sleep()

    t = threading.Thread(target=waiter)
    t.start()
    # Simulate the owner finishing the reset.
    threading.Timer(0.2, orch._reset_in_progress.clear).start()
    t.join(timeout=5)
    assert not t.is_alive()
    assert result["value"] is False
