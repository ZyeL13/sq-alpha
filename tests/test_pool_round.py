"""JIT pool round (spec 4): collect -> draft -> score -> schedule the
winner, with 429 early-exit, pool-1 skip-scoring, buffer-full sleep,
and None-safe chaining. No network, no LLM — the pipeline pieces are
stubbed; scoring uses the real mechanical scorer.
"""
import time

import pytest

import llm
import schedulers.orchestrator as orch
import storage.posts_csv as posts_csv
from storage.scheduled_post_queue import ScheduledPostQueue

# The real prepare_draft, saved before the harness fixture stubs it —
# the validation-retry tests need the real draft path.
_REAL_PREPARE_DRAFT = orch.prepare_draft


class _FakeQueue:
    def __init__(self, items):
        self.items = list(items)
        self.get_calls = 0

    def get(self, timeout=5):
        self.get_calls += 1
        if self.items:
            return ("binance", self.items.pop(0))
        return None


class _FakeFlag:
    def __init__(self):
        self.waits = []

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return False

    def is_set(self):
        return False


def _token(symbol, **overrides):
    token = {
        "symbol": symbol,
        "price": 1.35,
        "price_change_percent": 4.2,
        "volume_24h": 106_000_000,
        "high_24h": 1.42,
        "low_24h": 1.08,
        "market_cap": 500_000_000,
        "volume_ratio_7d": 3.2,
        "btc_change_24h": 2.1,
    }
    token.update(overrides)
    return token


def _content(symbol):
    # >100 chars so the real validate_post in score_draft accepts it.
    return (f"${symbol} jumped +4.2% to $1.35 as volume ran 3.2x the "
            "7-day average and the move held into the close with "
            "buyers still active.")


@pytest.fixture
def _harness(tmp_path, monkeypatch):
    """Stub the pipeline around run_pool_round. Returns a namespace
    of call recorders + the tmp scheduled queue."""
    import types
    ns = types.SimpleNamespace()
    ns.queue = ScheduledPostQueue(db_path=str(tmp_path / "sq.db"))
    ns.draft_calls = []
    ns.finalize_calls = []
    ns.reactions_recorded = []
    ns.variants_advanced = []
    ns.memory_recorded = []
    ns.news_marked = []
    ns.formats_incremented = []
    ns.totals = {}
    ns.prepare_behavior = {}  # symbol -> "draft" | "fail" | "fail_429"

    monkeypatch.setattr(orch, "can_post", lambda: True)
    monkeypatch.setattr(orch, "normalize_token",
                        lambda raw, source=None: dict(raw))
    monkeypatch.setattr(orch, "classify", lambda token: "GAINERS")
    monkeypatch.setattr(orch, "is_duplicate", lambda *a, **k: False)
    monkeypatch.setattr(orch, "get_memory", lambda symbol: None)
    monkeypatch.setattr(orch, "draw_reaction",
                        lambda token, mem=None: ("smug", "SMUG"))
    monkeypatch.setattr(orch, "format_memory_block", lambda *a: "")
    monkeypatch.setattr(orch, "get_post_delay", lambda: 4800)
    monkeypatch.setattr(llm, "_RATE_LIMIT_HITS", {})

    def _score_token(token, cat):
        total = ns.totals.get(token["symbol"], 0.8)
        return {"passes": True, "total": total, "primary": 0.7,
                "scores": {}}
    monkeypatch.setattr(orch, "score_token", _score_token)

    def _prepare(token, category, scores, reaction=None, memory=None,
                 total_score=0.0, avoid_openers=None):
        ns.draft_calls.append(token["symbol"])
        behavior = ns.prepare_behavior.get(token["symbol"], "draft")
        if behavior == "fail_429":
            llm.mark_rate_limited("groq")
            return None
        if behavior == "fail":
            return None
        return orch.Draft(content=_content(token["symbol"]), fmt="short",
                          title=None, token=token, category=category,
                          scores=scores, total_score=total_score,
                          reaction=reaction[0] if reaction else None)
    monkeypatch.setattr(orch, "prepare_draft", _prepare)

    def _finalize(draft):
        ns.finalize_calls.append(draft.token["symbol"])
        return draft.content, draft.fmt, draft.title, None
    monkeypatch.setattr(orch, "finalize_draft", _finalize)

    monkeypatch.setattr(orch, "record_reaction_used",
                        lambda name: ns.reactions_recorded.append(name))
    monkeypatch.setattr(orch, "advance_variant",
                        lambda name: ns.variants_advanced.append(name))
    monkeypatch.setattr(orch, "record_memory",
                        lambda s, c, t: ns.memory_recorded.append(s))
    monkeypatch.setattr(orch, "mark_news_used",
                        lambda a, s: ns.news_marked.append((a, s)))
    monkeypatch.setattr(orch, "increment_format_count",
                        lambda fmt: ns.formats_incremented.append(fmt))
    # _schedule_winner writes logs/posts.csv for real — point it at
    # a tmp file so the pool tests never touch the repo logs.
    monkeypatch.setattr(posts_csv, "POSTS_CSV_PATH",
                        str(tmp_path / "posts.csv"))
    return ns


def _run(harness, symbols, monkeypatch, pool_size=5, buffer_max=3):
    monkeypatch.setattr(orch, "DRAFT_POOL_SIZE", pool_size)
    monkeypatch.setattr(orch, "SCHEDULE_BUFFER_MAX", buffer_max)
    monkeypatch.setattr(orch, "data_queue",
                        _FakeQueue([_token(s) for s in symbols]))
    return orch.run_pool_round(1, harness.queue)


# ---------------------------------------------------------------- round
def test_round_schedules_highest_scored_draft(_harness, monkeypatch):
    _harness.totals = {"AAA": 0.5, "BBB": 0.9, "CCC": 0.7}
    assert _run(_harness, ["AAA", "BBB", "CCC"], monkeypatch) is True
    assert _harness.queue.get_post_count() == 1
    assert _harness.finalize_calls == ["BBB"]
    assert _harness.draft_calls == ["AAA", "BBB", "CCC"]
    rows = _harness.queue.get_recent_scheduled_posts(5)
    assert rows[0] == _content("BBB")


def test_pool_size_one_skips_scoring(_harness, monkeypatch):
    monkeypatch.setattr(orch, "score_draft",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("scoring must be skipped")))
    assert _run(_harness, ["AAA", "BBB", "CCC"], monkeypatch,
                pool_size=1) is True
    # Collection stops at 1 candidate; only one draft exists.
    assert _harness.draft_calls == ["AAA"]
    assert _harness.queue.get_post_count() == 1


def test_429_early_exit_uses_completed_drafts(_harness, monkeypatch):
    _harness.prepare_behavior = {"BBB": "fail_429"}
    assert _run(_harness, ["AAA", "BBB", "CCC"], monkeypatch) is True
    # The round stopped at BBB: CCC was never drafted.
    assert _harness.draft_calls == ["AAA", "BBB"]
    assert _harness.finalize_calls == ["AAA"]
    assert _harness.queue.get_post_count() == 1


def test_429_with_zero_drafts_schedules_nothing(_harness, monkeypatch):
    _harness.prepare_behavior = {"AAA": "fail_429"}
    assert _run(_harness, ["AAA", "BBB"], monkeypatch) is False
    assert _harness.draft_calls == ["AAA"]
    assert _harness.queue.get_post_count() == 0


def test_ordinary_failures_attempt_all_candidates(_harness, monkeypatch):
    _harness.prepare_behavior = {"AAA": "fail", "BBB": "fail", "CCC": "fail"}
    assert _run(_harness, ["AAA", "BBB", "CCC"], monkeypatch) is False
    assert _harness.draft_calls == ["AAA", "BBB", "CCC"]
    assert _harness.queue.get_post_count() == 0


def test_no_candidates_returns_false(_harness, monkeypatch):
    assert _run(_harness, [], monkeypatch) is False
    assert _harness.draft_calls == []


def test_buffer_full_schedules_nothing(_harness, monkeypatch):
    now = time.time()
    for i, sym in enumerate(["OLD1", "OLD2"]):
        _harness.queue.add_post(post="old", category="GAINERS", symbol=sym,
                                scheduled_time=now + 100 + i)
    monkeypatch.setattr(orch, "prepare_draft",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("no drafting when buffer full")))
    assert _run(_harness, ["AAA"], monkeypatch, buffer_max=2) is False
    assert _harness.queue.get_post_count() == 2


def test_can_post_false_schedules_nothing(_harness, monkeypatch):
    monkeypatch.setattr(orch, "can_post", lambda: False)
    monkeypatch.setattr(orch, "data_queue",
                        _FakeQueue([_token("AAA")]))
    monkeypatch.setattr(orch, "DRAFT_POOL_SIZE", 5)
    monkeypatch.setattr(orch, "SCHEDULE_BUFFER_MAX", 3)
    assert orch.run_pool_round(1, _harness.queue) is False
    assert _harness.queue.get_post_count() == 0


def test_tie_goes_to_earliest_candidate(_harness, monkeypatch):
    assert _run(_harness, ["AAA", "BBB"], monkeypatch) is True
    assert _harness.finalize_calls == ["AAA"]


# -------------------------------------------------------------- chaining
def test_empty_queue_chains_from_now(_harness, monkeypatch):
    before = time.time()
    assert _run(_harness, ["AAA"], monkeypatch, pool_size=1) is True
    due = _harness.queue.get_due_posts(limit=5)
    assert due == []  # scheduled in the future, not due
    nxt = _harness.queue.get_next_post_time()
    assert before + 4700 <= nxt <= before + 4900


def test_nonempty_queue_chains_from_last_post(_harness, monkeypatch):
    now = time.time()
    _harness.queue.add_post(post="old", category="GAINERS", symbol="OLD",
                            scheduled_time=now + 3600)
    assert _run(_harness, ["AAA"], monkeypatch, pool_size=1) is True
    last = _harness.queue.get_last_post_time()
    assert now + 3600 + 4700 <= last <= now + 3600 + 4900


def test_chain_time_unit():
    assert orch._chain_time(None, 1000, 4800) == 5800
    assert orch._chain_time(500, 1000, 4800) == 5800  # past: from now
    assert orch._chain_time(1000, 1000, 4800) == 5800  # due now: from now
    assert orch._chain_time(2000, 1000, 4800) == 6800  # future: chained


# ------------------------------------------------------- winner-only effects
def test_winner_only_side_effects(_harness, monkeypatch):
    _harness.totals = {"AAA": 0.5, "BBB": 0.9}
    assert _run(_harness, ["AAA", "BBB"], monkeypatch) is True
    assert _harness.reactions_recorded == ["smug"]
    assert _harness.variants_advanced == ["smug"]
    assert _harness.memory_recorded == ["BBB"]
    assert _harness.formats_incremented == []  # short posts consume nothing


def test_winner_news_stubs_marked_losers_not(_harness, monkeypatch):
    _harness.totals = {"AAA": 0.5, "BBB": 0.9}
    stub_a = {"link": "https://x/a", "title": "A", "source": "rss"}
    stub_b = {"link": "https://x/b", "title": "B", "source": "rss"}

    def _tokens_with_stubs():
        a = _token("AAA")
        a["news_catalyst"] = "catalyst A"
        a["news_article_keys"] = [stub_a]
        b = _token("BBB")
        b["news_catalyst"] = "catalyst B"
        b["news_article_keys"] = [stub_b]
        return [a, b]

    monkeypatch.setattr(orch, "DRAFT_POOL_SIZE", 5)
    monkeypatch.setattr(orch, "SCHEDULE_BUFFER_MAX", 3)
    monkeypatch.setattr(orch, "is_news_seen", lambda s: False)
    monkeypatch.setattr(orch, "data_queue", _FakeQueue(_tokens_with_stubs()))
    assert orch.run_pool_round(1, _harness.queue) is True
    assert _harness.news_marked == [(stub_b, "BBB")]


def test_stale_catalyst_stripped_before_draft(_harness, monkeypatch):
    seen = {}

    def _prepare(token, category, scores, reaction=None, memory=None,
                 total_score=0.0, avoid_openers=None):
        seen["catalyst"] = token.get("news_catalyst")
        seen["stubs"] = token.get("news_article_keys")
        return orch.Draft(content=_content(token["symbol"]), fmt="short",
                          title=None, token=token, category=category,
                          scores=scores, total_score=total_score,
                          reaction="smug")
    monkeypatch.setattr(orch, "prepare_draft", _prepare)
    monkeypatch.setattr(orch, "is_news_seen", lambda s: True)
    token = _token("AAA")
    token["news_catalyst"] = "old catalyst"
    token["news_article_keys"] = [{"link": "https://x/a", "title": "A"}]
    monkeypatch.setattr(orch, "DRAFT_POOL_SIZE", 1)
    monkeypatch.setattr(orch, "SCHEDULE_BUFFER_MAX", 3)
    monkeypatch.setattr(orch, "data_queue", _FakeQueue([token]))
    assert orch.run_pool_round(1, _harness.queue) is True
    assert seen["catalyst"] is None
    assert seen["stubs"] is None
    assert _harness.news_marked == []


# ----------------------------------------------------------------- sleep
def test_sleep_until_next_post_caps_wait(_harness, monkeypatch):
    flag = _FakeFlag()
    monkeypatch.setattr(orch, "stop_flag", flag)
    now = time.time()
    _harness.queue.add_post(post="old", category="GAINERS", symbol="OLD",
                            scheduled_time=now + 3600)
    orch._sleep_until_next_post(_harness.queue, 30)
    assert flag.waits == [30]


def test_sleep_until_next_post_uses_fire_time_plus_30(_harness, monkeypatch):
    flag = _FakeFlag()
    monkeypatch.setattr(orch, "stop_flag", flag)
    now = time.time()
    _harness.queue.add_post(post="old", category="GAINERS", symbol="OLD",
                            scheduled_time=now + 10)
    orch._sleep_until_next_post(_harness.queue, 1800)
    assert 39 <= flag.waits[0] <= 41


def test_sleep_until_next_post_empty_queue_waits_1s(_harness, monkeypatch):
    flag = _FakeFlag()
    monkeypatch.setattr(orch, "stop_flag", flag)
    orch._sleep_until_next_post(_harness.queue, 1800)
    assert flag.waits == [1.0]


# -------------------------------------------------------------- dispatch
def test_processor_target_follows_flag(monkeypatch):
    monkeypatch.setattr(orch, "JIT_SCHEDULING", True)
    assert orch._processor_target() is orch.processor_worker_jit
    monkeypatch.setattr(orch, "JIT_SCHEDULING", False)
    assert orch._processor_target() is orch.processor_worker


# ------------------------------------------------------- recent scheduled
def test_get_recent_scheduled_posts_newest_first(_harness):
    now = time.time()
    for i, sym in enumerate(["A", "B", "C"]):
        _harness.queue.add_post(post=f"post {sym}", category="GAINERS",
                                symbol=sym, scheduled_time=now + i * 100)
    assert _harness.queue.get_recent_scheduled_posts(2) == ["post C", "post B"]
    assert len(_harness.queue.get_recent_scheduled_posts(10)) == 3
    assert _harness.queue.get_recent_scheduled_posts(5) == [
        "post C", "post B", "post A"]


# ------------------------------------------------- step 1: abstain threshold
def test_abstain_when_best_draft_below_threshold(_harness, monkeypatch):
    # Signal 0.1 -> 4.5; specificity 22.5 (3 cited numbers); freshness
    # 0 (each opener repeats a seeded scheduled post) -> best 27 < 50.
    _harness.totals = {"AAA": 0.1, "BBB": 0.1, "CCC": 0.1}
    now = time.time()
    for i, sym in enumerate(["AAA", "BBB", "CCC"]):
        _harness.queue.add_post(post=_content(sym), category="GAINERS",
                                symbol=sym, scheduled_time=now + 100 + i)
    assert _run(_harness, ["AAA", "BBB", "CCC"], monkeypatch,
                buffer_max=5) is False
    assert _harness.queue.get_post_count() == 3  # only the seeds
    assert _harness.finalize_calls == []


def test_no_abstain_when_best_draft_above_threshold(_harness, monkeypatch):
    # Signal 0.3 -> 13.5; specificity 22.5; freshness 25 -> 61 >= 50.
    _harness.totals = {"AAA": 0.3, "BBB": 0.3, "CCC": 0.3}
    assert _run(_harness, ["AAA", "BBB", "CCC"], monkeypatch) is True
    assert _harness.queue.get_post_count() == 1


# ------------------------------------------------- step 1: validation retry
def _real_draft_harness(_harness, monkeypatch, replies):
    """Real prepare_draft + stubbed llm.generate (in post_generator's
    namespace). Returns the list of prompts the fake generate saw."""
    import generators.post_generator as pg

    calls = []

    def fake_generate(prompt, system_prompt=None, category=None, **kwargs):
        calls.append(prompt)
        return replies.pop(0) if replies else None

    monkeypatch.setattr(pg, "generate", fake_generate)
    monkeypatch.setattr(orch, "prepare_draft", _REAL_PREPARE_DRAFT)
    monkeypatch.setattr(orch, "select_post_format_with_reason",
                        lambda *a, **k: ("short", None))
    monkeypatch.setattr(orch, "get_format_counts", lambda: {})
    return calls


def _valid_reply(symbol):
    import json

    return json.dumps({
        "event": f"{symbol} jumped",
        "fact": "+4.2% to $1.35, volume 3.2x",
        "interpretation": "buyers are showing up",
        "angle": "smug",
        "post": _content(symbol),
    })


def test_pool_validation_retry_schedules_after_fix(_harness, monkeypatch):
    calls = _real_draft_harness(
        _harness, monkeypatch, ["not json at all", _valid_reply("AAA")])
    assert _run(_harness, ["AAA"], monkeypatch, pool_size=1) is True
    assert _harness.queue.get_post_count() == 1
    assert len(calls) == 2
    assert "failed validation: json_invalid" in calls[1]
    rows = _harness.queue.get_recent_scheduled_posts(5)
    assert rows[0] == _content("AAA")


def test_pool_second_validation_failure_skips_draft(_harness, monkeypatch):
    calls = _real_draft_harness(
        _harness, monkeypatch, ["nope", "still nope"])
    assert _run(_harness, ["AAA"], monkeypatch, pool_size=1) is False
    assert _harness.queue.get_post_count() == 0
    assert len(calls) == 2  # one retry, then the draft is skipped
