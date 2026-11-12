"""Cashtag muncul tepat sekali per post.

Regresi dari output user 2026-11-09: satu post $ETH menyebut $ETH
4 kali ("$ETH activity...", "$129.0M volume on $ETH...", "price of
$ETH stayed...", "tracking $ETH."). Penyebabnya tiga lapis:
- prompt menyuruh ulang ticker di tiap kalimat soal harga/volume
  ("MUST include ${symbol} explicitly", "Always refer to the token
  as ${symbol}"),
- cleaner cuma jalan kalau muncul >4 kali (post 4x lolos),
- proofread step 9 selalu menambahkan "tracking $X." di akhir.
"""
from generators.quality_gate import clean_redundant_symbol_references, proofread_post
from prompts.rebate import REBATE_SYSTEM

# Post asli dari user (2026-11-09), $ETH muncul 4 kali.
USER_POST = """$ETH activity increased alongside the move.

the advance held near $2235.54 with only a -0.2% dip and it didn't reverse quickly, which may suggest demand is real.

$129.0M volume on $ETH is relatively high compared with recent sessions, so participants appear more engaged than usual.

price of $ETH stayed around $2235.54 despite the small -0.2% move, which seems modest relative to the volume seen.

buyers continued showing up near current levels, and the reaction looks smaller than what might be expected after such volume.

tracking $ETH."""


def test_cleaner_user_post_four_mentions_become_one():
    cleaned = clean_redundant_symbol_references(USER_POST, "ETH")
    assert cleaned.count("$ETH") == 1
    assert cleaned.startswith("$ETH activity increased alongside the move.")
    # Pengganti menjaga kalimat tetap gramatikal, bukan berlubang.
    assert "$129.0M volume on the token is relatively high" in cleaned
    assert "price of the token stayed around $2235.54" in cleaned
    assert "tracking the token." in cleaned
    # Paragraf tetap utuh (cleaner lama meratakan \n\n jadi spasi).
    assert "\n\n" in cleaned


def test_cleaner_single_mention_untouched():
    post = "$ETH activity increased alongside the move.\n\nthe token held."
    assert clean_redundant_symbol_references(post, "ETH") == post


def test_cleaner_two_mentions_become_one():
    post = "$ETH moved up.\n\nvolume on $ETH stayed high."
    cleaned = clean_redundant_symbol_references(post, "ETH")
    assert cleaned.count("$ETH") == 1
    assert "volume on the token stayed high." in cleaned


def test_cleaner_leaves_other_tickers_alone():
    post = "$ETH moved up while $BTC stayed flat.\n\nvolume on $ETH was high."
    cleaned = clean_redundant_symbol_references(post, "ETH")
    assert cleaned.count("$ETH") == 1
    assert "$BTC stayed flat" in cleaned


def test_cleaner_does_not_match_longer_symbol():
    post = "$ETH moved up.\n\n$ETHUSDT volume was high."
    cleaned = clean_redundant_symbol_references(post, "ETH")
    assert "$ETHUSDT volume was high." in cleaned


def test_proofread_does_not_readd_tracking_ticker():
    cleaned = clean_redundant_symbol_references(USER_POST, "ETH")
    final = proofread_post(cleaned, "ETH")
    assert final.count("$ETH") == 1
    assert "tracking $ETH" not in final
    assert "tracking the token." in final


def test_prompt_orders_ticker_once_only():
    assert "EXACTLY ONCE" in REBATE_SYSTEM
    assert "MUST include ${symbol} explicitly" not in REBATE_SYSTEM
    assert "tracking $TOKEN" not in REBATE_SYSTEM


def test_build_prompt_orders_ticker_once_only():
    from generators.post_generator import build_prompt

    token = {
        "symbol": "ETH",
        "price": 2235.54,
        "price_change_percent": -0.2,
        "volume_24h": 129_000_000,
        "range_position": 0.5,
    }
    prompt = build_prompt(token, "HOT")
    assert "exactly ONCE" in prompt
    assert "Never drop the symbol mid-sentence" not in prompt


def test_generate_post_end_to_end_ticker_once(monkeypatch):
    from generators import post_generator

    monkeypatch.setattr(post_generator, "generate", lambda *a, **k: USER_POST)
    monkeypatch.setattr(post_generator, "is_similar_to_recent", lambda c: False)
    monkeypatch.setattr(post_generator, "add_to_recent", lambda c: None)
    token = {
        "symbol": "ETH",
        "price": 2235.54,
        "price_change_percent": -0.2,
        "volume_24h": 129_000_000,
        "range_position": 0.5,
    }
    result = post_generator.generate_post(token, "HOT", {})
    assert result is not None
    assert result.count("$ETH") == 1
    assert result.startswith("$ETH")
