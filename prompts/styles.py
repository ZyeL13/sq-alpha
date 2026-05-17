import random

HOOKS = {
    "HOT": [
        "volume is loud. price barely reacts.",
        "something is being absorbed here.",
        "the move looks smaller than the flow.",
        "activity is rising. conviction isn't obvious yet.",
    ],
    "GAINERS": [
        "green candles hide a lot of behavior.",
        "up only, until it isn't.",
        "price is moving faster than attention.",
        "strength is visible. conviction is less obvious.",
    ],
    "LOSERS": [
        "red attracts attention. not always clarity.",
        "the selloff looks emotional.",
        "weak hands usually move first.",
        "price is fading faster than interest.",
    ],
    "ALPHA": [
        "wallet behavior looks cleaner than price action.",
        "trade flow is more interesting than the chart.",
        "someone is positioning quietly.",
        "not much noise around this one.",
    ],
    "NEW": [
        "first days usually reveal intent fast.",
        "new listings exaggerate everything.",
        "price discovery gets messy early.",
        "attention is fresh. conviction isn't.",
    ],
    "SIGNAL": [
        "low noise. interesting flow.",
        "quiet charts sometimes matter more.",
        "not much attention here yet.",
        "small cap, unusual behavior.",
    ],
}

ANGLES = {
    "anomaly": [
        "volume and price aren't aligned yet.",
        "flow suggests more activity than price reflects.",
    ],
    "accumulation": [
        "wallet rotation looks controlled.",
        "positions appear to be building slowly.",
    ],
    "relative_strength": [
        "holding structure better than nearby names.",
        "less weakness than expected in this tape.",
    ],
    "underreaction": [
        "market response feels muted.",
        "attention hasn't caught up yet.",
    ],
    "distribution": [
        "strength is meeting supply overhead.",
        "buyers are getting tested here.",
    ],
    "capitulation": [
        "forced exits may be slowing down.",
        "panic behavior looks less aggressive now.",
    ],
}

CTA_VARIANTS = [
    "tracking ${symbol}.",
    "watching ${symbol}.",
    "keeping an eye on ${symbol}.",
    "${symbol} on radar.",
]

TRANSITIONS = [
    "worth noting:",
    "closer look:",
    "key detail:",
    "what stands out:",
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

def get_transition(probability=0.35) -> str:
    if random.random() > probability:
        return ""
    return random.choice(TRANSITIONS)
