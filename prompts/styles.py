import random

HOOKS = {
    "HOT": [
        "volume picked up while price stayed relatively flat.",
        "activity increased around current levels.",
        "more volume than expected for this move.",
    ],
    "GAINERS": [
        "strong move with volume still active.",
        "price moved higher and interest hasn't faded yet.",
        "momentum is still holding for now.",
    ],
    "LOSERS": [
        "price pulled back sharply today.",
        "selling pressure remains visible.",
        "momentum weakened into this session.",
    ],
    "ALPHA": [
        "worth a closer look based on recent activity.",
        "market activity here looks more active than usual.",
        "this one is seeing steady interest.",
    ],
    "NEW": [
        "early trading is setting the range.",
        "first sessions are shaping price discovery.",
        "new listing activity remains active.",
    ],
    "SIGNAL": [
        "activity is picking up quietly.",
        "not much attention here yet, but flow is active.",
        "volume behavior stands out slightly.",
    ],
}

ANGLES = {
    "anomaly": [
        "volume expanded faster than price movement.",
        "market activity looks stronger than price suggests.",
    ],
    "accumulation": [
        "trading activity stayed consistent near these levels.",
        "buyers are still active around current price.",
    ],
    "relative_strength": [
        "holding better than nearby names.",
        "showing more stability than expected.",
    ],
    "underreaction": [
        "price reaction has been fairly muted so far.",
        "market response still looks limited.",
    ],
    "distribution": [
        "upside is meeting resistance near current range.",
        "price is testing whether buyers stay active.",
    ],
    "capitulation": [
        "selling pace may be slowing.",
        "downside momentum looks less aggressive now.",
    ],
}

CTA_VARIANTS = [
    "tracking ${symbol}.",
    "watching ${symbol}.",
    "${symbol} on watchlist.",
    "monitoring ${symbol}.",
]

TRANSITIONS = [
    "worth noting:",
    "key detail:",
    "for context:",
]

def get_hook(category: str) -> str:
    return random.choice(HOOKS.get(category, HOOKS["HOT"]))

def get_angle(angle_type: str = None) -> str:
    if angle_type and angle_type in ANGLES:
        return random.choice(ANGLES[angle_type])
    pool = [line for values in ANGLES.values() for line in values]
    return random.choice(pool)

def get_cta(symbol: str) -> str:
    return random.choice(CTA_VARIANTS).replace("${symbol}", f"${symbol}")

def get_transition(probability=0.2) -> str:
    if random.random() > probability:
        return ""
    return random.choice(TRANSITIONS)
