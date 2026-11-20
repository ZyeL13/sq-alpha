# tests/test_snapshot.py — CardSnapshot: one ticker + klines + BTC bundle.
"""No network: the klines fetch is injected. build_snapshot fails
only on unusable klines data — a missing BTC change still yields a
snapshot with btc_change None."""
import pytest


def _token(**overrides):
    token = {
        "symbol": "KITE",
        "full_symbol": "KITEUSDT",
        "price": 2.40,
        "price_change_percent": -7.9,
        "volume_24h": 3_200_000,
        "high_24h": 2.80,
        "low_24h": 2.10,
        "btc_change_24h": 2.1,
    }
    token.update(overrides)
    return token


def _klines(n=168, close=2.0, quote_volume=2400.0):
    return [(close, quote_volume) for _ in range(n)]


def test_build_snapshot_bundles_all_three_sources():
    from schedulers.snapshot import build_snapshot

    seen = {}

    def fake_fetch(symbol):
        seen["symbol"] = symbol
        return _klines()

    snap = build_snapshot(_token(), fetch=fake_fetch)
    assert snap is not None
    assert seen["symbol"] == "KITEUSDT"
    assert snap.closes == [2.0] * 24
    assert snap.volume_7d_avg == pytest.approx(57_600.0)
    assert snap.btc_change == 2.1
    assert snap.token["symbol"] == "KITE"


def test_build_snapshot_defaults_full_symbol_from_symbol():
    from schedulers.snapshot import build_snapshot

    seen = {}

    def fake_fetch(symbol):
        seen["symbol"] = symbol
        return _klines()

    token = _token()
    del token["full_symbol"]
    assert build_snapshot(token, fetch=fake_fetch) is not None
    assert seen["symbol"] == "KITEUSDT"


def test_build_snapshot_none_when_fetch_fails():
    from schedulers.snapshot import build_snapshot

    assert build_snapshot(_token(), fetch=lambda s: None) is None


def test_build_snapshot_none_when_too_few_candles():
    from schedulers.snapshot import build_snapshot

    assert build_snapshot(_token(), fetch=lambda s: _klines(10)) is None


def test_build_snapshot_missing_btc_still_valid():
    from schedulers.snapshot import build_snapshot

    token = _token()
    del token["btc_change_24h"]
    snap = build_snapshot(token, fetch=lambda s: _klines())
    assert snap is not None
    assert snap.btc_change is None
    assert snap.btc_relative is None


def test_build_snapshot_bad_btc_value_is_none():
    from schedulers.snapshot import build_snapshot

    snap = build_snapshot(_token(btc_change_24h="n/a"),
                          fetch=lambda s: _klines())
    assert snap is not None
    assert snap.btc_change is None


def test_derived_signals():
    from schedulers.snapshot import CardSnapshot

    snap = CardSnapshot(token=_token(), closes=[2.0] * 24,
                        volume_7d_avg=1_000_000, btc_change=2.1)
    assert snap.volume_ratio == pytest.approx(3.2)
    assert snap.btc_relative == pytest.approx(-10.0)
    assert snap.range_position == pytest.approx((2.40 - 2.10) / 0.70)
    assert snap.range_width_pct == pytest.approx(0.70 / 2.40 * 100)


def test_range_helpers_without_real_range():
    from schedulers.snapshot import range_position_of, range_width_pct_of

    token = _token(high_24h=0, low_24h=0)
    assert range_position_of(token) == 0.5
    assert range_width_pct_of(token) is None
    assert range_position_of(_token(high_24h=0, low_24h=0,
                                    range_position=0.3)) == 0.3


# ------------------------------------------------- step 1: to_dict / prompt dict
def test_to_dict_omits_none_fields():
    from schedulers.snapshot import CardSnapshot

    snap = CardSnapshot(token=_token(), closes=[2.0] * 24,
                        volume_7d_avg=1_000_000, btc_change=None)
    d = snap.to_dict()
    assert "btc_change" not in d
    assert "btc_relative" not in d
    assert d["symbol"] == "KITE"
    assert d["price"] == 2.40
    assert d["change_24h"] == -7.9
    assert d["closes"] == [2.0] * 24
    assert d["volume_ratio"] == pytest.approx(3.2)


def test_to_dict_includes_btc_fields_when_present():
    from schedulers.snapshot import CardSnapshot

    snap = CardSnapshot(token=_token(), closes=[2.0] * 24,
                        volume_7d_avg=1_000_000, btc_change=2.1)
    d = snap.to_dict()
    assert d["btc_change"] == 2.1
    assert d["btc_relative"] == pytest.approx(-10.0)


def test_snapshot_dict_for_prompt_token_only():
    from schedulers.snapshot import snapshot_dict_for_prompt

    d = snapshot_dict_for_prompt(_token())
    assert d["symbol"] == "KITE"
    assert d["change_24h"] == -7.9
    assert d["btc_relative"] == pytest.approx(-10.0)
    assert "closes" not in d  # sparkline data never reaches the prompt
    token = _token()
    del token["btc_change_24h"]
    d = snapshot_dict_for_prompt(token)
    assert "btc_change" not in d
    assert "btc_relative" not in d


def test_snapshot_dict_for_prompt_drops_closes():
    from schedulers.snapshot import CardSnapshot, snapshot_dict_for_prompt

    snap = CardSnapshot(token=_token(), closes=[2.0] * 24,
                        volume_7d_avg=1_000_000, btc_change=2.1)
    d = snapshot_dict_for_prompt(_token(), snap)
    assert "closes" not in d
    assert d["volume_7d_avg"] == 1_000_000
    assert d["btc_relative"] == pytest.approx(-10.0)


# ------------------------------------------------- step 1: card assertions
def _snap_for_assert(**overrides):
    from schedulers.snapshot import CardSnapshot

    token = _token()
    token.update(overrides.pop("token", {}))
    return CardSnapshot(token=token, closes=overrides.pop("closes", [2.0] * 24),
                        volume_7d_avg=overrides.pop("volume_7d_avg", 1_000_000),
                        btc_change=overrides.pop("btc_change", 2.1))


def test_card_assertions_pass_on_valid_snapshot():
    from schedulers.card_renderer import assert_snapshot_for_card

    assert_snapshot_for_card(_snap_for_assert())  # no raise


def test_card_assertions_fail_price_outside_range():
    from schedulers.card_renderer import CardRenderError, assert_snapshot_for_card

    with pytest.raises(CardRenderError):
        assert_snapshot_for_card(_snap_for_assert(token={"price": 9.99}))


def test_card_assertions_fail_short_closes():
    from schedulers.card_renderer import CardRenderError, assert_snapshot_for_card

    with pytest.raises(CardRenderError):
        assert_snapshot_for_card(_snap_for_assert(closes=[2.0] * 23))


def test_card_assertions_fail_nonpositive_close():
    from schedulers.card_renderer import CardRenderError, assert_snapshot_for_card

    closes = [2.0] * 24
    closes[5] = 0.0
    with pytest.raises(CardRenderError):
        assert_snapshot_for_card(_snap_for_assert(closes=closes))


def test_card_assertions_fail_bad_volume_avg():
    from schedulers.card_renderer import CardRenderError, assert_snapshot_for_card

    with pytest.raises(CardRenderError):
        assert_snapshot_for_card(_snap_for_assert(volume_7d_avg=0))


def test_card_assertions_fail_btc_relative_mismatch():
    from types import SimpleNamespace

    from schedulers.card_renderer import CardRenderError, assert_snapshot_for_card

    # btc_relative is a derived property on CardSnapshot, so a real
    # snapshot can never disagree with itself — exercise the branch
    # with a stand-in carrying a stored (wrong) value, which is all
    # the assertion function ever reads.
    snap = SimpleNamespace(
        token=_token(), closes=[2.0] * 24, volume_7d_avg=1_000_000,
        btc_change=2.1, btc_relative=-5.0)  # recomputed is -10.0
    with pytest.raises(CardRenderError):
        assert_snapshot_for_card(snap)
    snap.btc_relative = -10.0
    assert_snapshot_for_card(snap)  # no raise within tolerance
    # Missing BTC context skips the check entirely.
    snap.btc_change = None
    snap.btc_relative = None
    assert_snapshot_for_card(snap)
