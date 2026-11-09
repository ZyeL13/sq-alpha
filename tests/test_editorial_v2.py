"""Editorial v2 — conditional style selection and quality-over-quota skip.

Style selection is deterministic: it reads the token's own data, never
a random draw. The skip check is the quality-over-quota gate: a token
with genuinely nothing to observe is skipped before any LLM call, and
the reason is logged by the caller.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prompts.styles import (
    EDITORIAL_FORBIDDEN,
    VOICE_CALIBRATION,
    insufficient_insight,
    select_editorial_style,
)


def _token(**overrides):
    token = {
        "symbol": "XYZ",
        "price": 1.50,
        "price_change_percent": 5.0,
        "volume_24h": 1_000_000,
        "range_position": 0.5,
    }
    token.update(overrides)
    return token


# --- select_editorial_style ---

def test_default_is_analytical():
    assert select_editorial_style(_token()) == "analytical"


def test_data_observation_on_volume_price_anomaly():
    # $150M volume, price barely moved -> anomaly 0.9
    token = _token(price_change_percent=0.5, volume_24h=150_000_000)
    assert select_editorial_style(token) == "data_observation"


def test_data_observation_prefers_passed_scores():
    token = _token(price_change_percent=0.5, volume_24h=1_000_000)
    assert select_editorial_style(token, {"anomaly": 0.8}) == "data_observation"
    assert select_editorial_style(token, {"anomaly": 0.2}) == "analytical"


def test_data_observation_on_volume_jump_since_news():
    token = _token(
        news_catalyst="XYZ launches mainnet",
        price=100.0,
        price_at_news=100.0,
        volume_24h=1_600_000,
        volume_at_news=1_000_000,
        price_change_percent=0.5,
    )
    assert select_editorial_style(token) == "data_observation"


def test_contrarian_when_tape_contradicts_the_day():
    # Day is +5%, but since the news landed price fell 4%.
    token = _token(
        news_catalyst="XYZ launches mainnet",
        price=96.0,
        price_at_news=100.0,
        price_change_percent=5.0,
    )
    assert select_editorial_style(token) == "contrarian"
    # Mirror image: day is down, but since the news it recovered.
    token = _token(
        news_catalyst="XYZ launches mainnet",
        price=104.0,
        price_at_news=100.0,
        price_change_percent=-5.0,
    )
    assert select_editorial_style(token) == "contrarian"


def test_contrarian_needs_opposite_directions():
    # Same direction since the news as the day: no contradiction.
    token = _token(
        news_catalyst="XYZ launches mainnet",
        price=104.0,
        price_at_news=100.0,
        price_change_percent=5.0,
    )
    assert select_editorial_style(token) == "analytical"


def test_dry_humor_on_big_move_with_no_catalyst():
    assert select_editorial_style(_token(price_change_percent=18.0)) == "dry_humor"
    assert select_editorial_style(_token(price_change_percent=-16.0)) == "dry_humor"
    # Same move WITH a catalyst, ended near the high: the move held,
    # so there is nothing absurd to satirize.
    token = _token(
        price_change_percent=18.0,
        range_position=0.9,
        news_catalyst="XYZ launches mainnet",
    )
    assert select_editorial_style(token) == "analytical"
    # But a news-driven spike that retraced to mid-range is still a
    # big session that went nowhere.
    token = _token(
        price_change_percent=18.0,
        range_position=0.5,
        news_catalyst="XYZ launches mainnet",
    )
    assert select_editorial_style(token) == "dry_humor"


def test_dry_humor_on_big_session_that_went_nowhere():
    token = _token(price_change_percent=12.0, range_position=0.5)
    assert select_editorial_style(token) == "dry_humor"
    # Ended near the high: the session went somewhere.
    token = _token(price_change_percent=12.0, range_position=0.9)
    assert select_editorial_style(token) == "analytical"


def test_data_observation_beats_humor_on_priority():
    # Huge move on nothing AND a volume anomaly: anomaly wins.
    token = _token(price_change_percent=18.0, volume_24h=500_000)
    assert select_editorial_style(token) == "data_observation"


# --- insufficient_insight ---

def test_skip_without_valid_data():
    assert insufficient_insight(_token(price=0)) == "no_valid_data"
    assert insufficient_insight(_token(volume_24h=0)) == "no_valid_data"


def test_skip_flat_tape_with_no_catalyst():
    token = _token(price_change_percent=0.5, range_position=0.5, volume_24h=5_000_000)
    assert insufficient_insight(token) == "no_observation"


def test_no_skip_when_there_is_something_to_say():
    # A catalyst is an observation by itself.
    token = _token(
        price_change_percent=0.5,
        range_position=0.5,
        volume_24h=5_000_000,
        news_catalyst="XYZ launches mainnet",
    )
    assert insufficient_insight(token) is None
    # A real move is an observation, even a modest one.
    assert insufficient_insight(_token(price_change_percent=5.0)) is None
    # Notable volume is an observation even on a flat price.
    token = _token(price_change_percent=0.5, volume_24h=150_000_000)
    assert insufficient_insight(token) is None
    # Sitting at the high/low of the range is an observation.
    token = _token(price_change_percent=0.5, range_position=0.9, volume_24h=5_000_000)
    assert insufficient_insight(token) is None


# --- build_prompt (Editorial v2 wiring) ---

def test_prompt_carries_style_and_calibration():
    from generators.post_generator import build_prompt

    prompt = build_prompt(_token(), "GAINERS")
    assert "EDITORIAL STYLE: analytical" in prompt
    assert "learn the voice, not the sentence structure" in prompt
    assert "Forced Contrarianism" in prompt
    # No verbatim template parts anymore.
    assert "HOOK - copy this as your FIRST LINE" not in prompt
    assert "ANGLE - use this as the basis" not in prompt
    assert "CLOSING - Your final line must be exactly this" not in prompt
    assert "Write 4-6 short paragraphs" not in prompt
    assert "No predictions, no opinions" not in prompt


def test_prompt_style_follows_scores():
    from generators.post_generator import build_prompt

    token = _token(price_change_percent=0.5, volume_24h=150_000_000)
    prompt = build_prompt(token, "HOT", {"anomaly": 0.9})
    assert "EDITORIAL STYLE: data_observation" in prompt


def test_prompt_still_carries_news_and_price_context():
    from generators.post_generator import build_prompt

    token = _token(
        news_catalyst="XYZ launches mainnet",
        price=110.0,
        price_at_news=100.0,
        volume_24h=1_500_000,
        volume_at_news=1_000_000,
    )
    prompt = build_prompt(token, "GAINERS")
    assert "relevant news: XYZ launches mainnet" in prompt
    assert "news price context: price at news time $100.00" in prompt


# --- quality gate: editorial violations ---

def test_validate_rejects_editorial_violations():
    from generators.quality_gate import validate_post

    for bad in (
        "$XYZ is up today. watching from here.",
        "$XYZ is up today. monitoring the session.",
        "$XYZ is up today. smart money is positioning.",
        "$XYZ is up today. only time will tell.",
    ):
        valid, reason = validate_post(bad)
        assert not valid, bad
        assert reason.startswith("Editorial violation:"), reason


def test_validate_accepts_clean_post():
    from generators.quality_gate import validate_post

    good = (
        "$XYZ is up 5% on $12.0M volume. buyers showed up after the "
        "announcement, but the move has not held above the open yet. "
        "worth watching whether the next session confirms it."
    )
    valid, _ = validate_post(good)
    assert valid


def test_proofread_does_not_append_template_closer():
    from generators.quality_gate import proofread_post

    content = "$XYZ is up 5% on $12.0M volume.\n\nbuyers showed up."
    assert "tracking the move" not in proofread_post(content, "XYZ")


# --- generate_post: skip happens before any LLM call ---

def test_generate_post_skips_without_calling_llm(monkeypatch):
    import generators.post_generator as pg

    def _boom(*args, **kwargs):
        raise AssertionError("LLM must not be called for a skipped token")

    monkeypatch.setattr(pg, "generate", _boom)
    flat = _token(price_change_percent=0.5, range_position=0.5, volume_24h=5_000_000)
    assert pg.generate_post(flat, "HOT", {}) is None


# --- quality gate: reasoning leaks from the VPS demo 2026-11-09 ---

def test_validate_rejects_reasoning_leaks_from_demo():
    """Verbatim BlockRun mistral outputs from the 2026-11-09 demo run.

    Both were returned as the "post" and PASSED the old gate.
    """
    from generators.quality_gate import is_reasoning_leak, validate_post

    kite_reasoning = (
        'We need to produce a short post (40-120 words). Must start with '
        '"$KITE" uppercase in first line. Then rest sentences refer to '
        '"the token". Must be analytical, calm, skeptical, maybe witty but '
        "not forced. Let's count approximate. First line: \"$KITE\" (1 word?). "
        "Let's draft: the token rose 4.2% to $2.40 on $8.5M volume."
    )
    orbit_reasoning = (
        "tags\n- No explanations, no analysis notes, no reasoning, no drafts\n\n"
        "Data: $ORBIT +0.4% on $150.0M volume, price $0.8500.\n\n"
        "I need to find an anomaly. The data shows +0.4% price move with "
        "$150.0M volume. Without knowing average volume, I can't say it's "
        "3x average. Let's draft: $ORBIT traded $150.0M in volume while "
        "price moved just +0.4% to $0.8500."
    )
    for leak in (kite_reasoning, orbit_reasoning):
        assert is_reasoning_leak(leak), leak[:60]
        valid, reason = validate_post(leak)
        assert not valid, leak[:60]
        assert reason == "Reasoning leak detected", reason


def test_validate_accepts_real_demo_posts():
    """The two good posts from the same demo run must still pass."""
    from generators.quality_gate import validate_post

    nova = (
        "$NOVA jumped 6% on $12.0M volume, yet the price sits at $95.50, "
        "down about 4.5% from the $100 level seen when the mainnet was "
        "announced. the prevailing story is that the launch should have "
        "sparked a rally, but the token is actually slipping while volume "
        "modestly climbs. this mismatch suggests sellers are still in "
        "control, and the extra volume may simply be distribution rather "
        "than fresh buying. a sustained price rise above $100 accompanied "
        "by continued volume growth would be needed to validate the "
        "bullish narrative."
    )
    meme = (
        "$MEME is up 21% at $0.0121 with $6.0M in volume, which is roughly "
        "the market equivalent of a small crowd cheering in an empty room. "
        "the move is real, but the participation is modest relative to the "
        "size of the gain. price can stretch quickly when liquidity is "
        "thin, so a single session of buying does not necessarily signal "
        "sustained demand. volume staying elevated would make the move "
        "harder to dismiss."
    )
    for good in (nova, meme):
        valid, reason = validate_post(good)
        assert valid, reason


def test_validate_rejects_demo2_orbit_leak():
    """Demo run 2 (2026-11-09 14:46 WIB): the ORBIT output PASSED the
    old gate. Its tells sit past the old 400-char scan window
    ("Let's draft:" at char 711, "Word count check:" at char 1077),
    and it opens with the "tags" fragment left by the <post> extraction.
    """
    from generators.quality_gate import is_reasoning_leak, validate_post

    orbit_demo2 = (
        "tags\n\n"
        "Data observation style: Let numbers lead. One anomaly stated "
        "plainly with comparison.\n\n"
        "The anomaly: +0.4% price move on $150.0M volume. That's high "
        "volume for a tiny price move. Need to compare to normal market "
        "behavior, but I don't have \"recent average\" volume in the data. "
        "I can only use the data above. Wait, the rules say \"Use only the "
        "DATA above. Never invent numbers...\" So I cannot say \"3x its "
        "recent average\" because I don't know the recent average. I can "
        "only state what is observable: $150.0M volume with only +0.4% "
        "move.\n\n"
        "I can say something like: volume is high relative to the price "
        "movement. That's a comparison inherent in the data itself "
        "(volume vs price change), not an invented number.\n\n"
        "Let's draft:\n\n"
        "$ORBIT traded $150.0M in volume while price moved only 0.4% to "
        "$0.8500. That is a large amount of activity for a near-flat "
        "session. Volume this elevated usually accompanies a clearer "
        "directional move, so the mismatch between activity and price "
        "change is worth noting. Either side is absorbing the other, or "
        "the market is waiting for a clearer signal.\n\n"
        "Word count check:\n1. $ORBIT\n2. traded\n3. $150.0M"
    )
    assert is_reasoning_leak(orbit_demo2)
    valid, reason = validate_post(orbit_demo2)
    assert not valid
    assert reason == "Reasoning leak detected", reason


def test_validate_accepts_demo2_nova_post():
    """Demo run 2 NOVA post (via Groq) must still pass — it is a real
    post, and it contains '9.1% from the news moment', a comparison
    computed from the demo's own numbers."""
    from generators.quality_gate import validate_post

    nova2 = (
        "$NOVA launched mainnet, and the headline is \"price will surge on "
        "activation.\" the token opened the session at $100, now trades "
        "around $95.50, a 4.5% dip, while 24h volume rose to $12.0M, up "
        "9.1% from the news moment. the higher volume suggests "
        "participants are still active, yet the price move contradicts the "
        "bullish narrative. if buyers were truly convinced, the price "
        "would likely have held above $100 or at least shown a clear "
        "upward bias alongside the volume. a sustained recovery above the "
        "$100 mark, accompanied by continued volume growth, would be the "
        "simplest way to validate the mainnet optimism."
    )
    valid, reason = validate_post(nova2)
    assert valid, reason


# --- calibration content ---

def test_calibration_covers_all_four_styles():
    for name in ("Analytical Take", "Contrarian View", "Dry Humor", "Data Observation"):
        assert name in VOICE_CALIBRATION


def test_calibration_warns_against_memorizing_structure():
    assert "not the sentence structure" in VOICE_CALIBRATION


def test_editorial_forbidden_covers_template_habits():
    for phrase in (
        "watching from here",
        "monitoring the session",
        "only time will tell",
        "smart money",
    ):
        assert phrase in EDITORIAL_FORBIDDEN
