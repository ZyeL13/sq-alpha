"""Tests for the atomic cross-process claim (Fix 4, 2026-11-15).

claim_due_post() selects the earliest due row and deletes it in ONE
SQLite transaction (BEGIN IMMEDIATE), so two processes sharing the
queue.db can never claim the same row.
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage.scheduled_post_queue import ScheduledPostQueue


def _add(queue, symbol, scheduled_time, **kwargs):
    queue.add_post(f"${symbol} test post body", "GAINERS", symbol, scheduled_time, **kwargs)


def test_claim_returns_earliest_due_and_removes_it(tmp_path):
    queue = ScheduledPostQueue(db_path=str(tmp_path / "q.db"))
    now = time.time()
    _add(queue, "EARLY", now - 100, format="image", title="t", image_paths=["/tmp/a.png"])
    _add(queue, "LATE", now - 10)
    _add(queue, "FUTURE", now + 3600)

    first = queue.claim_due_post()
    assert first is not None
    assert first[3] == "EARLY"
    assert first[7] == "image"          # format preserved
    assert first[8] == "t"              # title preserved
    assert first[9] == ["/tmp/a.png"]   # image_paths JSON-decoded
    assert queue.get_post_count() == 2

    second = queue.claim_due_post()
    assert second is not None and second[3] == "LATE"
    assert queue.get_post_count() == 1

    assert queue.claim_due_post() is None  # only the future row left
    assert queue.get_post_count() == 1


def test_claim_returns_none_when_empty(tmp_path):
    queue = ScheduledPostQueue(db_path=str(tmp_path / "q.db"))
    assert queue.claim_due_post() is None


def test_concurrent_claims_never_return_same_row(tmp_path):
    db_path = str(tmp_path / "q.db")
    queue = ScheduledPostQueue(db_path=db_path)
    now = time.time()
    for i in range(20):
        _add(queue, f"T{i:02d}", now - 100 + i)

    # Separate instances = separate connections, like two processes.
    # Created up front so table init cannot race with the claims.
    queues = [ScheduledPostQueue(db_path=db_path) for _ in range(2)]
    barrier = threading.Barrier(2)
    claimed_ids = []
    errors = []

    def worker(own_queue):
        try:
            barrier.wait(timeout=10)
            while True:
                row = own_queue.claim_due_post()
                if row is None:
                    return
                claimed_ids.append(row[0])
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(q,)) for q in queues]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors
    assert len(claimed_ids) == 20
    assert len(set(claimed_ids)) == 20
    assert ScheduledPostQueue(db_path=db_path).get_post_count() == 0
