"""Experiment rotation (14-day charter, audit §F.4).

Phase 1 (Days 1-7) rotates the four formats in a fixed order; the
day plan is derived from the COUNT of experiment posts already
logged in logs/posts.csv, so no state file is needed and a restart
cannot lose the rotation. Phase 2 (Day 8+, index >= 7) keeps
rotating the same schedule as a safe fallback — NO winner logic
lives in code: the Phase 2 format is a human decision recorded via
the EXPERIMENT_FORMAT env var, which also overrides the format on
any day. The Day-12 second post (10:30-12:00 WIB poll/question
post, exploratory n=1) is a manual action and is NOT implemented
here.

The experiment flag IS the post window flag: the experiment is
active exactly when EXPERIMENT_POST_WINDOW parses (see
schedulers/timing.py). When inactive, current_day_plan returns
None and the orchestrator behaves exactly as today.
"""
import csv
import os

from schedulers.timing import experiment_window_active
from storage import posts_csv

EXPERIMENT_MODES = ("deep-signal", "pulse", "contrarian", "onchain")
_EXPERIMENT_MODE_SET = frozenset(EXPERIMENT_MODES)
EXPERIMENT_FORMAT_ENV = "EXPERIMENT_FORMAT"

# Visuals that require an image (banner / chart / sketchnote card).
# The orchestrator forces a snapshot + card-type selection for a
# short draft when the day plan's visual is one of these.
IMAGE_VISUALS = frozenset(
    {"banner", "chart", "annotated chart", "sketchnote card"})

# Phase 1 schedule (audit §F.4), index 0-6 = Days 1-7. Hypotheses
# and variables are the audit's, in the brief's "format=<Name>"
# shape; the visual is the audit's per-day visual.
EXPERIMENT_SCHEDULE = (
    {"mode": "deep-signal",
     "hypothesis": "new long-form + specific question earns replies",
     "variable_tested": "format=Deep Signal",
     "visual": "banner"},
    {"mode": "pulse",
     "hypothesis": "hook strength",
     "variable_tested": "format=Market Pulse, headline fact+hook",
     "visual": "sketchnote card"},
    {"mode": "contrarian",
     "hypothesis": "opinion discussability",
     "variable_tested": "format=Contrarian",
     "visual": "annotated chart"},
    {"mode": "deep-signal",
     "hypothesis": "repeatability of Deep Signal",
     "variable_tested": "format=Deep Signal (repeat)",
     "visual": "banner"},
    {"mode": "onchain",
     "hypothesis": "numbers-first format",
     "variable_tested": "format=On-chain Watch",
     "visual": "chart"},
    {"mode": "pulse",
     "hypothesis": "Pulse with chart vs Pulse with card (Day 2)",
     "variable_tested": "visual=chart",
     "visual": "chart"},
    {"mode": "contrarian",
     "hypothesis": "repeatability of Contrarian",
     "variable_tested": "format=Contrarian (repeat)",
     "visual": "banner"},
)


def experiment_active() -> bool:
    """True exactly when the experiment post window is configured
    (schedulers/timing.experiment_window_active). The window flag IS
    the experiment flag."""
    return experiment_window_active()


def experiment_post_count(csv_path=None) -> int:
    """How many experiment posts are already logged: rows in the
    posts CSV whose mode is one of the four experiment modes.
    Missing file -> 0; malformed rows are skipped defensively."""
    path = csv_path or posts_csv.POSTS_CSV_PATH
    try:
        f = open(path, newline="")
    except OSError:
        return 0
    count = 0
    with f:
        try:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    if (row or {}).get("mode") in _EXPERIMENT_MODE_SET:
                        count += 1
                except (AttributeError, TypeError):
                    continue
        except (csv.Error, OSError):
            pass
    return count


def _override_mode():
    """EXPERIMENT_FORMAT when set to a valid mode, else None.
    Case/whitespace-insensitive; anything else is ignored (never a
    crash, never a silent new mode)."""
    raw = (os.environ.get(EXPERIMENT_FORMAT_ENV) or "").strip().lower()
    return raw if raw in _EXPERIMENT_MODE_SET else None


def current_day_plan(csv_path=None):
    """Today's experiment plan, or None when inactive.

    index = experiment_post_count(). Phase 1 (index < 7): the
    schedule entry. Phase 2 (index >= 7): the schedule keeps
    rotating (index % 7) as the safe fallback and the visual
    alternates by parity (odd index -> banner, even -> chart, so
    Day 8 = index 7 -> banner, Day 9 -> chart, per audit §F.4).
    A valid EXPERIMENT_FORMAT env var overrides the format on any
    day (the visual still comes from the schedule/parity rule);
    the override is recorded in the hypothesis so the CSV row says
    a human chose it.
    """
    if not experiment_active():
        return None
    index = experiment_post_count(csv_path)
    if index < len(EXPERIMENT_SCHEDULE):
        plan = dict(EXPERIMENT_SCHEDULE[index])
    else:
        visual = "banner" if index % 2 == 1 else "chart"
        base = EXPERIMENT_SCHEDULE[index % len(EXPERIMENT_SCHEDULE)]
        plan = {"mode": base["mode"],
                "hypothesis": (f"Phase 2 visual test: {visual} "
                               f"for {base['mode']}"),
                "variable_tested": f"visual={visual}",
                "visual": visual}
    override = _override_mode()
    if override is not None:
        plan = {"mode": override,
                "hypothesis": (f"manual override "
                               f"{EXPERIMENT_FORMAT_ENV}={override}"),
                "variable_tested": f"format={override}",
                "visual": plan["visual"]}
    return plan
