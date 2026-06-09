import random

# ─────────────────────────────────────────────
# HOOKS
# Data-first. Fewer generic statements.
# ─────────────────────────────────────────────

HOOKS = {
    "HOT": [
        "unusual activity appeared without an obvious catalyst.",
        "volume expanded faster than price reacted.",
        "activity jumped while price stayed near current levels.",
        "participation increased without a major breakout.",
        "unusual activity appeared during an otherwise quiet session.",
    ],

    "GAINERS": [
        "strong move with volume confirmation.",
        "volume stayed elevated after the move.",
        "this rally attracted more participation than recent attempts.",
        "buyers remained active after the initial move.",
        "price advanced while volume continued expanding.",
    ],

    "LOSERS": [
        "drop accelerated despite relatively light volume.",
        "buyers have yet to respond aggressively.",
        "selling pressure remained active throughout the session.",
        "volume expanded while price continued lower.",
        "the pullback attracted more activity than usual.",
    ],

    "ALPHA": [
        "activity increased without a visible catalyst.",
        "volume expanded faster than price reacted.",
        "volume expanded while price stayed mostly unchanged.",
        "more participation than recent sessions would suggest.",
        "unusual activity appeared on a low-attention token.",
        "interest increased despite limited price movement.",
    ],

    "NEW": [
        "early trading is establishing the initial range.",
        "price discovery remains in progress.",
        "volume is beginning to establish a baseline.",
        "the first trading sessions remain active.",
    ],

    "SIGNAL": [
        "activity increased before price reacted meaningfully.",
        "volume expanded ahead of the move.",
        "participation changed before the chart followed.",
        "activity picked up inside a relatively quiet range.",
    ],
}

HOOKS_COMMENTARY = {
    "COMMENTARY": [
        "semis diverging while mega-cap tech cools.",
        "crypto volume up, price reaction mixed.",
        "rotation looks sector-specific, not broad.",
        "macro data landed, market response was muted.",
        "correlation between BTC and altcoins breaking down this session.",
        "risk appetite looks selective today.",
        "vol up across the board but leaders and laggards swapped.",
        "this kind of divergence usually resolves within a few sessions.",
    ],
    "OPINION": [
        "worth asking: rotation or temporary noise?",
        "is this a sector shift or just a noisy session?",
        "one of those days where the data and the narrative don't match.",
        "volume says one thing, price says another.",
        "not obvious which way this resolves.",
        "the move looks real, follow-through is the question.",
    ],
}

# ─────────────────────────────────────────────
# ANGLES
# Observable interpretation only. Low-confidence language required.
# Use: may, appears, looks, seems, still early
# ─────────────────────────────────────────────

ANGLES = {
    "anomaly": [
        "volume appears elevated relative to the size of the move.",
        "activity is running above recent norms.",
        "participation looks stronger than price action alone suggests.",
        "volume-to-price behavior appears unusual.",
    ],

    "divergence": [
        "volume expanded faster than price.",
        "activity increased without a comparable move in price.",
        "participation changed while the chart remained relatively stable.",
    ],

    "relative_strength": [
        "holding up better than nearby names.",
        "showing more resilience than similar tokens.",
        "price remains relatively stable compared to peers.",
    ],

    "breakout_watch": [
        "price is approaching a recently important level.",
        "the current range appears close to resolution.",
        "recent trading has compressed into a tighter range.",
    ],
}

ANGLES_COMPARISON = {
    "comparison": [
        "$TOKEN_A up {chg_a}% while $TOKEN_B moved only {chg_b}%.",
        "$TOKEN_A outperforming $TOKEN_B by a notable margin this session.",
        "$TOKEN_A volume significantly higher than $TOKEN_B despite similar price moves.",
        "momentum in $TOKEN_A appears stronger than $TOKEN_B so far.",
        "$TOKEN_A holding gains while $TOKEN_B pulled back.",
    ],
}
# ─────────────────────────────────────────────
# CTA
# Click encouragement only. No hype, no calls.
# ─────────────────────────────────────────────

CTA_VARIANTS = [
    "tracking ${symbol}.",
    "watching ${symbol}.",
    "${symbol} on watchlist.",
    "monitoring ${symbol}.",
]

# ─────────────────────────────────────────────
# TRANSITIONS
# Use rarely. Factual connectors only.
# ─────────────────────────────────────────────

TRANSITIONS = [
    "worth noting:",
    "for context:",
    "key detail:",
]

# ─────────────────────────────────────────────
# CLOSERS
# Neutral. No edge, no persona.
# ─────────────────────────────────────────────

CLOSERS = [
    "the next few sessions should clarify the move.",
    "follow-through matters from here.",
    "still needs confirmation from price action.",
    "worth watching if activity stays elevated.",
    "momentum looks active for now.",
]

ANGLES.update(ANGLES_COMPARISON)
# ─────────────────────────────────────────────
# GETTERS
# ─────────────────────────────────────────────

def get_hook(category: str) -> str:
    return random.choice(HOOKS.get(category, HOOKS["HOT"]))

def get_angle(angle_type: str = None) -> str:
    if angle_type and angle_type in ANGLES:
        return random.choice(ANGLES[angle_type])
    pool = [line for values in ANGLES.values() for line in values]
    return random.choice(pool)

def get_cta(symbol: str) -> str:
    return random.choice(CTA_VARIANTS).replace("${symbol}", f"${symbol}")

def get_transition(probability: float = 0.2) -> str:
    if random.random() > probability:
        return ""
    return random.choice(TRANSITIONS)

from config import CLOSER_ENABLED
def get_closer(probability: float = 0.3) -> str:
    if not CLOSER_ENABLED:
        return ""
    if random.random() > probability:
        return ""
    return random.choice(CLOSERS)

# Helper untuk comparison posts (butuh 2 tokens)
def get_comparison_hook(symbol_a: str, chg_a: float, symbol_b: str, chg_b: float) -> str:
    import random
    templates = [
        f"${symbol_a} +{chg_a:.1f}% while ${symbol_b} moved only +{chg_b:.1f}%.",
        f"${symbol_a} outperforming ${symbol_b} by a wide margin today.",
        f"${symbol_a} and ${symbol_b} diverging, same sector, different tape.",
        f"${symbol_a} moved. ${symbol_b} didn't follow.",
    ]
    return random.choice(templates)
