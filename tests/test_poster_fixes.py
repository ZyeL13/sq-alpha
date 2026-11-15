"""Regression tests for the Telegram + scheduling fixes (2026-11-14).

- Telegram is single-attempt (best-effort): retrying after a timeout
  duplicates a message that was actually delivered.
- Daily quota is posted + queued, so the queue cannot overfill and
  burst-fire at the 07:00 WIB reset.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_telegram_single_attempt_on_http_error(monkeypatch):
    from schedulers import poster

    calls = []

    class Resp:
        status_code = 500

    def fake_post(*args, **kwargs):
        calls.append(1)
        return Resp()

    monkeypatch.setattr(poster.requests, "post", fake_post)
    assert poster.post_to_telegram("hello $XYZ", "ALPHA") is False
    assert len(calls) == 1


def test_telegram_single_attempt_on_timeout(monkeypatch):
    from schedulers import poster

    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        raise poster.requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(poster.requests, "post", fake_post)
    assert poster.post_to_telegram("hello $XYZ", "ALPHA") is False
    assert len(calls) == 1


def test_telegram_success_single_call(monkeypatch):
    from schedulers import poster

    calls = []

    class Resp:
        status_code = 200

    def fake_post(*args, **kwargs):
        calls.append(1)
        return Resp()

    monkeypatch.setattr(poster.requests, "post", fake_post)
    assert poster.post_to_telegram("hello $XYZ", "ALPHA") is True
    assert len(calls) == 1


def test_has_daily_quota_counts_queued(monkeypatch):
    from schedulers import orchestrator as orch

    monkeypatch.setattr(orch, "get_today_posts", lambda: 8)
    assert orch.has_daily_quota(1) is True   # 8 + 1 < 10
    assert orch.has_daily_quota(2) is False  # 8 + 2 = 10, full
    monkeypatch.setattr(orch, "get_today_posts", lambda: 10)
    assert orch.has_daily_quota(0) is False


def test_delete_old_posts_cutoff(tmp_path):
    import time

    from storage.scheduled_post_queue import ScheduledPostQueue

    queue = ScheduledPostQueue(db_path=str(tmp_path / "scheduled_queue.db"))
    now = time.time()
    queue.add_post("$OLD overdue 2h", "LOSERS", "OLD", now - 7200)
    queue.add_post("$RECENT overdue 30m", "LOSERS", "RECENT", now - 1800)
    queue.add_post("$FUTURE in 1h", "GAINERS", "FUTURE", now + 3600)

    assert queue.delete_old_posts(5400) == 1
    assert queue.get_post_count() == 2
    due = queue.get_due_posts(limit=10)
    assert [row[3] for row in due] == ["RECENT"]
