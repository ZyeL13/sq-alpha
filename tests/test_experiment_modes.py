"""Worker C — experiment modes, question gate, rotation, window gate.

No network, no LLM — generation is stubbed where the loop is
exercised. Rotation tests live here (not in
test_experiment_window.py, which covers the 6 timing helpers).
"""
import csv

import pytest

import schedulers.experiment as exp


@pytest.fixture
def _window(monkeypatch):
    monkeypatch.setenv("EXPERIMENT_POST_WINDOW", "07:30-09:30")
    monkeypatch.delenv("EXPERIMENT_FORMAT", raising=False)
    return exp


def _write_csv(path, modes):
    """A posts.csv with one row per mode in `modes` (plus a header
    and one non-experiment row, which must not count)."""
    import storage.posts_csv as posts_csv

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(posts_csv.COLUMNS)
        for i, mode in enumerate(modes):
            row = [""] * len(posts_csv.COLUMNS)
            row[0] = f"2026-11-27 08:0{i}:00"
            row[1] = f"T{i}"
            row[11] = mode
            writer.writerow(row)
        row = [""] * len(posts_csv.COLUMNS)
        row[1] = "PLAIN"
        row[11] = ""
        writer.writerow(row)


# ------------------------------------------- generate_post mode wiring
def _xyz_token():
    return {"symbol": "XYZ", "price": 1.50, "price_change_percent": 5.0,
            "volume_24h": 1_000_000, "range_position": 0.5}


def _mode_reply(post, angle="smug"):
    import json

    return json.dumps({
        "event": "XYZ climbed",
        "fact": "+5.0% to $1.50 on $1.0M volume",
        "interpretation": "buyers are showing up steadily",
        "angle": angle,
        "post": post,
    })


def _stub_pg_generate(monkeypatch, replies):
    import generators.post_generator as pg

    calls = []

    def fake(prompt, system_prompt=None, category=None, **kwargs):
        calls.append(prompt)
        assert kwargs.get("output_format") == "json"
        assert kwargs.get("max_tokens") == 1200
        return replies.pop(0) if replies else None

    monkeypatch.setattr(pg, "generate", fake)
    return calls


_PULSE_NO_Q = ("$XYZ climbed +5.0% to $1.50 on $1.0M of volume.\n"
               "No catalyst in sight, just steady buying.\n\n"
               "Buyers kept showing up near the highs all session long.")
_PULSE_WITH_Q = (_PULSE_NO_Q + " $XYZ at $1.50 — bounce or lower low first?")


def test_build_prompt_mode_block(monkeypatch):
    from generators.post_generator import build_prompt

    prompt = build_prompt(_xyz_token(), "GAINERS", mode="pulse")
    assert "MODE: Market Pulse" in prompt
    assert "$XYZ + the fact" in prompt
    assert "at most 2 lines, each line at most 90 characters" in prompt
    assert "ONE specific discussion question" in prompt
    # The mode sets the ending rule to the closing-question rule.
    assert "End the post with a closing question" in prompt
    # Flag off: no mode block, no forced question.
    plain = build_prompt(_xyz_token(), "GAINERS")
    assert "MODE:" not in plain
    assert "ONE specific discussion question" not in plain
    with pytest.raises(ValueError):
        build_prompt(_xyz_token(), "GAINERS", mode="deep-signal")


def test_generate_post_mode_retries_on_missing_question(monkeypatch):
    from generators.post_generator import generate_post

    calls = _stub_pg_generate(
        monkeypatch, [_mode_reply(_PULSE_NO_Q), _mode_reply(_PULSE_WITH_Q)])
    result = generate_post(_xyz_token(), "GAINERS", {},
                           reaction=("smug", "SMUG TEXT"), mode="pulse")
    assert result is not None
    # The exactly-1-cashtag cleaner rewrites the question's $XYZ to
    # "the token" after the mode check passed (the check runs on the
    # pre-clean text, where the question still names the token).
    assert result["post"] == _PULSE_WITH_Q.replace(
        "$XYZ at $1.50", "the token at $1.50")
    assert len(calls) == 2
    assert "mode_question_missing" in calls[1]
    # The retry prompt still carries the mode block (built from the
    # same prompt, not a mode-less fallback).
    assert "MODE: Market Pulse" in calls[1]


def test_generate_post_mode_skips_after_second_failure(monkeypatch):
    from generators.post_generator import generate_post

    calls = _stub_pg_generate(
        monkeypatch, [_mode_reply(_PULSE_NO_Q), _mode_reply(_PULSE_NO_Q)])
    assert generate_post(_xyz_token(), "GAINERS", {},
                         reaction=("smug", "SMUG TEXT"),
                         mode="pulse") is None
    assert len(calls) == 2  # one retry, then skip — never more


# ---------------------------------------- longform require_question
def _pyr_longform_setup(monkeypatch, replies):
    import generators.post_generator as pg
    from schedulers.snapshot import CardSnapshot

    token = {"symbol": "PYR", "price": 0.0210,
             "price_change_percent": -48.8, "high_24h": 0.0470,
             "low_24h": 0.0190, "volume_24h": 500_000,
             "range_position": 0.07}
    closes = [0.0408, 0.0420, 0.0445, 0.0470, 0.0455, 0.0430, 0.0410,
              0.0390, 0.0375, 0.0360, 0.0340, 0.0325, 0.0310, 0.0295,
              0.0280, 0.0265, 0.0250, 0.0235, 0.0220, 0.0215, 0.0190,
              0.0195, 0.0205, 0.0210]
    snapshot = CardSnapshot(token=dict(token, btc_change_24h=-1.7),
                            closes=closes, volume_7d_avg=833333.33,
                            btc_change=-1.7)
    calls = []

    def fake_generate(prompt, system_prompt=None, category=None,
                      max_tokens=None, **kw):
        calls.append(prompt)
        pg.llm.last_call_meta = {"provider": "test", "model": "test-model",
                                 "finish_reason": "stop"}
        return replies.pop(0) if replies else None

    monkeypatch.setattr(pg, "generate", fake_generate)
    monkeypatch.setattr(pg, "is_similar_to_recent", lambda c: False)
    monkeypatch.setattr(pg, "add_to_recent", lambda c: None)
    return pg, token, snapshot, calls


def _good_article(question=False):
    import copy
    import json

    with open("tests/fixtures/pyr_article_good.json") as f:
        article = json.load(f)
    if question:
        article = copy.deepcopy(article)
        conclusion = article["conclusion"].rstrip()
        assert conclusion.endswith(".")
        article["conclusion"] = conclusion[:-1] + "?"
    return article


def test_longform_question_gate_retries_then_passes(monkeypatch):
    import json

    pg, token, snapshot, calls = _pyr_longform_setup(
        monkeypatch, [json.dumps(_good_article(question=False)),
                      json.dumps(_good_article(question=True))])
    result = pg.generate_longform(token, "LOSERS", {}, snapshot=snapshot,
                                  require_question=True)
    assert result is not None
    assert len(calls) == 2
    assert "CONCLUSION must end with one specific discussion question" \
        in calls[1]
    # The first prompt already carries the question line.
    assert "CONCLUSION must end with one specific discussion question" \
        in calls[0]


def test_longform_question_gate_skips_after_second_failure(monkeypatch):
    import json

    pg, token, snapshot, calls = _pyr_longform_setup(
        monkeypatch, [json.dumps(_good_article(question=False)),
                      json.dumps(_good_article(question=False))])
    assert pg.generate_longform(token, "LOSERS", {}, snapshot=snapshot,
                                require_question=True) is None
    assert len(calls) == 2


def test_longform_require_question_false_is_todays_behavior(monkeypatch):
    import json

    pg, token, snapshot, calls = _pyr_longform_setup(
        monkeypatch, [json.dumps(_good_article(question=False))])
    result = pg.generate_longform(token, "LOSERS", {}, snapshot=snapshot)
    assert result is not None
    assert len(calls) == 1
    # No question line in the prompt when the flag is off.
    assert "one specific discussion question" not in calls[0]


def test_build_longform_prompt_question_line_keeps_contracts():
    from generators.post_generator import build_longform_prompt

    from tests.test_article_redesign import PYR_TOKEN

    prompt = build_longform_prompt(PYR_TOKEN, "LOSERS", {},
                                   require_question=True)
    assert prompt.lower().count(
        "conclusion must end with one specific discussion question") == 1
    # A's contract: each section job stated once, each §3.1
    # principle at most once — the added line repeats none of them.
    lowered = prompt.lower()
    assert lowered.count("restate the stance and the single condition "
                         "to watch") == 1
    assert lowered.count("never invent") <= 1
def test_pulse_headline_rule():
    from generators.quality_gate import validate_mode_post

    good = ("$XYZ climbed +5.0% to $1.50 on $1.0M of volume.\n"
            "No catalyst in sight — so who is buying?\n\n"
            "The tape stayed firm after the move, buyers still active "
            "into the close. $XYZ at $1.50 — bounce or lower low first?")
    assert validate_mode_post(good, "XYZ", "pulse") == (True, "")
    # 3-line headline block (no blank line before the third line).
    three = ("$XYZ climbed +5.0% to $1.50 on $1.0M of volume.\n"
             "No catalyst in sight.\n"
             "A third headline line here.\n\n"
             "Body text follows here. $XYZ at $1.50 — bounce or lower?")
    assert validate_mode_post(three, "XYZ", "pulse") == (
        False, "mode_pulse_headline_too_many_lines")
    # Line 1 over 90 chars.
    long1 = ("$XYZ " + "x" * 95 + "\nHook line here.\n\n"
             "Body text follows here. $XYZ at $1.50 — bounce or lower?")
    assert validate_mode_post(long1, "XYZ", "pulse") == (
        False, "mode_pulse_headline_too_long")
    # Missing second line (single-line headline block).
    one = ("$XYZ climbed +5.0% to $1.50 on $1.0M of volume.\n\n"
           "Body text follows here. $XYZ at $1.50 — bounce or lower?")
    assert validate_mode_post(one, "XYZ", "pulse") == (
        False, "mode_pulse_headline_missing_second_line")


def test_question_gate():
    from generators.quality_gate import validate_mode_post

    no_q = ("$XYZ climbed +5.0% to $1.50 on $1.0M of volume.\n"
            "No catalyst in sight.\n\n"
            "The tape stayed firm after the move.")
    assert validate_mode_post(no_q, "XYZ", "pulse") == (
        False, "mode_question_missing")
    assert validate_mode_post(no_q, "XYZ", "contrarian") == (
        False, "mode_question_missing")


def test_contrarian_falsifiability():
    from generators.quality_gate import validate_mode_post

    base = ("Everyone says $XYZ is dead money after the fade. "
            "Volume is up 2.1x the 7-day average while the price held "
            "its range, so the sellers are not in control here. "
            "The read is wrong if the token closes below $1.20 "
            "on heavy volume — what would change your mind?")
    assert validate_mode_post(base, "XYZ", "contrarian") == (True, "")
    no_phrase = base.replace(
        "The read is wrong if the token closes below $1.20 "
        "on heavy volume — what would change your mind?",
        "The read stands on its own — what would change your mind?")
    # "what would change your mind?" alone is not a falsifiability
    # phrase; the check needs one of the listed phrases.
    assert "wrong if" not in no_phrase.lower()
    assert validate_mode_post(no_phrase, "XYZ", "contrarian") == (
        False, "mode_contrarian_no_falsifiability")


def test_onchain_number_and_watch():
    from generators.quality_gate import validate_mode_post

    good = ("Burns hit 500K CAKE a week while daily emission fell to "
            "22,500 — net emission is now negative. Revenue runs "
            "$27M a year and the DEX holds 82% of BNB Chain share. "
            "Which burn is moving a price right now, and what level "
            "should we watch next?")
    assert validate_mode_post(good, "CAKE", "onchain") == (True, "")
    no_number = ("Burns are high every week while emission keeps "
                 "falling — net emission is now negative. Revenue runs "
                 "strong and the DEX holds most of the chain share. "
                 "Which burn is moving a price, and what should we "
                 "watch next?")
    assert validate_mode_post(no_number, "CAKE", "onchain") == (
        False, "mode_onchain_no_number")
    no_watch = ("Burns hit 500K CAKE a week while daily emission fell "
                "to 22,500 — net emission is now negative. Revenue "
                "runs $27M a year. Which burn is moving a price "
                "right now — name it with the weekly number?")
    assert validate_mode_post(no_watch, "CAKE", "onchain") == (
        False, "mode_onchain_no_watch_clause")


def test_article_headline_cap_is_gate5():
    # Article headline rule (audit §G.1/G.2): the article JSON
    # headline is a single line <= 90 chars — enforced by A's gate
    # 5, not by the short-form headline helper. The good fixture
    # passes; a 91-char headline fails gate 5.
    import copy

    from generators.json_validate import validate_article_json

    with open("tests/fixtures/pyr_article_good.json") as f:
        import json

        article = json.load(f)
    with open("tests/fixtures/pyr_research_pack.json") as f:
        pack = json.load(f)
    ok, _, _ = validate_article_json(
        article, pack["facts"], pack)
    assert ok is True
    bad = copy.deepcopy(article)
    bad["headline"] = "x" * 91
    ok, reason, gate = validate_article_json(bad, pack["facts"], pack)
    assert ok is False and gate == "5"
    assert reason == "headline_too_long"
def test_rotation_count_based_day_plan(tmp_path, _window):
    path = str(tmp_path / "posts.csv")
    _write_csv(path, [])
    assert exp.experiment_post_count(path) == 0
    plan = exp.current_day_plan(path)
    assert plan["mode"] == "deep-signal"
    assert plan["visual"] == "banner"
    assert plan["hypothesis"] == (
        "new long-form + specific question earns replies")
    assert plan["variable_tested"] == "format=Deep Signal"

    _write_csv(path, ["deep-signal"])
    assert exp.current_day_plan(path)["mode"] == "pulse"
    assert exp.current_day_plan(path)["visual"] == "sketchnote card"

    _write_csv(path, ["deep-signal", "pulse"])
    plan = exp.current_day_plan(path)
    assert plan["mode"] == "contrarian"
    assert plan["visual"] == "annotated chart"

    _write_csv(path, ["deep-signal", "pulse", "contrarian",
                      "deep-signal", "onchain"])
    plan = exp.current_day_plan(path)
    assert plan["mode"] == "pulse"  # Day 6: chart variant
    assert plan["visual"] == "chart"
    assert plan["variable_tested"] == "visual=chart"


def test_rotation_phase2_fallback_and_visual_parity(tmp_path, _window):
    path = str(tmp_path / "posts.csv")
    # 7 posts -> Phase 2, index 7: schedule[0] mode, odd -> banner.
    _write_csv(path, ["deep-signal"] * 7)
    plan = exp.current_day_plan(path)
    assert plan["mode"] == "deep-signal"
    assert plan["visual"] == "banner"
    assert plan["variable_tested"] == "visual=banner"
    # 8 posts -> index 8: schedule[1] mode, even -> chart.
    _write_csv(path, ["deep-signal"] * 8)
    plan = exp.current_day_plan(path)
    assert plan["mode"] == "pulse"
    assert plan["visual"] == "chart"
    # 14 posts -> index 14: schedule[0] again, even -> chart.
    _write_csv(path, ["deep-signal"] * 14)
    plan = exp.current_day_plan(path)
    assert plan["mode"] == "deep-signal"
    assert plan["visual"] == "chart"


def test_rotation_override_respected(tmp_path, _window, monkeypatch):
    path = str(tmp_path / "posts.csv")
    _write_csv(path, [])
    monkeypatch.setenv("EXPERIMENT_FORMAT", "contrarian")
    plan = exp.current_day_plan(path)
    assert plan["mode"] == "contrarian"
    assert plan["hypothesis"] == (
        "manual override EXPERIMENT_FORMAT=contrarian")
    assert plan["variable_tested"] == "format=contrarian"
    # Override changes the format only: Day 1's visual stays banner.
    assert plan["visual"] == "banner"
    # Invalid override is ignored, never a crash or a new mode.
    monkeypatch.setenv("EXPERIMENT_FORMAT", "bogus")
    assert exp.current_day_plan(path)["mode"] == "deep-signal"


def test_rotation_inactive_without_window(tmp_path, monkeypatch):
    monkeypatch.delenv("EXPERIMENT_POST_WINDOW", raising=False)
    path = str(tmp_path / "posts.csv")
    _write_csv(path, [])
    assert exp.experiment_active() is False
    assert exp.current_day_plan(path) is None


def test_rotation_missing_csv_counts_zero(tmp_path, _window):
    missing = str(tmp_path / "no-such.csv")
    assert exp.experiment_post_count(missing) == 0
    assert exp.current_day_plan(missing)["mode"] == "deep-signal"


def test_rotation_malformed_rows_skipped(tmp_path, _window):
    import storage.posts_csv as posts_csv

    path = str(tmp_path / "posts.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(posts_csv.COLUMNS)
        for symbol, mode in (("AAA", "pulse"), ("BBB", "onchain")):
            row = [""] * len(posts_csv.COLUMNS)
            row[0] = "2026-11-27 08:00:00"
            row[1] = symbol
            row[11] = mode
            writer.writerow(row)
        # A short row (fewer fields than the header): DictReader
        # yields mode=None for it — skipped, never counted/crashing.
        writer.writerow(["this", "is", "a", "malformed", "row"])
    assert exp.experiment_post_count(path) == 2
    plan = exp.current_day_plan(path)
    assert plan["mode"] == "contrarian"  # index 2 -> Day 3


# ------------------------------------------- experiment-log columns
def test_schedule_winner_writes_experiment_columns(tmp_path, monkeypatch):
    import csv

    import llm
    import schedulers.orchestrator as orch
    import storage.posts_csv as posts_csv
    from storage.scheduled_post_queue import ScheduledPostQueue

    monkeypatch.delenv("EXPERIMENT_POST_WINDOW", raising=False)
    monkeypatch.setattr(posts_csv, "POSTS_CSV_PATH",
                        str(tmp_path / "posts.csv"))
    monkeypatch.setattr(orch, "get_post_delay", lambda: 4800)
    monkeypatch.setattr(orch, "record_memory", lambda *a: None)
    monkeypatch.setattr(orch, "mark_posted", lambda *a, **k: None)
    monkeypatch.setattr(llm, "last_call_meta", {"provider": "", "model": ""})

    queue = ScheduledPostQueue(db_path=str(tmp_path / "sq.db"))
    draft = orch.Draft(content="$AAA jumped +4.2% to $1.35.",
                       fmt="short", title=None, token={"symbol": "AAA"},
                       category="GAINERS", scores={}, total_score=0.8,
                       mode="pulse", hypothesis="hook strength",
                       variable_tested="format=Market Pulse, headline fact+hook",
                       visual="sketchnote card")
    assert orch._schedule_winner(1, draft, "default", queue) is True
    # A non-experiment draft leaves the columns blank.
    plain = orch.Draft(content="$BBB jumped +4.2% to $1.35.",
                       fmt="short", title=None, token={"symbol": "BBB"},
                       category="GAINERS", scores={}, total_score=0.8)
    assert orch._schedule_winner(1, plain, "default", queue) is True

    with open(tmp_path / "posts.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["symbol"] == "AAA"
    assert rows[0]["mode"] == "pulse"
    assert rows[0]["hypothesis"] == "hook strength"
    assert rows[0]["variable_tested"] == (
        "format=Market Pulse, headline fact+hook")
    assert rows[1]["symbol"] == "BBB"
    assert rows[1]["mode"] == ""
    assert rows[1]["hypothesis"] == ""
    assert rows[1]["variable_tested"] == ""


# ------------------------------------------- pool-round day-plan wiring
def test_run_pool_round_passes_day_plan_once(tmp_path, monkeypatch):
    import llm
    import schedulers.orchestrator as orch
    import storage.posts_csv as posts_csv
    from storage.scheduled_post_queue import ScheduledPostQueue

    # Window on, empty CSV -> Day 1 deep-signal.
    monkeypatch.setenv("EXPERIMENT_POST_WINDOW", "07:30-09:30")
    monkeypatch.delenv("EXPERIMENT_FORMAT", raising=False)
    monkeypatch.setattr(posts_csv, "POSTS_CSV_PATH",
                        str(tmp_path / "posts.csv"))
    monkeypatch.setattr(orch, "can_post", lambda: True)
    monkeypatch.setattr(orch, "get_today_posts", lambda: 0)
    monkeypatch.setattr(orch, "DAILY_POST_LIMIT", 10)
    monkeypatch.setattr(orch, "DRAFT_POOL_SIZE", 1)
    monkeypatch.setattr(orch, "get_post_delay", lambda: 4800)
    monkeypatch.setattr(orch, "get_memory", lambda symbol: None)
    monkeypatch.setattr(orch, "draw_reaction",
                        lambda token, mem=None: ("smug", "SMUG"))
    monkeypatch.setattr(orch, "format_memory_block", lambda *a: "")
    monkeypatch.setattr(orch, "record_memory", lambda *a: None)
    monkeypatch.setattr(orch, "mark_posted", lambda *a, **k: None)
    monkeypatch.setattr(llm, "last_call_meta", {"provider": "", "model": ""})

    token = {"symbol": "AAA", "price": 1.35, "price_change_percent": 4.2,
             "volume_24h": 1_000_000, "high_24h": 1.4, "low_24h": 1.3}
    monkeypatch.setattr(orch, "_collect_candidates",
                        lambda wid, size: [(token, "GAINERS",
                                            {"scores": {}, "total": 0.8},
                                            "default")])
    seen = {}
    calls = {"n": 0}

    def _fake_prepare(*a, **k):
        seen.update(k)
        return orch.Draft(content="$AAA jumped.", fmt="short", title=None,
                          token=token, category="GAINERS", scores={},
                          total_score=0.8, reaction="smug")

    monkeypatch.setattr(orch, "prepare_draft", _fake_prepare)
    monkeypatch.setattr(orch, "finalize_draft",
                        lambda d: (d.content, d.fmt, d.title, None))
    real_plan = orch._experiment.current_day_plan
    monkeypatch.setattr(orch._experiment, "current_day_plan",
                        lambda *a, **k: calls.update(n=calls["n"] + 1)
                        or real_plan(*a, **k))

    queue = ScheduledPostQueue(db_path=str(tmp_path / "sq.db"))
    assert orch.run_pool_round(1, queue) is True
    assert calls["n"] == 1  # computed once per round, not per token
    assert seen["mode"] == "deep-signal"
    assert seen["day_plan"]["mode"] == "deep-signal"
    assert seen["day_plan"]["visual"] == "banner"


# ------------------------------------------- window gate, end-to-end
# B's test_experiment_window.py covers the 6 timing helpers + the
# _schedule_winner clamp + the JIT quota gate. These are the missing
# end-to-end cases: the poster holds outside the window (never
# claims), and flag-off poster behaviour is today's behaviour.
def test_poster_holds_outside_window(monkeypatch):
    import threading

    import schedulers.orchestrator as orch

    monkeypatch.setenv("EXPERIMENT_POST_WINDOW", "07:30-09:30")
    monkeypatch.setattr(orch, "check_and_sleep", lambda: False)
    monkeypatch.setattr(orch, "can_post", lambda: True)
    # Deterministic "outside": the helpers are stubbed, not the clock.
    monkeypatch.setattr(orch, "in_experiment_window", lambda now=None: False)
    nxt_calls = []
    from datetime import datetime

    from config import WIB

    def _next_start(now=None):
        nxt_calls.append(1)
        return datetime(2026, 11, 28, 7, 30, tzinfo=WIB)

    monkeypatch.setattr(orch, "next_experiment_window_start", _next_start)

    class _FakeQueue:
        def __init__(self):
            self.claims = 0

        def get_post_count(self):
            return 0

        def get_next_post_time(self):
            return None

        def delete_old_posts(self, age):
            return 0

        def claim_due_post(self):
            self.claims += 1
            return None

    queue = _FakeQueue()
    monkeypatch.setattr(orch, "ScheduledPostQueue", lambda: queue)
    assert orch.stop_flag.is_set() is False
    timer = threading.Timer(0.2, orch.stop_flag.set)
    try:
        timer.start()
        orch.poster_worker()
    finally:
        timer.cancel()
        orch.stop_flag.clear()
    assert nxt_calls, "the hold branch never ran"
    assert queue.claims == 0  # held WITHOUT claiming


def test_poster_flag_off_posts_as_today(monkeypatch):
    import schedulers.orchestrator as orch

    monkeypatch.delenv("EXPERIMENT_POST_WINDOW", raising=False)
    monkeypatch.setattr(orch, "check_and_sleep", lambda: False)
    monkeypatch.setattr(orch, "can_post", lambda: True)
    monkeypatch.setattr(orch.time, "sleep", lambda s: None)
    monkeypatch.setattr(orch, "mark_posted", lambda *a, **k: None)
    posted = []
    monkeypatch.setattr(orch, "post_to_targets",
                        lambda **k: posted.append(k) or True)

    class _FakeQueue:
        def __init__(self):
            self.claims = 0

        def get_post_count(self):
            return 0

        def get_next_post_time(self):
            return None

        def delete_old_posts(self, age):
            return 0

        def claim_due_post(self):
            self.claims += 1
            if self.claims == 1:
                # Claim one due post, then stop after it posts.
                orch.stop_flag.set()
                return (1, "$AAA jumped.", "GAINERS", "AAA", "default",
                        "asia", "test", "short", None, None)
            return None

    queue = _FakeQueue()
    monkeypatch.setattr(orch, "ScheduledPostQueue", lambda: queue)
    try:
        orch.poster_worker()
    finally:
        orch.stop_flag.clear()
    assert queue.claims == 1
    assert len(posted) == 1
    assert posted[0]["symbol"] == "AAA"
