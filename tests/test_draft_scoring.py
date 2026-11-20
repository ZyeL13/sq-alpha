"""Mechanical draft scoring (spec 5.2): 45 signal / 30 specificity
/ 25 freshness, no LLM judge. Specificity counts only numbers with a
market unit (%, x, $, vol) matched against the token's own numbers.
"""
import pytest

from processors.draft_scoring import (
    DraftScore,
    _match_cited,
    extract_opener,
    find_unmatched_numbers,
    pick_winner,
    score_draft,
)


def _token(**overrides):
    token = {
        "symbol": "NOVA",
        "price": 1.35,
        "price_change_percent": 4.2,
        "volume_24h": 106_000_000,
        "high_24h": 1.42,
        "low_24h": 1.08,
        "btc_change_24h": 2.1,
        "volume_ratio_7d": 3.2,
    }
    token.update(overrides)
    return token


def _post(body: str) -> str:
    """A draft body padded past the 100-char validation floor."""
    text = "$NOVA " + body
    if len(text) < 110:
        text += " the session stayed orderly and the tape gave no reason to look away from the chart."
    return text


# ------------------------------------------------------------- signal
def test_signal_scales_total_score():
    s = score_draft(_post("is doing that thing again."), _token(), 0.8)
    assert s.signal == pytest.approx(36.0)
    s = score_draft(_post("is doing that thing again."), _token(), 0.0)
    assert s.signal == 0.0


def test_signal_clamps_above_one():
    s = score_draft(_post("is doing that thing again."), _token(), 1.5)
    assert s.signal == 45.0


# -------------------------------------------------------- specificity
def test_specificity_counts_unit_numbers_matched_to_token():
    content = _post("jumped +4.2% to $1.35 on volume 3.2x the 7-day average, "
                    "with $106.0M traded.")
    s = score_draft(content, _token(), 0.5)
    assert s.matched == ("change", "price", "volume", "volume_ratio")
    assert s.specificity == 30.0


def test_specificity_one_citation_counts_once_in_tight_range():
    # Found by the dry-run: $1.015 sits within 2% of price, high AND
    # low in a 3% range, and used to earn three credits. One cited
    # number earns at most one.
    token = _token(price=1.015, price_change_percent=1.2,
                   high_24h=1.03, low_24h=1.00,
                   volume_ratio_7d=1.4)
    content = _post("squeezed +1.2% to $1.015 inside a tight range all day, "
                    "barely moving while the rest of the board chopped.")
    s = score_draft(content, token, 0.5)
    assert s.matched == ("change", "price")
    assert s.specificity == 15.0


def test_specificity_percent_matching_two_fields_counts_once():
    # +2.1% equals both the BTC change and (here) the token change.
    token = _token(price_change_percent=2.1, btc_change_24h=2.1)
    content = _post("added +2.1% in line with the wider market move, "
                    "holding gains into the close without much fuss.")
    s = score_draft(content, token, 0.5)
    assert len(s.matched) == 1
    assert s.specificity == 7.5


def test_specificity_caps_at_four_numbers():
    content = _post("jumped +4.2% to $1.35, high $1.42, low $1.08, volume "
                    "3.2x, $106.0M traded, BTC +2.1%.")
    s = score_draft(content, _token(), 0.5)
    assert s.specificity == 30.0
    assert len(s.matched) >= 4


def test_specificity_ignores_bare_numbers():
    content = _post("held for 3 days, a top 10 move, 5 traders watching, "
                    "range position 0.82, 2 sessions in a row.")
    s = score_draft(content, _token(), 0.5)
    assert s.specificity == 0.0
    assert s.matched == ()


def test_specificity_ignores_unmatched_unit_numbers():
    # Unit-carrying numbers that are NOT the token's numbers earn nothing.
    content = _post("jumped +9.9% to $9.99 on volume 9.9x, $999.0M traded.")
    s = score_draft(content, _token(), 0.5)
    assert s.specificity == 0.0


def test_specificity_repeated_citation_counts_once():
    content = _post("jumped +4.2%, and +4.2% again, still +4.2% on the day.")
    s = score_draft(content, _token(), 0.5)
    assert s.matched == ("change",)
    assert s.specificity == 7.5


def test_specificity_vol_marker_matches_ratio():
    content = _post("volume 3.2 while the price barely moved at all today.")
    s = score_draft(content, _token(), 0.5)
    assert "volume_ratio" in s.matched


def test_specificity_dollar_ticker_is_not_a_price():
    # $1UP in the text must not parse as a $1 price citation.
    content = _post("is doing that thing again, unlike $1UP which faded.")
    s = score_draft(content, _token(price=1.0), 0.5)
    assert "price" not in s.matched


def test_specificity_rounding_tolerance():
    # Cited 1-decimal values match 2-decimal actuals.
    content = _post("jumped +4.2% to $1.35 on the session.")
    s = score_draft(content, _token(price_change_percent=4.24, price=1.349), 0.5)
    assert "change" in s.matched
    assert "price" in s.matched


def test_specificity_small_prices_use_relative_tolerance():
    content = _post("jumped +4.2% to $0.0001234 on the session.")
    s = score_draft(content, _token(price=0.0001234), 0.5)
    assert "price" in s.matched
    content2 = _post("jumped +4.2% to $0.0009 on the session.")
    s2 = score_draft(content2, _token(price=0.0001234), 0.5)
    assert "price" not in s2.matched


def test_specificity_btc_relative_matches_percent():
    # Token +6.3, BTC +2.1 -> relative +4.2 pts, cited as a percent.
    # The three percent values must differ: one citation earns one
    # key, the first matching field in class order.
    content = _post("outran the market by +4.2% on the session.")
    s = score_draft(content, _token(price_change_percent=6.3), 0.5)
    assert "btc_relative" in s.matched


def test_specificity_uses_snapshot_ratio_when_present():
    class Snap:
        volume_ratio = 2.0
    content = _post("volume 2.0x the 7-day average today.")
    token = _token()
    del token["volume_ratio_7d"]
    s = score_draft(content, token, 0.5, snapshot=Snap())
    assert "volume_ratio" in s.matched


def test_specificity_bad_token_numbers_do_not_crash():
    token = _token(price="n/a", price_change_percent=None, volume_24h="x")
    s = score_draft(_post("jumped +4.2% to $1.35."), token, 0.5)
    assert s.specificity == 0.0


# ---------------------------------------------------------- freshness
def test_freshness_full_when_opener_is_new():
    s = score_draft(_post("is doing that thing again today."), _token(), 0.5,
                    recent_openers=["$nova slipped 4% on thin volume today as"])
    assert s.freshness == 25.0


def test_freshness_zero_on_opener_repeat():
    opener = "$nova slipped 4% on thin volume today as"
    content = opener + " the session wore on and nothing changed at all for the token."
    s = score_draft(content, _token(), 0.5, recent_openers=[opener])
    assert s.freshness == 0.0


def test_freshness_compares_first_eight_words_only():
    opener = "$nova slipped 4% on thin volume today as"
    content = opener + " something completely different happens later in this post body."
    s = score_draft(content, _token(), 0.5, recent_openers=[opener + " other tail words here"])
    assert s.freshness == 0.0


def test_extract_opener_normalizes():
    assert extract_opener("$NOVA   Slipped\n4%  ON thin") == "$nova slipped 4% on thin"
    assert extract_opener("short") == "short"
    assert extract_opener("") == ""


# --------------------------------------------------------- hard reject
def test_hard_reject_empty_content():
    assert score_draft("", _token(), 0.5) is None
    assert score_draft(None, _token(), 0.5) is None


def test_hard_reject_failed_validation():
    assert score_draft("too short", _token(), 0.5) is None
    leak = "$NOVA let's draft a post about the move " + "x" * 80
    assert score_draft(leak, _token(), 0.5) is None


# ------------------------------------------------------------ picking
def test_pick_winner_highest_total_earliest_tie():
    scores = [DraftScore(50, 30, 20, 0), DraftScore(70, 40, 30, 0),
              DraftScore(70, 40, 30, 0)]
    assert pick_winner(scores) == 1
    assert pick_winner(scores[:1]) == 0


def test_pick_winner_empty_raises():
    with pytest.raises(ValueError):
        pick_winner([])


def test_total_is_sum_of_components():
    s = score_draft(_post("jumped +4.2% to $1.35."), _token(), 0.8)
    assert s.total == pytest.approx(s.signal + s.specificity + s.freshness)
    assert "signal=" in s.components_str()


# ------------------------------------------- find_unmatched_numbers
# (JSON validator's number check: same numbers dict the validator
# tests use — plain snapshot numbers, no token enrichment.)
_NUMBERS = {
    "change": 4.2,
    "price": 1.35,
    "volume_ratio": 3.2,
    "btc_change": 2.1,
    "btc_relative": 2.1,
    "volume": 106_000_000,
    "high": 1.42,
    "low": 1.08,
}


def test_find_unmatched_numbers_all_matched():
    content = "$XYZ jumped +4.2% to $1.35 on volume 3.2x the 7-day average."
    assert find_unmatched_numbers(content, _NUMBERS) == []


def test_find_unmatched_numbers_reports_unmatched():
    content = "$XYZ jumped +9.9% on the session."
    assert "+9.9%" in find_unmatched_numbers(content, _NUMBERS)


def test_find_unmatched_numbers_unmatched_dollar_and_ratio():
    content = "$XYZ jumped to $5.55 on volume 7.7x the average."
    unmatched = find_unmatched_numbers(content, _NUMBERS)
    assert "$5.55" in unmatched
    assert "7.7x" in unmatched


def test_find_unmatched_numbers_ignores_bare_digits():
    content = "$XYZ held for 3 days, a top 10 move."
    assert find_unmatched_numbers(content, _NUMBERS) == []


def test_find_unmatched_numbers_one_citation_one_key():
    # +2.1% equals both change and btc_change: one citation, one key.
    content = "$XYZ added +2.1% in line with the wider market move."
    numbers = dict(_NUMBERS, change=2.1, btc_change=2.1)
    assert _match_cited(content, numbers) == {"change"}
    assert find_unmatched_numbers(content, numbers) == []
