# processors/score.py
import math
from typing import Dict, Any

from config import (
    MOMENTUM_WEIGHT,
    ANOMALY_WEIGHT,
    WALLET_WEIGHT,
    LIQUIDITY_WEIGHT,
    FRESHNESS_WEIGHT,
    MIN_TOTAL_SCORE,
    MIN_PRIMARY_SCORE,
)

def momentum_score(token: Dict[str, Any]) -> float:
    """Score based on price momentum (0-1)"""
    chg = token.get("price_change_percent", 0)
    # Map: -20% = 0, 0% = 0.5, +20% = 1.0
    normalized = (chg + 20) / 40
    return max(0.0, min(1.0, normalized))


def anomaly_score(token: Dict[str, Any]) -> float:
    """
    Volume vs price contradiction.
    High volume + small price move = anomaly
    But only for tokens with reasonable market cap (not mega caps)
    """
    vol = token.get("volume_24h", 0)
    chg = abs(token.get("price_change_percent", 0))
    symbol = token.get("symbol", "")
    
    # Skip mega caps (BTC, ETH, BNB, SOL, XRP)
    MEGA_CAPS = {"BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "DOT", "LINK"}
    if symbol in MEGA_CAPS:
        return 0.2  # low anomaly, normal behavior
    
    # For smaller tokens, detect contradiction
    if vol > 100_000_000 and chg < 1.0:
        return 0.9
    elif vol > 50_000_000 and chg < 2.0:
        return 0.7
    elif vol > 10_000_000 and chg < 3.0:
        return 0.5
    elif vol < 1_000_000 and chg > 10:
        return 0.8
    else:
        return 0.2


def wallet_score(token: Dict[str, Any]) -> float:
    """
    Trade size clustering.
    High trade count + large avg trade = institutional
    """
    trade_count = token.get("trade_count", 0)
    volume = token.get("volume_24h", 0)
    
    if trade_count == 0 or volume == 0:
        return 0.5
    
    avg_trade = volume / trade_count
    
    if avg_trade > 50_000:
        return 0.9  # whale territory
    elif avg_trade > 10_000:
        return 0.7  # larger hands
    elif avg_trade < 500:
        return 0.3  # retail noise
    else:
        return 0.5


def freshness_score(token: Dict[str, Any]) -> float:
    """Newly listed = high score"""
    age = token.get("age_hours", 100)
    if age < 6:
        return 1.0 - (age / 24)  # 0-6h: 1.0 to 0.75
    elif age < 24:
        return 0.7 - ((age - 6) / 36)  # 6-24h: 0.75 to 0.25
    elif age < 48:
        return 0.25 - ((age - 24) / 48)  # 24-48h: 0.25 to 0
    else:
        return 0.0


def liquidity_score(token: Dict[str, Any]) -> float:
    """Based on 24h volume"""
    vol = token.get("volume_24h", 0)
    
    if vol > 500_000_000:
        return 1.0
    elif vol > 100_000_000:
        return 0.9
    elif vol > 50_000_000:
        return 0.8
    elif vol > 10_000_000:
        return 0.6
    elif vol > 1_000_000:
        return 0.4
    elif vol > 100_000:
        return 0.2
    else:
        return 0.1


def compute_scores(token: Dict[str, Any]) -> Dict[str, float]:
    """Return all scores for a token"""
    scores = {
        "momentum": momentum_score(token),
        "anomaly": anomaly_score(token),
        "wallet": wallet_score(token),
        "freshness": freshness_score(token),
        "liquidity": liquidity_score(token),
    }
    
    # Risk score (inverse of safety)
    safety = (scores["liquidity"] + scores["anomaly"]) / 2
    scores["risk"] = 1.0 - min(1.0, safety)
    
    return scores


def get_primary_score(category: str, scores: Dict[str, float]) -> float:
    """Get the most relevant score for a category.

    LOSERS is inverted: momentum maps a big drop to a low value, but for
    a LOSERS post a big drop is exactly the signal, so use 1 - momentum.
    """
    if category == "LOSERS":
        return 1.0 - scores.get("momentum", 0.5)
    primary_map = {
        "HOT": "anomaly",
        "GAINERS": "momentum",
        "NEW": "freshness",
        "ALPHA": "wallet",
        "SIGNAL": "wallet",
    }
    key = primary_map.get(category, "anomaly")
    return scores.get(key, 0.5)


def total_score(scores: Dict[str, float]) -> float:
    """Weighted total from the config weights (they sum to 1.0)."""
    weights = {
        "momentum": MOMENTUM_WEIGHT,
        "anomaly": ANOMALY_WEIGHT,
        "wallet": WALLET_WEIGHT,
        "liquidity": LIQUIDITY_WEIGHT,
        "freshness": FRESHNESS_WEIGHT,
    }
    return sum(scores.get(k, 0.0) * w for k, w in weights.items())


def score_token(token: Dict[str, Any], category: str) -> Dict[str, Any]:
    """Score one token for a category and decide if it is worth posting.

    Passes when the weighted total clears MIN_TOTAL_SCORE, or when the
    category's primary signal is strong (MIN_PRIMARY_SCORE) even if the
    total is low — e.g. a LOSERS token whose momentum drags the total
    down but whose drop itself is the story.
    """
    scores = compute_scores(token)
    total = total_score(scores)
    primary = get_primary_score(category, scores)
    passes = total >= MIN_TOTAL_SCORE or primary >= MIN_PRIMARY_SCORE
    return {"scores": scores, "total": total, "primary": primary, "passes": passes}
