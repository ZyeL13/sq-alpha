# generators/style_guard.py
import re
from collections import deque
from typing import List, Tuple

# Banned repetitive phrases
BANNED_PHRASES = [
    "the data suggests",
    "it is important to note",
    "as you can see",
    "in conclusion",
    "to summarize",
    "based on the analysis",
    "it's worth noting",
    "it should be noted",
    "from a technical perspective",
    "in the current market environment",
    "under the surface",
    "quiet divergence",
    "signal:",
    "layer 2:",
    "tape says",
    "market hasn't noticed",
    "nobody's talking about it",
    "something's shifting",
]

# Too generic sentences (should trigger rewrite)
GENERIC_SENTENCES = [
    r"price is (up|down) \d+\.?\d*%",
    r"volume is \$\d+\.?\d*[MB]",
    r"the token is trading at",
    r"investors should be cautious",
    r"this is not financial advice",
    r"always do your own research",
]

class StyleGuard:
    def __init__(self, history_size: int = 10):
        self.recent_posts: deque = deque(maxlen=history_size)
    
    def contains_banned_phrase(self, text: str) -> bool:
        """Check if text contains any banned phrase"""
        text_lower = text.lower()
        for phrase in BANNED_PHRASES:
            if phrase in text_lower:
                return True
        return False
    
    def has_generic_pattern(self, text: str) -> bool:
        """Check if text contains generic trading phrases"""
        for pattern in GENERIC_SENTENCES:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    
    def is_similar_to_recent(self, text: str, threshold: float = 0.7) -> bool:
        """
        Simple similarity check based on shared words
        Returns True if too similar to any recent post
        """
        if not self.recent_posts:
            return False
        
        words = set(text.lower().split())
        for prev in self.recent_posts:
            prev_words = set(prev.lower().split())
            if len(words) == 0 or len(prev_words) == 0:
                continue
            intersection = words.intersection(prev_words)
            similarity = len(intersection) / max(len(words), len(prev_words))
            if similarity > threshold:
                return True
        return False
    
    def add_post(self, text: str):
        """Add post to history"""
        self.recent_posts.append(text)
    
    def validate(self, text: str) -> Tuple[bool, str]:
        """
        Validate post style.
        Returns (is_valid, reason_or_cleaned)
        """
        if self.contains_banned_phrase(text):
            return False, "Contains banned phrase"
        
        if self.has_generic_pattern(text):
            return False, "Contains generic pattern"
        
        if self.is_similar_to_recent(text):
            return False, "Too similar to recent post"
        
        return True, text


# Singleton instance
_guard: StyleGuard = None

def get_guard() -> StyleGuard:
    global _guard
    if _guard is None:
        _guard = StyleGuard()
    return _guard

def validate_post_style(text: str) -> Tuple[bool, str]:
    """Convenience function"""
    return get_guard().validate(text)

def record_post(text: str):
    """Record post for future similarity check"""
    get_guard().add_post(text)
