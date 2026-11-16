# tests/test_dry_run_cards.py — the dry-run script produces its
# 10 pairs (8 cards + 2 text-only) from fixed sample data.
"""Runs the script as a subprocess with no font dir (DejaVu
fallback). No network, no publishing."""
import os
import subprocess
import sys

import pytest

pytest.importorskip("PIL")


def test_dry_run_produces_pairs(tmp_path):
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(repo_root, "scripts", "dry_run_cards.py")
    out = tmp_path / "dry-run"
    env = dict(os.environ)
    env.pop("KALAM_FONT_DIR", None)
    result = subprocess.run(
        [sys.executable, script, "--out", str(out)],
        capture_output=True, text=True, timeout=120, env=env,
        cwd=repo_root)
    assert result.returncode == 0, result.stdout + result.stderr

    cards = sorted(p for p in os.listdir(out) if p.endswith(".png"))
    assert len(cards) == 8, cards
    for name in ("01-nova.png", "02-rust.png", "03-orbt.png",
                 "04-moth.png", "05-kite.png", "06-pale.png",
                 "07-volt.png", "08-wren.png"):
        assert name in cards
        assert os.path.getsize(out / name) > 1024

    with open(out / "pairs.txt") as f:
        pairs = f.read()
    for card_type in ("volume_spike", "range_squeeze", "thin_tape",
                      "relative_weakness"):
        assert card_type in pairs
    assert "TEXT ONLY (no card type matched)" in pairs
    assert "TEXT ONLY (klines fetch failed)" in pairs
    assert pairs.count("Q: ") == 8
