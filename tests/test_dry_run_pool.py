"""Smoke test: scripts/dry_run_pool.py runs hermetically (no network,
no LLM, no posting) and prints the scored drafts + winner.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_dry_run_pool_exits_zero_and_names_a_winner(tmp_path):
    out = tmp_path / "pool-dry-run"
    proc = subprocess.run(
        [sys.executable, "scripts/dry_run_pool.py",
         "--out", str(out), "--pool-size", "5"],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "DRY RUN" in proc.stdout
    assert "WINNER: $NOVA" in proc.stdout
    assert "DRAFTS" in proc.stdout
    assert "JSON REPLIES + VALIDATION" in proc.stdout
    assert "ABSTAIN: no" in proc.stdout
    report = out / "report.txt"
    assert report.exists()
    assert "WINNER: $NOVA" in report.read_text()
    assert "ABSTAIN: no" in report.read_text()
    # The winner's draft validated against its snapshot numbers.
    assert "valid=True" in proc.stdout
    # _schedule_winner wrote the per-post CSV row to the dry-run state.
    csv_path = out / "state" / "posts.csv"
    assert csv_path.exists()
    csv_text = csv_path.read_text()
    assert "NOVA" in csv_text
    assert "unknown" in csv_text  # no LLM in dry-run: provider is unknown
    # The winner is an image post: exactly one card rendered.
    cards = list((out / "cards").glob("*.png"))
    assert len(cards) == 1
    assert cards[0].name.startswith("NOVA_")
