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
