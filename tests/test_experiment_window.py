"""Experiment post window (14-day charter): the EXPERIMENT_POST_WINDOW
env var gates scheduling/posting to a WIB "HH:MM-HH:MM" range. When
the flag is unset or unparseable the window is OFF and nothing
changes. No network, no LLM.
"""
import pytest

from datetime import datetime

import schedulers.timing as timing
from config import WIB


@pytest.fixture
def _window(monkeypatch):
    """Point the env var at 07:30-09:30 WIB for one test."""
    monkeypatch.setenv("EXPERIMENT_POST_WINDOW", "07:30-09:30")
    return timing


def _wib(hour, minute=0, day=27):
    return datetime(2026, 11, day, hour, minute, tzinfo=WIB)


def test_active_only_when_parseable(monkeypatch):
    monkeypatch.delenv("EXPERIMENT_POST_WINDOW", raising=False)
    assert timing.experiment_window_active() is False
    for bad in ("", "0730-0930", "07:30", "7:30-9:30x", "25:00-09:30",
                "07:60-09:30", "09:30-07:30", "07:30-07:30", "abc"):
        monkeypatch.setenv("EXPERIMENT_POST_WINDOW", bad)
        assert timing.experiment_window_active() is False, bad
    monkeypatch.setenv("EXPERIMENT_POST_WINDOW", "07:30-09:30")
    assert timing.experiment_window_active() is True


def test_in_window_boundaries(_window):
    assert timing.in_experiment_window(_wib(7, 29)) is False
    assert timing.in_experiment_window(_wib(7, 30)) is True
    assert timing.in_experiment_window(_wib(8, 0)) is True
    assert timing.in_experiment_window(_wib(9, 29)) is True
    assert timing.in_experiment_window(_wib(9, 30)) is False
    assert timing.in_experiment_window(_wib(10, 0)) is False


def test_in_window_inactive(monkeypatch):
    monkeypatch.delenv("EXPERIMENT_POST_WINDOW", raising=False)
    assert timing.in_experiment_window(_wib(8, 0)) is False


def test_next_window_start(_window):
    assert timing.next_experiment_window_start(_wib(6, 0)) == _wib(7, 30)
    # Inside the window the next start is tomorrow's.
    assert timing.next_experiment_window_start(_wib(8, 0)) == _wib(7, 30, day=28)
    assert timing.next_experiment_window_start(_wib(10, 0)) == _wib(7, 30, day=28)


def test_clamp_to_window(_window):
    # Before today's start -> today's start.
    assert timing.clamp_to_experiment_window(
        _wib(6, 0).timestamp()) == _wib(7, 30).timestamp()
    # Inside -> unchanged.
    assert timing.clamp_to_experiment_window(
        _wib(8, 15).timestamp()) == _wib(8, 15).timestamp()
    # After the end -> tomorrow's start.
    assert timing.clamp_to_experiment_window(
        _wib(10, 0).timestamp()) == _wib(7, 30, day=28).timestamp()
    # Exactly at the end counts as after (end is exclusive).
    assert timing.clamp_to_experiment_window(
        _wib(9, 30).timestamp()) == _wib(7, 30, day=28).timestamp()


def test_clamp_inactive_is_noop(monkeypatch):
    monkeypatch.delenv("EXPERIMENT_POST_WINDOW", raising=False)
    ts = _wib(8, 0).timestamp()
    assert timing.clamp_to_experiment_window(ts) == ts


# ------------------------------------------- orchestrator window wiring
def test_schedule_winner_clamps_into_window(tmp_path, monkeypatch):
    """_schedule_winner chains the new post after the last one, then
    clamps it into the window when the flag is active."""
    import llm
    import schedulers.orchestrator as orch
    import storage.posts_csv as posts_csv
    from storage.scheduled_post_queue import ScheduledPostQueue

    monkeypatch.setenv("EXPERIMENT_POST_WINDOW", "07:30-09:30")
    monkeypatch.setattr(posts_csv, "POSTS_CSV_PATH",
                        str(tmp_path / "posts.csv"))
    monkeypatch.setattr(orch, "get_post_delay", lambda: 4800)
    monkeypatch.setattr(orch, "record_memory", lambda *a: None)
    monkeypatch.setattr(orch, "mark_posted", lambda *a, **k: None)
    monkeypatch.setattr(llm, "last_call_meta", {"provider": "", "model": ""})
    # Fixed "now" 05:00 WIB; last post 06:00 -> chained 07:20, which
    # is before the window and clamps to 07:30.
    now = _wib(5, 0).timestamp()
    monkeypatch.setattr(orch.time, "time", lambda: now)

    queue = ScheduledPostQueue(db_path=str(tmp_path / "sq.db"))
    queue.add_post(post="$SEED seeded", category="GAINERS", symbol="SEED",
                   scheduled_time=_wib(6, 0).timestamp())
    draft = orch.Draft(content="$AAA jumped +4.2% to $1.35.",
                       fmt="short", title=None, token={"symbol": "AAA"},
                       category="GAINERS", scores={}, total_score=0.8)
    assert orch._schedule_winner(1, draft, "default", queue) is True
    assert queue.get_last_post_time() == pytest.approx(
        _wib(7, 30).timestamp())


def test_run_pool_round_quota_gate_window_active(tmp_path, monkeypatch):
    """With the window active and the daily quota full (posted +
    queued >= limit), run_pool_round schedules nothing and never
    even collects candidates."""
    import schedulers.orchestrator as orch
    from storage.scheduled_post_queue import ScheduledPostQueue

    monkeypatch.setenv("EXPERIMENT_POST_WINDOW", "07:30-09:30")
    monkeypatch.setattr(orch, "DAILY_POST_LIMIT", 1)
    monkeypatch.setattr(orch, "get_today_posts", lambda: 0)
    monkeypatch.setattr(orch, "can_post", lambda: True)

    queue = ScheduledPostQueue(db_path=str(tmp_path / "sq.db"))
    queue.add_post(post="$SEED seeded", category="GAINERS", symbol="SEED",
                   scheduled_time=_wib(8, 0).timestamp())
    assert queue.get_post_count() == 1  # posted 0 + queued 1 >= limit 1

    class _FakeQueue:
        def __init__(self, items):
            self.items = list(items)

        def get(self, timeout=5):
            if self.items:
                return ("binance", self.items.pop(0))
            return None

    data_queue = _FakeQueue([{"symbol": "AAA", "price": 1.35,
                              "price_change_percent": 4.2,
                              "volume_24h": 1_000_000,
                              "high_24h": 1.4, "low_24h": 1.3}])
    monkeypatch.setattr(orch, "data_queue", data_queue)
    drafted = []
    monkeypatch.setattr(orch, "prepare_draft",
                        lambda *a, **k: drafted.append(1) or None)

    assert orch.run_pool_round(1, queue) is False
    assert queue.get_post_count() == 1  # nothing scheduled
    assert drafted == []  # the gate fires before collection/drafting
    assert len(data_queue.items) == 1  # candidate unconsumed
