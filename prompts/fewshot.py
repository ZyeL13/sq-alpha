# prompts/fewshot.py — loader for per-reaction few-shot examples.
#
# Each prompts/fewshot/<reaction>.json is
#   {"good": [{"post": ..., "why": ...}, ...], "bad": [...]}
# The "why" is reviewer-only documentation and is NEVER returned.
# Loading is best-effort: missing, corrupt, or unknown-reaction files
# are skipped gracefully and the caller always gets a list (possibly
# empty), never an exception.

import json
import random
from pathlib import Path

_FEW_SHOT_DIR = Path(__file__).resolve().parent / "fewshot"


def _load_file(path: "Path") -> "dict | None":
    """One few-shot file, or None on any failure (missing/corrupt/
    wrong shape). Never raises."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _posts(data: "dict | None", kind: str) -> "list[str]":
    """Non-empty post strings of one kind from a parsed file."""
    if not data:
        return []
    items = data.get(kind)
    if not isinstance(items, list):
        return []
    posts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        post = item.get("post")
        if isinstance(post, str) and post.strip():
            posts.append(post)
    return posts


def load_fewshot_examples(reaction=None, n_good=2, n_bad=1, rng=None):
    """Return [(kind, post), ...] with kind in ("good", "bad").

    If `reaction` is given, load prompts/fewshot/<reaction>.json;
    if None, pool all files in prompts/fewshot/. A random subset
    (n_good good + n_bad bad) is drawn via random.sample, using the
    passed `rng` or the random module. Missing/corrupt/unknown-
    reaction files are skipped gracefully (return what exists,
    never raise).
    """
    sampler = rng if rng is not None else random
    try:
        if reaction is None:
            try:
                files = sorted(_FEW_SHOT_DIR.glob("*.json"))
            except Exception:
                return []
            good, bad = [], []
            for path in files:
                data = _load_file(path)
                good.extend(_posts(data, "good"))
                bad.extend(_posts(data, "bad"))
        else:
            data = _load_file(_FEW_SHOT_DIR / f"{reaction}.json")
            if data is None:
                return []
            good = _posts(data, "good")
            bad = _posts(data, "bad")
        picked_good = sampler.sample(good, min(n_good, len(good))) if good else []
        picked_bad = sampler.sample(bad, min(n_bad, len(bad))) if bad else []
        return [("good", post) for post in picked_good] + [
            ("bad", post) for post in picked_bad
        ]
    except Exception:
        return []
