# tests/test_fewshot.py — per-reaction few-shot example files + loader.
#
# Every prompts/fewshot/<reaction>.json must parse, hold 3-4 good +
# 2 bad items, and every GOOD post must satisfy the hard rules the
# prompt builder relies on: 40-90 words, cashtag-first, exactly one
# cashtag, no EDITORIAL_FORBIDDEN phrase. The "why" field is
# reviewer-only and is never returned by the loader.

import json
import random
import re
from pathlib import Path

import pytest

from prompts.fewshot import load_fewshot_examples
from prompts.styles import EDITORIAL_FORBIDDEN

FEWSHOT_DIR = Path(__file__).resolve().parent.parent / "prompts" / "fewshot"

REACTIONS = (
    "surprise",
    "dejavu",
    "shrug",
    "disbelief",
    "question",
    "contrast",
    "caution",
    "smug",
)

CASHTAG_RE = re.compile(r"\$[A-Z]+")


def _load(reaction):
    with open(FEWSHOT_DIR / f"{reaction}.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("reaction", REACTIONS)
def test_file_parses_with_good_and_bad(reaction):
    data = _load(reaction)
    assert 3 <= len(data["good"]) <= 4, reaction
    assert len(data["bad"]) == 2, reaction
    for kind in ("good", "bad"):
        for item in data[kind]:
            assert isinstance(item["post"], str) and item["post"].strip()
            assert isinstance(item["why"], str) and item["why"].strip()


@pytest.mark.parametrize("reaction", REACTIONS)
def test_good_posts_follow_hard_rules(reaction):
    data = _load(reaction)
    for item in data["good"]:
        post = item["post"]
        words = post.split()
        assert 40 <= len(words) <= 90, f"{reaction}: {len(words)} words"
        assert re.match(r"^\$[A-Z0-9]+", post), f"{reaction}: not cashtag-first"
        assert len(CASHTAG_RE.findall(post)) == 1, (
            f"{reaction}: {CASHTAG_RE.findall(post)}"
        )
        lowered = post.lower()
        for phrase in EDITORIAL_FORBIDDEN:
            assert phrase not in lowered, f"{reaction}: forbidden {phrase!r}"


def test_loader_returns_default_subset_for_one_reaction():
    result = load_fewshot_examples("question")
    kinds = [kind for kind, _ in result]
    assert kinds.count("good") == 2
    assert kinds.count("bad") == 1
    assert all(isinstance(post, str) and post for _, post in result)


def test_loader_pools_all_files_when_no_reaction():
    result = load_fewshot_examples()
    kinds = [kind for kind, _ in result]
    assert kinds.count("good") == 2
    assert kinds.count("bad") == 1


def test_loader_seeded_rng_is_deterministic():
    first = load_fewshot_examples(rng=random.Random(1))
    second = load_fewshot_examples(rng=random.Random(1))
    assert first == second


def test_loader_unknown_reaction_returns_empty():
    assert load_fewshot_examples("not_a_reaction") == []


def test_loader_never_returns_why():
    result = load_fewshot_examples("question")
    data = _load("question")
    whys = {item["why"] for kind in ("good", "bad") for item in data[kind]}
    for _, post in result:
        assert post not in whys
