"""Market-cap enrichment for ALPHA — Fase 3 langkah 4.

Offline: CoinGecko / CoinMarketCap calls are mocked.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _token(symbol="XYZ", market_cap=0):
    return {
        "symbol": symbol,
        "full_symbol": f"{symbol}USDT",
        "price": 1.50,
        "price_change_percent": 0.5,
        "volume_24h": 100_000,
        "volume_rank": 50,
        "market_cap": market_cap,
        "trade_count": 1000,
        "age_hours": 100,
    }


def test_enrich_tokens_sets_market_cap(monkeypatch):
    import collectors.coingecko as cg

    def fake_top(limit=100, vs_currency="usd"):
        return [
            {"symbol": "xyz", "market_cap": 4_000_000, "price_change_24h": 1.0,
             "volume_24h": 90_000},
            {"symbol": "btc", "market_cap": 1_000_000_000_000, "price_change_24h": 0.5,
             "volume_24h": 10_000_000_000},
        ]

    monkeypatch.setattr(cg, "get_top_coins_market_data", fake_top)
    out = cg.enrich_tokens([_token("XYZ"), _token("BTC"), _token("UNKNOWN")])
    assert out[0]["market_cap"] == 4_000_000
    assert out[0]["enriched_by"] == "coingecko"
    assert out[1]["market_cap"] == 1_000_000_000_000
    assert out[2]["market_cap"] == 0  # not covered: stays unknown


def test_enrich_single_token_keeps_backwards_compat(monkeypatch):
    import collectors.coingecko as cg

    monkeypatch.setattr(
        cg, "get_top_coins_market_data",
        lambda limit=100, vs_currency="usd": [
            {"symbol": "xyz", "market_cap": 2_000_000, "price_change_24h": 0.0,
             "volume_24h": 50_000},
        ],
    )
    out = cg.enrich_binance_token(_token("XYZ"))
    assert out["market_cap"] == 2_000_000
    assert out["coingecko_market_cap"] == 2_000_000


def test_cmc_enrich_is_noop_without_key(monkeypatch):
    import collectors.coinmarketcap as cmc

    monkeypatch.setattr(cmc, "CMC_API_KEY", None)
    tokens = [_token("XYZ")]
    assert cmc.enrich_tokens_cmc(tokens) == tokens
    assert tokens[0]["market_cap"] == 0


def test_cmc_enrich_fills_missing_only(monkeypatch):
    import collectors.coinmarketcap as cmc

    monkeypatch.setattr(cmc, "CMC_API_KEY", "test-key")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"XYZ": [{"quote": {"USD": {"market_cap": 3_000_000}}}],
                            "ABC": [{"quote": {"USD": {"market_cap": 9_000_000}}}]}}

    calls = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        calls["url"] = url
        calls["headers"] = headers
        calls["params"] = params
        return FakeResp()

    monkeypatch.setattr(cmc.requests, "get", fake_get)
    tokens = [_token("XYZ"), _token("ABC", market_cap=8_000_000)]
    out = cmc.enrich_tokens_cmc(tokens)
    assert out[0]["market_cap"] == 3_000_000
    assert out[0]["enriched_by"] == "coinmarketcap"
    assert out[1]["market_cap"] == 8_000_000  # already known: untouched
    assert calls["headers"]["X-CMC_PRO_API_KEY"] == "test-key"


def test_alpha_end_to_end_with_enrichment(monkeypatch):
    """Enriched small cap -> ALPHA; unenriched token -> not ALPHA."""
    import collectors.coingecko as cg
    from processors.classify import classify

    monkeypatch.setattr(
        cg, "get_top_coins_market_data",
        lambda limit=100, vs_currency="usd": [
            {"symbol": "xyz", "market_cap": 4_000_000, "price_change_24h": 0.5,
             "volume_24h": 100_000},
        ],
    )
    enriched = cg.enrich_tokens([_token("XYZ"), _token("UNKNOWN")])
    assert classify(enriched[0]) == "ALPHA"
    assert classify(enriched[1]) is None
