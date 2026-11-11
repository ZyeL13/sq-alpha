# generators/quality_gate.py
import re
from collections import defaultdict
from storage.post_history import get_recent_posts
from prompts.styles import EDITORIAL_FORBIDDEN

# Patterns that indicate reasoning/planning (HARUS ditolak)
REJECT_PATTERNS = [
    r"(?i)^(okay|alright|sure|let\'s|let me|i need|i will|i\'m going|first,|so,|now,)",
    r"(?i)(let me (think|draft|write|craft|analyze|see|check|try))",
    r"(?i)(i need to (write|create|craft|produce|make|do))",
    r"(?i)(the user (wants|asked|gave|provided|said))",
    r"(?i)^draft",
    r"(?i)^let\'s see",
    r"(?i)^wait[, ]",
    r"(?i)^the user",
    r"(?i)\(example says\)",
    r"(?i)^got it",
    r"(?i)^let\'s start",
    r"(?i)^hmm",
    r"(?i)let me check",
    r"(?i)hold on",
    # Demo 2026-11-09 (BlockRun mistral): chain-of-thought returned as
    # the "post" and passed the old gate. These cover its exact shapes:
    # "We need to produce a short post...", "I need to find an anomaly...",
    # "Let's draft:", "First line: ...", "Let's count approximate...",
    # and the echoed output rules ("No explanations, no reasoning...").
    r"(?i)(we need to (produce|write|create|craft|draft|make|do))",
    r"(?i)(i need to (find|figure out|check|identify|look|see))",
    r"(?i)(let'?s (draft|count|try|start|write|plan))",
    r"(?i)(first line:|paragraph \d|word count|let'?s count)",
    r"(?i)no (explanations|analysis notes|reasoning|drafts)",
    # A bullet list is planning notes, never a post (posts are 1-2
    # prose paragraphs, no lists).
    r"(?m)^\s*[-•]\s",
    # A numbered list ("Word count check:\n1. $ORBIT\n2. traded...") is
    # planning notes, never a post — demo 2, 2026-11-09.
    r"(?m)^\s*\d+[.)]\s",
    # Echoed style guidance ("Data observation style: Let numbers
    # lead...") and meta-commentary about the rules themselves.
    r"(?i)(analytical|contrarian|data observation|dry humor)\s+style\s*:",
    r"(?i)(the rules say|i can say something like)",
]

# For tracking reject reasons
_reject_reasons = defaultdict(int)


# V3 long-form: article sections may use lists and headings, which
# the short-form gate rejects as planning notes. The two list
# patterns are the only ones dropped for articles; every other
# reasoning-leak marker still applies, and the first-word heuristic
# in is_reasoning_leak() is not used for articles at all (a section
# heading is not a planning word).
_LONGFORM_EXCLUDED_PATTERNS = {
    r"(?m)^\s*[-•]\s",
    r"(?m)^\s*\d+[.)]\s",
}
LONGFORM_REJECT_PATTERNS = [
    p for p in REJECT_PATTERNS if p not in _LONGFORM_EXCLUDED_PATTERNS
]

# Minimum article body length (chars). Short posts reject below 100;
# an article below this is a truncated generation, not an article.
LONGFORM_MIN_BODY_CHARS = 600
LONGFORM_MAX_TITLE_CHARS = 200


def _has_leak_patterns(content: str, patterns) -> bool:
    """Pattern-only reasoning-leak scan (no first-word heuristic)."""
    content_lower = content.lower().strip()
    for pattern in patterns:
        if re.search(pattern, content_lower):
            return True
    return False


def is_reasoning_leak(content: str) -> bool:
    """Check if content contains reasoning/planning language."""
    if not content:
        return True

    content_lower = content.lower().strip()
    # Scan the WHOLE content, not just the first 400 chars. Demo 2
    # (2026-11-09) proved the window too narrow: the ORBIT leak looked
    # clean for 400 chars while "Let's draft:" sat at char 711 and
    # "Word count check:" at char 1077. Posts are short (40-120 words)
    # and these markers never occur in a legit post anywhere.
    if _has_leak_patterns(content, REJECT_PATTERNS):
        return True

    if content_lower.startswith('$'):
        return False

    valid_starts = [
        'volume', 'price', 'the', 'a', 'an', 'this', 'that', 'these',
        'watching', 'tracking', 'worth', 'market', 'crypto', 'token',
        'activity', 'momentum', 'sellers', 'buyers', 'trade', 'flow',
        'early', 'low', 'more', 'some', 'strong', 'clean', 'no',
        'buying', 'selling', 'dip', 'pump', 'dump', 'bleed',
        'green', 'red', 'flat', 'range', 'move', 'session',
        'chip', 'gold', 'oil', 'equity', 'sector', 'commodities',
        'holding', 'declining', 'rising', 'down', 'up', 'mixed',
        'consistent', 'notable', 'unusual', 'relative',
        'bid', 'ask', 'spread', 'order', 'book', 'depth',
        'resistance', 'support', 'break', 'reject', 'test',
        'entry', 'exit', 'position', 'size', 'risk',
    ]

    first_word = content_lower.split()[0] if content_lower.split() else ''
    if first_word in valid_starts:
        return False

    # Reasoning often opens with a first-person/planning word that the
    # blanket lowercase pass below would otherwise let through
    # ("We need to produce a short post..." — demo 2026-11-09), or with
    # a fragment of the echoed output rules ("tags" — the tail of
    # "<post> tags", demo 2 ORBIT).
    if first_word in ("we", "i", "let", "lets", "let's", "tags", "tag"):
        return True

    if len(first_word) <= 10 and re.match(r'^[a-z]+$', first_word):
        return False

    return True


def has_editorial_violation(content: str) -> str | None:
    """Editorial v2 check: reject template habits and hype phrases.

    Returns the offending phrase, or None when the content is clean.
    This is what the week-one KPI "0 editorial violations" counts:
    a post that trips this never reaches the queue.
    """
    if not content:
        return None
    lowered = content.lower()
    for phrase in EDITORIAL_FORBIDDEN:
        if phrase in lowered:
            return phrase
    return None


def has_double_symbol(content: str, symbol: str) -> bool:
    """Check if symbol appears more than twice"""
    if not content or not symbol:
        return False
    
    target = f"${symbol.upper()}"
    count = content.upper().count(target)
    
    return count > 2


def clean_redundant_symbol_references(content: str, symbol: str) -> str:
    """Keep the cashtag exactly once (first occurrence).

    Every later $SYMBOL becomes "the token" instead of being deleted,
    so sentences stay grammatical ("volume on the token is high",
    "price of the token stayed") instead of breaking ("volume on is
    high"). Only the post's own symbol is touched — other tickers
    (e.g. $BTC in a comparison) are left alone.
    """
    if not content or not symbol:
        return content

    import re
    symbol_upper = symbol.upper()
    pattern = re.compile(rf"\${re.escape(symbol_upper)}\b", re.IGNORECASE)
    matches = list(pattern.finditer(content))

    if len(matches) <= 1:
        return content

    first_end = matches[0].end()
    head, tail = content[:first_end], content[first_end:]
    return head + pattern.sub("the token", tail)

def proofread_post(content: str, symbol: str) -> str:
    """Clean up formatting, remove redundant phrases, ensure consistent CTA"""
    import re
    
    if not content or not symbol:
        return content
    
    symbol_upper = symbol.upper()
    
    # 1. Hapus "RULES: -" dan sejenisnya di akhir
    content = re.sub(r'RULES:\s*-.*$', '', content, flags=re.IGNORECASE)
    content = re.sub(r'\s*RULES.*$', '', content, flags=re.IGNORECASE)
    
    # 2. Hapus "the price of $X" → "$X price"
    content = re.sub(rf'the price of \${symbol_upper}', rf'${symbol_upper} price', content, flags=re.IGNORECASE)
    content = re.sub(rf'current price of \${symbol_upper}', rf'${symbol_upper} price', content, flags=re.IGNORECASE)
    
    # 3. Hapus CTA ganda di akhir
    content = re.sub(rf'tracking \${symbol_upper}.*$', '', content, flags=re.IGNORECASE)
    content = re.sub(rf'monitoring \${symbol_upper}.*$', '', content, flags=re.IGNORECASE)
    content = re.sub(rf'watching \${symbol_upper}.*$', '', content, flags=re.IGNORECASE)
    
    # 4. Hapus double dollar $$ → $ (tapi jangan sentuh $10M)
    content = re.sub(r'\$\$(\d+)', r'$\1', content)
    
    # 5. Format angka harga dengan $ dan desimal yang sesuai
    # SKIP jika angka diikuti huruf (seperti 10M) atau sudah ada $
    def format_price(match):
        num_str = match.group(1)
        # Cek apakah angka diikuti huruf (volume seperti 10M)
        next_char_pos = match.end()
        if next_char_pos < len(content) and content[next_char_pos].isalpha():
            return match.group(0)  # Biarkan saja (ini volume)
        try:
            num = float(num_str)
            if num < 0.001:
                return f"${num:.7f}"
            elif num < 1:
                return f"${num:.4f}"
            else:
                return f"${num:.2f}"
        except:
            return match.group(0)
    
    # Cari angka dengan 4+ desimal, lewati yang sudah ada $ di depannya
    content = re.sub(r'(?<!\$)(\d+\.\d{4,})', format_price, content)
    
    # 6. Jika tidak ada blank line, pecah berdasarkan kalimat
    if '\n\n' not in content:
        # Split berdasarkan titik, tanda tanya, atau seru diikuti spasi
        sentences = re.split(r'(?<=[.!?])\s+', content)
        if len(sentences) > 1:
            # Jika ada kalimat yang terlalu panjang (>100 kata), split juga berdasarkan ","
            # Gabungkan 2 kalimat per paragraf
            paragraphs = []
            for i in range(0, len(sentences), 2):
                para = ' '.join(sentences[i:i+2])
                paragraphs.append(para)
            content = '\n\n'.join(paragraphs)

    # 7. Konsisten: 1 blank line antar paragraf
    content = re.sub(r'\n{3,}', '\n\n', content)
    content = re.sub(r'\n{2,}', '\n\n', content)
    
    # 8. Tambahkan $SYMBOL di awal hanya jika tidak ada sama sekali.
    # (Kalau ticker sudah ada di tengah, jangan tambah lagi di depan —
    # cleaner di atas sudah memastikan ticker cuma muncul sekali.)
    if f"${symbol_upper}" not in content.upper():
        content = f"${symbol_upper} " + content

    # 9. No forced sign-off. Editorial v2 forbids template closers
    # ("watching from here", "monitoring the session", "tracking the
    # move"): a post ends where its observation ends. The old code
    # appended "tracking the move." here — removed.
    content = content.strip()
    # 10. Perbaiki spasi ganda
    content = re.sub(r' {2,}', ' ', content)
    
    # 11. Pastikan ada blank line antar paragraf
    # Jika masih tidak ada blank line, split berdasarkan ". "
    if '\n\n' not in content:
        parts = content.split('. ')
        if len(parts) > 3:
            # Kelompokkan 2-3 kalimat per paragraf
            new_parts = []
            for i in range(0, len(parts), 2):
                new_parts.append('. '.join(parts[i:i+2]))
            content = '.\n\n'.join(new_parts)
            if not content.endswith('.'):
                content += '.'
    return content.strip()

def validate_post(content: str, symbol: str = None) -> tuple[bool, str]:
    """Validate post content."""
    if not content:
        return False, "Empty content"

    if symbol and has_double_symbol(content, symbol):
        return False, "Double symbol detected"
    
    if is_reasoning_leak(content):
        return False, "Reasoning leak detected"

    violation = has_editorial_violation(content)
    if violation:
        return False, f"Editorial violation: {violation}"

    if len(content) < 100:
        return False, "Content too short"

    content = re.sub(r'\$([A-Z]+)[\'"]?s\b', r'$\1', content)

    return True, content


def validate_longform(title: str, content: str, symbol: str = None) -> tuple[bool, str]:
    """Validate a long-form article (title + body) — V3 Phase 1.

    Same no-fabrication / no-advice / editorial rules as short posts,
    but article sections may use lists and headings, so the two list
    patterns and the first-word heuristic of the short-form gate do
    NOT apply here. The exactly-1-cashtag rule is enforced by the
    caller (clean_redundant_symbol_references); this gate rejects a
    cashtag in the title, which would break the count.
    Returns (True, cleaned_body) or (False, reason).
    """
    if not title or not title.strip():
        return False, "Missing title"
    title = title.strip()
    if len(title) > LONGFORM_MAX_TITLE_CHARS:
        return False, "Title too long"
    if "$" in title:
        return False, "Cashtag in title"

    if not content:
        return False, "Empty content"
    content = content.strip()
    if len(content) < LONGFORM_MIN_BODY_CHARS:
        return False, f"Article too short ({len(content)} chars)"

    if symbol and has_double_symbol(content, symbol):
        return False, "Double symbol detected"

    # Pattern-only leak scan (filtered list); no first-word heuristic:
    # a section heading is legitimate in an article.
    if _has_leak_patterns(content, LONGFORM_REJECT_PATTERNS):
        return False, "Reasoning leak detected"

    violation = has_editorial_violation(content)
    if violation:
        return False, f"Editorial violation: {violation}"

    content = re.sub(r'\$([A-Z]+)[\'"]?s\b', r'$\1', content)

    return True, content


def finalize_post(content: str, symbol: str) -> str:
    """Final cleanup and add symbol if missing."""
    content = content.strip()

    if content.startswith(f'${symbol}'):
        content = content[len(f'${symbol}'):].lstrip()
        content = re.sub(r'^[.,\s]+', '', content)

    content = f"${symbol} " + content
    content = re.sub(r' {2,}', ' ', content)
    content = re.sub(r'\n{3,}', '\n\n', content)
    content = re.sub(r'\.\s*$', '.', content)
#    content = re.sub(r'(?<!\$)\b(\d+\.\d{2})\b', r'$\1', content)
    return content


def is_similar_to_recent(content: str, threshold: float = 0.85) -> bool:
    """Check if content is too similar to recent posts."""
    if not get_recent_posts():
        return False

    words = set(content.lower().split())
    for prev in get_recent_posts()[-5:]:
        prev_words = set(prev.lower().split())
        if not words or not prev_words:
            continue
        intersection = words.intersection(prev_words)
        similarity = len(intersection) / max(len(words), len(prev_words))
        if similarity > threshold:
            return True
    return False





