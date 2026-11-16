# tests/test_klines.py — klines fetch + summarize, BTC context wiring.
"""No network: requests.get is mocked. The klines payload shape is
the real Binance /api/v3/klines row: index 4 = close, index 7 =
quote asset volume."""
import pytest
import requests


def _row(close, quote_volume):
    # [open_time, open, high, low, close, base_vol, close_time, quote_vol, ...]
    return [0, "0", "0", "0", str(close), "0", 0, str(quote_volume),
            0, "0", "0", "0"]


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status}")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _fake_get(captured, resp=None, exc=None):
    def fake(url, params=None, timeout=None, headers=None, verify=None):
        captured.update(url=url, params=params, timeout=timeout)
        if exc is not None:
            raise exc
        return resp
    return fake


# ------------------------------------------------------------- fetch
def test_fetch_parses_close_and_quote_volume(monkeypatch):
    import collectors.klines as kl

    captured = {}
    rows = [_row(1.10 + i * 0.01, 1000.0) for i in range(168)]
    monkeypatch.setattr(kl.requests, "get",
                        _fake_get(captured, _Resp(rows)))
    result = kl.fetch_klines("KITEUSDT")
    assert result is not None
    assert len(result) == 168
    assert result[0] == (1.10, 1000.0)
    assert result[-1][0] == pytest.approx(1.10 + 167 * 0.01)
    assert captured["url"] == kl.KLINES_URL
    assert captured["params"] == {"symbol": "KITEUSDT", "interval": "1h",
                                  "limit": 168}


def test_fetch_returns_none_on_http_error(monkeypatch):
    import collectors.klines as kl

    monkeypatch.setattr(kl.requests, "get",
                        _fake_get({}, _Resp([], status=500)))
    assert kl.fetch_klines("KITEUSDT") is None


def test_fetch_returns_none_on_timeout(monkeypatch):
    import collectors.klines as kl

    monkeypatch.setattr(kl.requests, "get",
                        _fake_get({}, exc=requests.exceptions.Timeout()))
    assert kl.fetch_klines("KITEUSDT") is None


def test_fetch_returns_none_on_bad_json(monkeypatch):
    import collectors.klines as kl

    monkeypatch.setattr(kl.requests, "get",
                        _fake_get({}, _Resp(ValueError("bad json"))))
    assert kl.fetch_klines("KITEUSDT") is None


def test_fetch_returns_none_on_empty_payload(monkeypatch):
    import collectors.klines as kl

    monkeypatch.setattr(kl.requests, "get", _fake_get({}, _Resp([])))
    assert kl.fetch_klines("KITEUSDT") is None


def test_fetch_skips_malformed_rows(monkeypatch):
    import collectors.klines as kl

    rows = [_row(1.0, 100.0) for _ in range(30)] + [["junk"], None]
    monkeypatch.setattr(kl.requests, "get",
                        _fake_get({}, _Resp(rows)))
    result = kl.fetch_klines("KITEUSDT")
    assert result is not None
    assert len(result) == 30


# --------------------------------------------------------- summarize
def _klines(n, close=2.0, quote_volume=2400.0):
    return [(close, quote_volume) for _ in range(n)]


def test_summarize_full_week():
    from collectors.klines import summarize_klines

    # 168 hourly candles x 2400 quote volume = 403,200 total / 7 days.
    out = summarize_klines(_klines(168))
    assert out is not None
    assert out["closes"] == [2.0] * 24
    assert out["volume_7d_avg"] == pytest.approx(57_600.0)


def test_summarize_uses_last_24_closes():
    from collectors.klines import summarize_klines

    klines = [(float(i), 2400.0) for i in range(1, 169)]
    out = summarize_klines(_klines(168)[:0] + klines)
    assert out["closes"] == [float(i) for i in range(145, 169)]


def test_summarize_short_window_averages_over_days_covered():
    from collectors.klines import summarize_klines

    # 48 candles = 2 days: 48 x 2400 / 2 = 57,600.
    out = summarize_klines(_klines(48))
    assert out is not None
    assert out["volume_7d_avg"] == pytest.approx(57_600.0)


def test_summarize_rejects_fewer_than_24_candles():
    from collectors.klines import summarize_klines

    assert summarize_klines(_klines(23)) is None
    assert summarize_klines([]) is None
    assert summarize_klines(None) is None


def test_summarize_rejects_zero_close_or_zero_volume():
    from collectors.klines import summarize_klines

    bad_close = _klines(24)
    bad_close[-1] = (0.0, 2400.0)
    assert summarize_klines(bad_close) is None
    assert summarize_klines(_klines(24, quote_volume=0.0)) is None


# ------------------------------------------------------ BTC context
def test_attach_btc_change_sets_every_token():
    from collectors.binance import attach_btc_change

    tokens = [{"symbol": "BTC", "price_change_percent": 2.5},
              {"symbol": "KITE", "price_change_percent": -7.9},
              {"symbol": "NOVA", "price_change_percent": 18.4}]
    assert attach_btc_change(tokens) == 2.5
    assert all(t["btc_change_24h"] == 2.5 for t in tokens)


def test_attach_btc_change_missing_btc_is_none_not_zero():
    from collectors.binance import attach_btc_change

    tokens = [{"symbol": "KITE", "price_change_percent": -7.9}]
    assert attach_btc_change(tokens) is None
    assert tokens[0]["btc_change_24h"] is None


def test_attach_btc_change_bad_value_is_none():
    from collectors.binance import attach_btc_change

    tokens = [{"symbol": "BTC", "price_change_percent": "n/a"},
              {"symbol": "KITE", "price_change_percent": -7.9}]
    assert attach_btc_change(tokens) is None
    assert tokens[1]["btc_change_24h"] is None
