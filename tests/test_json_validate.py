"""JSON draft validation (step 1, spec §2.3 steps 2-5).

`parse_json_reply` + `validate_draft_json` in generators/json_validate.py.
"""
import json

from generators.json_validate import parse_json_reply, validate_draft_json

NUMBERS = {
    "change": 4.2,
    "price": 1.35,
    "volume_ratio": 3.2,
    "btc_change": 2.1,
    "btc_relative": 2.1,
    "volume": 106_000_000,
    "high": 1.42,
    "low": 1.08,
}

_POST = ("$XYZ jumped +4.2% to $1.35 on volume 3.2x the 7-day average, "
         "and the tape stayed orderly while the move held into the close.")


def _draft(**overrides):
    d = {
        "event": "XYZ rallied on strong volume",
        "fact": "Price +4.2% to $1.35, volume 3.2x the 7-day average",
        "interpretation": "Buyers stepped in without chasing",
        "angle": "surprise",
        "post": _POST,
    }
    d.update(overrides)
    return d


def _as_json(d):
    return json.dumps(d)


# ---------------------------------------------------------------- parse
def test_parse_plain_json():
    assert parse_json_reply(_as_json(_draft())) == _draft()


def test_parse_fenced_json():
    text = "```json\n" + _as_json(_draft()) + "\n```"
    assert parse_json_reply(text) == _draft()


def test_parse_fenced_json_no_language_tag():
    text = "```\n" + _as_json(_draft()) + "\n```"
    assert parse_json_reply(text) == _draft()


def test_parse_json_with_surrounding_prose():
    text = "Here is the JSON you asked for:\n" + _as_json(_draft()) + \
        "\nHope that helps!"
    assert parse_json_reply(text) == _draft()


def test_parse_unparseable_text_returns_none():
    assert parse_json_reply("no json here at all") is None
    assert parse_json_reply("```\nnot json\n```") is None
    assert parse_json_reply("") is None
    assert parse_json_reply(None) is None


def test_parse_non_dict_json_returns_none():
    assert parse_json_reply("[1, 2, 3]") is None
    assert parse_json_reply('"just a string"') is None


# --------------------------------------------------------------- fields
def test_validate_passes_on_good_draft():
    assert validate_draft_json(_draft(), "surprise", NUMBERS,
                               symbol="XYZ") == (True, None)


def test_validate_missing_post():
    d = _draft()
    del d["post"]
    assert validate_draft_json(d, "surprise", NUMBERS,
                               symbol="XYZ") == (False, "json_missing_field")


def test_validate_missing_angle():
    d = _draft()
    del d["angle"]
    assert validate_draft_json(d, "surprise", NUMBERS,
                               symbol="XYZ") == (False, "json_missing_field")


def test_validate_non_string_value():
    d = _draft(fact=42)
    assert validate_draft_json(d, "surprise", NUMBERS,
                               symbol="XYZ") == (False, "json_missing_field")


def test_validate_empty_post():
    d = _draft(post="")
    assert validate_draft_json(d, "surprise", NUMBERS,
                               symbol="XYZ") == (False, "json_missing_field")


# ---------------------------------------------------------------- angle
def test_validate_angle_mismatch():
    assert validate_draft_json(_draft(), "shrug", NUMBERS,
                               symbol="XYZ") == (False, "angle_mismatch")


# -------------------------------------------------------------- numbers
def test_validate_numbers_matching_pass():
    # +4.2% (change), $1.35 (price), 3.2x (volume_ratio) all match.
    assert validate_draft_json(_draft(), "surprise", NUMBERS,
                               symbol="XYZ") == (True, None)


def test_validate_unmatched_percent_fails():
    d = _draft(post="$XYZ jumped +9.9% to $1.35 on the session, "
                    "holding gains into the close.")
    assert validate_draft_json(d, "surprise", NUMBERS,
                               symbol="XYZ") == (False, "number_not_in_snapshot")


def test_validate_unmatched_dollar_fails():
    d = _draft(post="$XYZ jumped +4.2% to $5.55 on the session, "
                    "holding gains into the close.")
    assert validate_draft_json(d, "surprise", NUMBERS,
                               symbol="XYZ") == (False, "number_not_in_snapshot")


def test_validate_unmatched_ratio_fails():
    d = _draft(post="$XYZ jumped +4.2% to $1.35 on volume 7.7x "
                    "the 7-day average today.")
    assert validate_draft_json(d, "surprise", NUMBERS,
                               symbol="XYZ") == (False, "number_not_in_snapshot")


def test_validate_bare_digits_ignored():
    d = _draft(post="$XYZ held for 3 days, a top 10 move, +4.2% "
                    "to $1.35 on the session.")
    assert validate_draft_json(d, "surprise", NUMBERS,
                               symbol="XYZ") == (True, None)


def test_validate_rounding_within_tolerance_passes():
    # Snapshot -5.37% vs post "-5.4%" (unicode minus): 0.03 <= 0.15.
    numbers = dict(NUMBERS, change=-5.37)
    d = _draft(post="$XYZ slipped \u22125.4% to $1.35 on the session, "
                    "giving back the morning gains.")
    assert validate_draft_json(d, "surprise", numbers,
                               symbol="XYZ") == (True, None)


def test_validate_derived_claim_without_literal_number_fails():
    # "volume doubled" implies 2.0x, but the snapshot ratio is 3.2x:
    # the derived number is cited, the literal snapshot number is not.
    d = _draft(post="$XYZ volume doubled to 2.0x the 7-day average, "
                    "and the move held into the close.")
    assert validate_draft_json(d, "surprise", NUMBERS,
                               symbol="XYZ") == (False, "number_not_in_snapshot")


# -------------------------------------------------------------- cashtag
def test_validate_cashtag_not_first():
    d = _draft(post="XYZ jumped +4.2% to $1.35 on volume 3.2x "
                    "the 7-day average today.")
    assert validate_draft_json(d, "surprise", NUMBERS,
                               symbol="XYZ") == (False, "cashtag_not_first")


def test_validate_cashtag_matching_start_passes():
    assert validate_draft_json(_draft(), "surprise", NUMBERS,
                               symbol="XYZ") == (True, None)


def test_validate_cashtag_check_is_case_insensitive():
    d = _draft(post="$xyz jumped +4.2% to $1.35 on volume 3.2x "
                    "the 7-day average today.")
    assert validate_draft_json(d, "surprise", NUMBERS,
                               symbol="XYZ") == (True, None)


# ------------------------------------------------------- forbidden phrase
def test_validate_forbidden_phrase():
    d = _draft(post="$XYZ smart money jumped +4.2% to $1.35 on volume "
                    "3.2x the 7-day average today.")
    assert validate_draft_json(d, "surprise", NUMBERS,
                               symbol="XYZ") == (False, "forbidden_phrase")
