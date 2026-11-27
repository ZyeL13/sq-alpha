# tests/test_article_redesign.py — article redesign (spec §8).
"""Research-pack builder, stance + verb-scale boundaries, prompt
contracts. No network, no LLM: the pack is code-built and the prompt
is a pure function of the token."""
import pytest

PYR_TOKEN = {
    "symbol": "PYR",
    "price": 0.0210,
    "price_change_percent": -48.8,
    "high_24h": 0.0470,
    "low_24h": 0.0190,
    "volume_24h": 500_000,
    "range_position": 0.07,
}
# 24 hourly closes, oldest first: session high $0.0470 twenty hours
# ago (index 3), session low $0.0190 three hours ago (index 20),
# 24h-ago price $0.0408.
PYR_CLOSES = [
    0.0408, 0.0420, 0.0445, 0.0470, 0.0455, 0.0430, 0.0410, 0.0390,
    0.0375, 0.0360, 0.0340, 0.0325, 0.0310, 0.0295, 0.0280, 0.0265,
    0.0250, 0.0235, 0.0220, 0.0215, 0.0190, 0.0195, 0.0205, 0.0210,
]


def _pyr_snapshot():
    from schedulers.snapshot import CardSnapshot

    return CardSnapshot(
        token=dict(PYR_TOKEN, btc_change_24h=-1.7),
        closes=list(PYR_CLOSES),
        volume_7d_avg=833333.33,
        btc_change=-1.7,
    )


# ------------------------------------------------------- path facts
def test_path_facts_from_closes():
    snap = _pyr_snapshot()
    facts = snap.path_facts()
    assert facts["price_24h_ago"] == pytest.approx(0.0408)
    assert facts["session_low"] == pytest.approx(0.0190)
    assert facts["session_low_hours_ago"] == 3
    assert facts["session_high"] == pytest.approx(0.0470)
    assert facts["session_high_hours_ago"] == 20


def test_path_facts_empty_without_closes():
    from schedulers.snapshot import CardSnapshot

    snap = CardSnapshot(token=dict(PYR_TOKEN), closes=[],
                        volume_7d_avg=0, btc_change=None)
    assert snap.path_facts() == {}


def test_to_dict_unchanged_by_path_facts():
    # Path facts live in path_facts(), NOT to_dict() — the short-form
    # snapshot JSON (and its prompt bytes) stay unchanged.
    snap = _pyr_snapshot()
    d = snap.to_dict()
    assert "price_24h_ago" not in d
    assert "session_low" not in d
    assert d["price"] == pytest.approx(0.0210)
    assert d["volume_ratio"] == pytest.approx(0.6)


# ------------------------------------------------------- research pack
def test_build_research_pack_pyr():
    from generators.post_generator import build_research_pack

    pack = build_research_pack(PYR_TOKEN, _pyr_snapshot(), "LOSERS",
                               "anomaly")
    assert set(pack) >= {"facts", "stance", "catalyst", "memory", "missing"}
    facts = pack["facts"]
    assert facts["price"] == pytest.approx(0.0210)
    assert facts["change_24h"] == pytest.approx(-48.8)
    assert facts["volume_24h"] == 500_000
    assert facts["volume_ratio"] == pytest.approx(0.6)
    assert facts["btc_relative"] == pytest.approx(-47.1)
    assert facts["range_position"] == pytest.approx(0.0714, abs=0.001)
    # Code-derived path facts are merged into facts.
    assert facts["price_24h_ago"] == pytest.approx(0.0408)
    assert facts["session_low"] == pytest.approx(0.0190)
    assert facts["session_high"] == pytest.approx(0.0470)
    assert "closes" not in facts
    assert pack["stance"] == "BEARISH"
    assert pack["angle"] == "anomaly"
    assert pack["catalyst"] is None
    assert pack["memory"] is None
    # Missing split: catalyst is the only fillable gap for PYR.
    assert pack["missing"]["fillable"] == ["news catalyst"]
    assert ">24h price history" in pack["missing"]["unavailable"]
    assert "funding rates and open interest" in pack["missing"]["unavailable"]


def test_build_research_pack_no_snapshot_marks_fields_missing():
    from generators.post_generator import build_research_pack

    token = {"symbol": "KITE", "price": 1.0, "price_change_percent": 2.0,
             "volume_24h": 100_000}
    pack = build_research_pack(token, None, "HOT", "range edge")
    assert pack["facts"]["price"] == 1.0
    assert pack["facts"]["change_24h"] == 2.0
    assert "price_24h_ago" not in pack["facts"]
    assert "volume vs 7-day average" in pack["missing"]["fillable"]
    assert "BTC 24h change" in pack["missing"]["fillable"]
    assert pack["stance"] == "NEUTRAL"


def test_build_research_pack_catalyst_and_memory():
    from generators.post_generator import build_research_pack

    token = dict(PYR_TOKEN, news_catalyst="exchange lists PYR",
                 price_at_news=0.04, volume_at_news=400_000)
    pack = build_research_pack(token, None, "LOSERS", "catalyst follow-through",
                               memory="Last post: $PYR slipped 5%.")
    assert pack["catalyst"]["text"] == "exchange lists PYR"
    assert pack["catalyst"]["price_at_news"] == 0.04
    assert "news catalyst" not in pack["missing"]["fillable"]
    assert pack["memory"] == "Last post: $PYR slipped 5%."


# ------------------------------------------------------- stance + verbs
@pytest.mark.parametrize("change,category,expected", [
    (-48.8, "LOSERS", "BEARISH"),
    (-10.0, "HOT", "BEARISH"),
    (-9.9, "HOT", "NEUTRAL"),
    (10.0, "HOT", "BULLISH"),
    (9.9, "HOT", "NEUTRAL"),
    (0.0, "HOT", "NEUTRAL"),
    (0.0, "LOSERS", "BEARISH"),
    (0.0, "GAINERS", "BULLISH"),
    (2.9, "GAINERS", "BULLISH"),
    (-2.9, "LOSERS", "BEARISH"),
    (3.0, "LOSERS", "NEUTRAL"),
    (-3.0, "GAINERS", "NEUTRAL"),
    (None, "HOT", "NEUTRAL"),
])
def test_derive_stance_boundaries(change, category, expected):
    from prompts.styles import derive_stance

    assert derive_stance(change, category) == expected


@pytest.mark.parametrize("change,expected", [
    (-48.8, "COLLAPSES"), (-30.0, "COLLAPSES"), (-29.9, "TUMBLES"),
    (-15.0, "TUMBLES"), (-14.9, "SLIDES"), (-10.0, "SLIDES"),
    (-9.9, "DIPS"), (-5.0, "DIPS"), (-4.9, "HOLDS FLAT"),
    (-0.1, "HOLDS FLAT"), (0.0, "EDGES UP"), (4.9, "EDGES UP"),
    (5.0, "GAINS"), (9.9, "GAINS"), (10.0, "CLIMBS"),
    (14.9, "CLIMBS"), (15.0, "JUMPS"), (29.9, "JUMPS"),
    (30.0, "SURGES"), (48.8, "SURGES"),
])
def test_verb_scale_boundaries(change, expected):
    from prompts.styles import verb_for_change

    assert verb_for_change(change) == expected


# ------------------------------------------------------- format + reason
def _token(**over):
    base = {"symbol": "KITE", "price": 1.0, "price_change_percent": 0.0,
            "volume_24h": 500_000, "range_position": 0.5}
    base.update(over)
    return base


def test_select_post_format_with_reason_justifications():
    from prompts.styles import select_post_format_with_reason

    # Anomaly.
    assert select_post_format_with_reason(
        _token(), "HOT", {"anomaly": 0.9}, {}) == ("longform", "anomaly")
    # Volume event: volume +100% since the news, no price move.
    assert select_post_format_with_reason(
        _token(news_catalyst="n", volume_at_news=100_000,
               volume_24h=200_000, price_at_news=1.0),
        "HOT", {"anomaly": 0.2}, {}) == ("longform", "volume event")
    # Contrarian: price +6% since the news, day -6%.
    assert select_post_format_with_reason(
        _token(news_catalyst="n", price_at_news=1.0, price=1.06,
               price_change_percent=-6.0),
        "HOT", {"anomaly": 0.2}, {}) == ("longform", "contrarian")
    # Catalyst follow-through: +6% since the news, same direction.
    assert select_post_format_with_reason(
        _token(news_catalyst="n", price_at_news=1.0, price=1.06,
               price_change_percent=6.0),
        "HOT", {"anomaly": 0.2}, {}) == ("longform", "catalyst follow-through")
    # Range edge: bottom 5% of the range with a 6% move.
    assert select_post_format_with_reason(
        _token(price_change_percent=6.0, high_24h=0.0470, low_24h=0.0190,
               price=0.0204),
        "HOT", {"anomaly": 0.2}, {}) == ("longform", "range edge")
    # Ordinary token: short, no justification.
    assert select_post_format_with_reason(
        _token(), "HOT", {"anomaly": 0.2}, {}) == ("short", None)


def test_select_post_format_unchanged_via_with_reason():
    from prompts.styles import select_post_format

    assert select_post_format(_token(), "HOT", {"anomaly": 0.9}, {}) == "longform"
    assert select_post_format(_token(), "HOT", {"anomaly": 0.2}, {}) == "short"


# ------------------------------------------------------- prompt contracts
def test_build_longform_prompt_section_jobs_stated_once():
    from generators.post_generator import build_longform_prompt

    prompt = build_longform_prompt(PYR_TOKEN, "LOSERS", {})
    # Each section's job (spec §3.2) appears exactly once.
    jobs = [
        "the stance, the single strongest reason",
        "the tape as a path",
        "market context",
        "the strongest bull argument from the data",
        "the mirror of BULL CASE",
        "the only section that states limitations",
        "restate the stance and the single condition to watch",
    ]
    for job in jobs:
        assert prompt.lower().count(job.lower()) == 1, job
    # Each §3.1 principle appears once; the ~7x caution is gone.
    lowered = prompt.lower()
    for phrase in ("never invent", "no fabricated certainty",
                   "state the limits"):
        assert lowered.count(phrase) <= 1, phrase
    assert "never pretend certainty" not in lowered
    assert "VOICE CALIBRATION" not in prompt
    assert "RESEARCH PACK" in prompt
    assert '"stance": "BEARISH"' in prompt
    assert "COLLAPSES" in prompt
