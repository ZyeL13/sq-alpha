# tests/test_article_gates.py — article quality gates (spec §6, §8).
"""The PYR before-article MUST fail gates 1, 3, 4, 6b; the fixed
good article MUST pass all gates. Number matcher, causal-claim scan,
LIMITS-missing-list, and the finish_reason=length retry (§6.6a)."""
import copy
import json
from pathlib import Path

import pytest

from generators.json_validate import (
    ARTICLE_SECTION_KEYS,
    _find_unmatched_article_numbers,
    _gate_differentiation,
    _gate_missing,
    _gate_repetition,
    _limitation_sentences,
    validate_article_json,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    with open(FIXTURES / name) as f:
        return json.load(f)


@pytest.fixture
def good():
    return _load("pyr_article_good.json")


@pytest.fixture
def pack():
    return _load("pyr_research_pack.json")


# ------------------------------------------------------- the before-state
# RECONSTRUCTED, not verbatim: the verbatim PYR article text is not
# saved anywhere on disk (verified by grep — only the spec's quotes
# exist). Rebuilt from spec §0's measurements: 803 words total;
# sections 122/147/137/138/130/119/10 words; only 3 numbers ($0.0210
# x2, 48.8% x5, $0.5M x5); 7x "cannot"; the two verbatim sentences
# "The distinction matters." and "That makes restraint part of the
# analysis, not a lack of analysis."; CONCLUSION exactly "The
# available evidence is blunt but narrow: the token is".
# The stance echo is set to BEARISH (the code-derived stance) so the
# fixture fails exactly gates 1, 3, 4, 6b — not 5, which the old
# <post>-tag article never had.
PYR_BEFORE = {
    "title": "A Sharp Decline, With Too Little Context",
    "stance": "BEARISH",
    "thesis": (
        "$PYR fell 48.8% to $0.0210 on $0.5M of volume. "
        "The decline is the dominant fact, and it cannot show whether the move reflects persistent selling or a single event. "
        "The volume figure does not, by itself, explain the move: there is no earlier volume figure, no measurement period, and no baseline against which volume can be called unusually high or low. "
        "No catalyst has been named, no timeframe has been established, and no forecast follows from one session. "
        "The distinction matters. "
        "Size is not explanation, and a large move without a baseline, without a timeframe, and without a catalyst leaves the cause and persistence of the decline unproven. "
        "No bullish case follows from these data, and no bearish signal is proven either."),
    "what_happened": (
        "The token fell 48.8% to $0.0210, with $0.5M of volume behind the whole move. "
        "There is no measurement period for the decline, and no earlier volume figure establishes a baseline for the volume, so the volume cannot be called unusually high or low. "
        "The data cannot establish whether selling accelerated, whether the move was orderly, or whether it came as a single event. "
        "No timeframe bounds the session, no history frames the low, and no catalyst names the cause. "
        "The move is very large, but size is not explanation, and the distinction matters here as well: the figures describe what happened, not why it happened or what must happen next at all. "
        "Without a baseline, without a timeframe, and without a catalyst, the session cannot be read as a trend. "
        "Every figure shows the same move, and every reading shows the same missing timeframe, baseline, and catalyst."),
    "why_it_matters": (
        "The 48.8% decline is very large, yet size is not explanation. "
        "The $0.5M volume figure adds context only in a limited sense: without a baseline, without a timeframe, and without a catalyst, it cannot show whether the move reflects persistent selling or a single event. "
        "Cause and persistence remain unproven, and the distinction matters for any reading of the session for now. "
        "A large move with no baseline and no history cannot be called a trend, and a single session cannot prove what follows. "
        "That makes restraint part of the analysis, not a lack of analysis. "
        "The figures are blunt, but the evidence is narrow, and the lack of a timeframe, a baseline, and a catalyst leaves every interpretation provisional. "
        "No forecast follows from one session, and no measurement period turns a single day into a trend."),
    "bull_case": (
        "There is no strong bullish case in these data here. "
        "A bullish reading would need new evidence, and neither the volume figure nor the price level supplies it at all. "
        "The $0.5M volume gives no support, the price level gives no floor, and the 48.8% decline gives no completed move. "
        "No catalyst points upward, no baseline shows the selling spent, and no timeframe bounds the fall. "
        "The possibility of a bounce is a logical possibility rather than a bullish signal: it is neither present in the data nor supported by any figure here today. "
        "Without a catalyst, without a baseline, and without a history of recovery, the bull case stays a possibility, not a signal. "
        "A bounce would need a named catalyst, a visible baseline, and a measured timeframe, and none of those is present in the session."),
    "bear_case": (
        "The 48.8% decline is the clearest directional signal in the data. "
        "Price fell to the session low on $0.5M of volume, and the move reads as steady selling pressure through the session. "
        "But the figures do not prove that selling pressure still remains, that the decline is continuing, or that it has passed its sharpest point. "
        "It could be continuing, slowing, or past its sharpest point, and no timeframe, no baseline, and no history can settle which. "
        "The bear case is strongest as description, not forecast: it describes damage to date so far, not what must happen next. "
        "Without a catalyst and without a baseline, the direction is clear and the duration is not. "
        "No history of recovery and no measurement period gives the decline a shape beyond one session."),
    "limits": (
        "The limits are the ones already named. "
        "There is no timeframe for the move, no price history beyond one session, no comparative volume baseline, no catalyst, and no trader identity behind the selling in the data. "
        "The volume figure gives no earlier figure to set it against, the price gives no longer history, and the move gives no trend to follow at all. "
        "No forecast follows from these data, and no invalidation level can be fixed without a timeframe or a baseline. "
        "The read would change only if later price data showed a reclaim of the levels lost, with volume at size and a named catalyst behind it. "
        "Until then, the evidence stays blunt and narrow by every measure."),
    "conclusion": "The available evidence is blunt but narrow: the token is",
    "headline": "PYR COLLAPSES WITH NO EXPLANATION",
    "deck": "Half the value gone in a day, and the data cannot say why.",
}


def _body(article):
    return " ".join(article[k] for k in ARTICLE_SECTION_KEYS)


def test_pyr_before_measured_properties():
    """The reconstruction reproduces spec §0's measurements."""
    counts = {k: len(PYR_BEFORE[k].split()) for k in ARTICLE_SECTION_KEYS}
    assert counts == {
        "thesis": 122, "what_happened": 147, "why_it_matters": 137,
        "bull_case": 138, "bear_case": 130, "limits": 119,
        "conclusion": 10,
    }
    assert sum(counts.values()) == 803
    body = _body(PYR_BEFORE)
    assert body.count("$0.0210") == 2
    assert body.count("48.8%") == 5
    assert body.count("$0.5M") == 5
    assert body.lower().count("cannot") == 7
    assert "The distinction matters." in PYR_BEFORE["thesis"]
    assert ("That makes restraint part of the analysis, not a lack of "
            "analysis." in PYR_BEFORE["why_it_matters"])
    assert PYR_BEFORE["conclusion"] == (
        "The available evidence is blunt but narrow: the token is")
    # Limitation restatements, spec §0's ~31 theme hits in kind: the
    # gate's limitation-sentence detector finds 19 such sentences
    # (16 outside LIMITS, far above the <= 4 gate), and every
    # non-LIMITS section carries at least 2.
    total_lim = sum(len(_limitation_sentences(PYR_BEFORE[k]))
                    for k in ARTICLE_SECTION_KEYS)
    assert total_lim == 19
    for key in ARTICLE_SECTION_KEYS:
        if key not in ("limits", "conclusion"):
            assert len(_limitation_sentences(PYR_BEFORE[key])) >= 2


def test_pyr_before_fails_gates_1_3_4_6b(pack):
    ok, reason, gate = validate_article_json(
        PYR_BEFORE, pack["facts"], pack)
    assert ok is False
    assert gate == "6b"  # first failure: CONCLUSION cut mid-sentence
    assert reason == "conclusion_too_short"
    assert _gate_repetition(PYR_BEFORE) is not None  # gate 1
    assert _gate_missing(PYR_BEFORE, pack) is not None  # gate 3
    assert _gate_differentiation(PYR_BEFORE) is not None  # gate 4
    # Gates 2 and 5 pass: every number is real, no causal claim, the
    # stance echo and headline verb are correct.
    from generators.json_validate import _gate_banner_text, _gate_unsupported

    assert _gate_unsupported(PYR_BEFORE, pack["facts"], pack) is None
    assert _gate_banner_text(PYR_BEFORE, pack["facts"], pack) is None


# ------------------------------------------------------- the fixed article
def test_good_article_passes_all_gates(good, pack):
    ok, reason, gate = validate_article_json(good, pack["facts"], pack)
    assert (ok, reason, gate) == (True, None, None)


def test_good_article_section_bands_and_total(good):
    counts = {k: len(good[k].split()) for k in ARTICLE_SECTION_KEYS}
    bands = {
        "thesis": (60, 90), "what_happened": (80, 120),
        "why_it_matters": (80, 120), "bull_case": (60, 100),
        "bear_case": (60, 100), "limits": (60, 90),
        "conclusion": (40, 70),
    }
    for key, (lo, hi) in bands.items():
        assert lo <= counts[key] <= hi, (key, counts[key])
    assert 550 <= sum(counts.values()) <= 750
    assert good["conclusion"].rstrip().endswith((".", "!", "?"))
    assert good["stance"] == "BEARISH"
    assert "BEARISH" in good["thesis"] or "bearish" in good["thesis"]
    assert len(good["headline"]) <= 90
    assert len(good["deck"]) <= 140


def test_good_article_numbers_capped_at_three_mentions(good):
    """Spec §9: each number appears at most 3x in the body."""
    body = _body(good)
    for num in ("$0.0210", "48.8%", "$0.5M", "$0.0190", "$0.0470",
                "$0.0408", "0.6x", "$833K", "133.3%", "1.7%"):
        assert body.count(num) <= 3, (num, body.count(num))
    # And the volume baseline, range position context, and
    # BTC-relative all appear (they are now in the research pack).
    assert "0.6x" in body
    assert "133.3%" in body
    assert "47.1 points" in body


def test_good_article_passes_validate_longform(good):
    from generators.post_generator import _assemble_article_body
    from generators.quality_gate import validate_longform

    body = _assemble_article_body(good)
    valid, _ = validate_longform(good["title"], body, symbol="PYR")
    assert valid is True


# ------------------------------------------------------- number matcher
def test_unmatched_dollar_figure_fails_gate_2(good, pack):
    bad = copy.deepcopy(good)
    bad["thesis"] = bad["thesis"].replace("$0.0210", "$9.99", 1)
    ok, reason, gate = validate_article_json(bad, pack["facts"], pack)
    assert ok is False
    assert gate == "2"
    assert reason.startswith("number_not_in_snapshot")


def test_number_matcher_tolerances(good, pack):
    # 48.9% vs 48.8% (0.1 <= 0.15 pct) and $0.0212 vs $0.0210
    # (0.95% <= 2% rel) and 0.7x vs 0.6x (0.1 <= 0.15) all pass.
    ok = copy.deepcopy(good)
    ok["thesis"] = ok["thesis"].replace("48.8%", "48.9%", 1)
    ok["thesis"] = ok["thesis"].replace("$0.0210", "$0.0212", 1)
    ok["thesis"] = ok["thesis"].replace("0.6x", "0.7x", 1)
    assert validate_article_json(ok, pack["facts"], pack)[0] is True
    # Outside tolerance: 49.5% vs 48.8% (0.7 > 0.15) fails.
    bad = copy.deepcopy(good)
    bad["thesis"] = bad["thesis"].replace("48.8%", "49.5%", 1)
    assert validate_article_json(bad, pack["facts"], pack)[2] == "2"


def test_unmatched_numbers_helper_direct(pack):
    from generators.json_validate import _article_numbers

    numbers = _article_numbers(pack["facts"])
    assert _find_unmatched_article_numbers(
        "price $0.0210, down 48.8% on $0.5M", numbers) == []
    assert "$9.99" in _find_unmatched_article_numbers(
        "price $9.99", numbers)
    # Sign-insensitive percent: "fell 48.8%" matches a -48.8% move.
    assert _find_unmatched_article_numbers(
        "fell 48.8%", numbers) == []


# ------------------------------------------------------- causal claims
def test_causal_claim_without_catalyst_fails(good, pack):
    bad = copy.deepcopy(good)
    bad["why_it_matters"] = bad["why_it_matters"] + (
        " The slide was driven by a hack nobody reported.")
    ok, reason, gate = validate_article_json(bad, pack["facts"], pack)
    assert ok is False
    assert gate == "2"
    assert reason == "causal_claim_without_catalyst"


def test_causal_claim_with_named_catalyst_passes(good, pack):
    with_catalyst = copy.deepcopy(pack)
    with_catalyst["catalyst"] = {"text": "exchange hack reported"}
    ok = copy.deepcopy(good)
    ok["why_it_matters"] = ok["why_it_matters"] + (
        " The slide was triggered by the exchange hack reported.")
    assert validate_article_json(
        ok, with_catalyst["facts"], with_catalyst)[0] is True


# ------------------------------------------------------- LIMITS / missing
def test_limits_generic_fails_gate_3(good, pack):
    bad = copy.deepcopy(good)
    bad["limits"] = (
        "More data is needed before any conclusion can be drawn, and the "
        "read stays provisional without it. The evidence is thin and the "
        "picture is incomplete, so any view here is early.")
    ok, reason, gate = validate_article_json(bad, pack["facts"], pack)
    assert ok is False
    assert gate == "3"
    assert reason == "limits_names_no_missing_data"


def test_limits_names_missing_item_passes(good, pack):
    from generators.json_validate import _gate_missing

    assert _gate_missing(good, pack) is None
    assert _gate_missing(PYR_BEFORE, pack) == "limits_names_no_missing_data"


# ------------------------------------------------------- headline / stance
def test_headline_verb_wrong_band_fails_gate_5(good, pack):
    bad = copy.deepcopy(good)
    bad["headline"] = "PYR DIPS 48.8% WITH NO EXPLANATION"
    ok, reason, gate = validate_article_json(bad, pack["facts"], pack)
    assert ok is False
    assert gate == "5"
    assert reason == "headline_verb_mismatch"


def test_stance_mismatch_fails_gate_5(good, pack):
    bad = copy.deepcopy(good)
    bad["stance"] = "BULLISH"
    ok, reason, gate = validate_article_json(bad, pack["facts"], pack)
    assert ok is False
    assert gate == "5"
    assert reason == "stance_mismatch"


def test_headline_too_long_fails_gate_5(good, pack):
    bad = copy.deepcopy(good)
    bad["headline"] = "PYR COLLAPSES 48.8% " + "AND KEEPS FALLING " * 6
    assert len(bad["headline"]) > 90
    assert validate_article_json(bad, pack["facts"], pack)[2] == "5"


# ------------------------------------------------------- §6.6a length retry
def test_generate_longform_retries_on_finish_reason_length(monkeypatch, good):
    import json

    import generators.post_generator as pg

    token = {"symbol": "PYR", "price": 0.0210, "price_change_percent": -48.8,
             "high_24h": 0.0470, "low_24h": 0.0190,
             "volume_24h": 500_000, "range_position": 0.07}
    # The good fixture cites volume_ratio / BTC-relative / path facts,
    # so the pack needs a real snapshot, not token-only facts.
    from schedulers.snapshot import CardSnapshot

    closes = [
        0.0408, 0.0420, 0.0445, 0.0470, 0.0455, 0.0430, 0.0410, 0.0390,
        0.0375, 0.0360, 0.0340, 0.0325, 0.0310, 0.0295, 0.0280, 0.0265,
        0.0250, 0.0235, 0.0220, 0.0215, 0.0190, 0.0195, 0.0205, 0.0210,
    ]
    snapshot = CardSnapshot(
        token=dict(token, btc_change_24h=-1.7), closes=closes,
        volume_7d_avg=833333.33, btc_change=-1.7)
    calls = {"n": 0, "prompts": []}

    def fake_generate(prompt, system_prompt=None, category=None,
                      max_tokens=None, **kw):
        calls["n"] += 1
        calls["prompts"].append(prompt)
        # First reply is cut by length even though it parses; the
        # second completes.
        pg.llm.last_call_meta = {
            "provider": "test", "model": "test-model",
            "finish_reason": "length" if calls["n"] == 1 else "stop"}
        return json.dumps(good)

    monkeypatch.setattr(pg, "generate", fake_generate)
    monkeypatch.setattr(pg, "is_similar_to_recent", lambda c: False)
    monkeypatch.setattr(pg, "add_to_recent", lambda c: None)

    result = pg.generate_longform(token, "LOSERS", {}, snapshot=snapshot)
    assert result is not None
    assert calls["n"] == 2
    assert "500 words max" in calls["prompts"][1]
