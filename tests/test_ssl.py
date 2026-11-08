"""SSL verification must stay enabled — Fase 3 langkah 2.

Regression test for the Fase 1 critical finding: Binance requests and
the Binance Square POST used `verify=False`, sending market data and
the Square API key over unverified TLS.
"""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_binance_verify_is_a_ca_bundle():
    from collectors.binance import _VERIFY

    # Must be a path to a CA bundle (Termux cert or certifi), never False.
    assert _VERIFY, "_VERIFY must not be False"
    assert isinstance(_VERIFY, str)
    assert os.path.exists(_VERIFY), f"CA bundle not found: {_VERIFY}"


def test_no_verify_false_in_network_code():
    for path in ("collectors/binance.py", "schedulers/poster.py"):
        with open(os.path.join(REPO_ROOT, path)) as f:
            source = f.read()
        assert "verify=False" not in source, f"{path} still contains verify=False"
        assert "disable_warnings" not in source, f"{path} still disables warnings"
