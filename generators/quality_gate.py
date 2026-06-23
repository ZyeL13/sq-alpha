# generators/quality_gate.py
import re

# Patterns that indicate reasoning/planning (HARUS ditolak)
REJECT_PATTERNS = [
    r"(?i)^(okay|alright|sure|let's|let me|i need|i will|i'm going|first,|so,|now,)",
    r"(?i)(let me (think|draft|write|craft|analyze|see|check|try))",
    r"(?i)(i need to (write|create|craft|produce|make|do))",
    r"(?i)(the user (wants|asked|gave|provided|said))",
    r"(?i)^draft",
    r"(?i)^let's see",
    r"(?i)^wait[, ]",
    r"(?i)^the user",
    r"(?i)\(example says\)",
    r"(?i)^got it",
    r"(?i)^let's start",
    r"(?i)^hmm",
    r"(?i)let me check",
    r"(?i)hold on",
]

# Track recent posts for similarity check
_recent_posts = []


def is_reasoning_leak(content: str) -> bool:
    """Check if content contains reasoning/planning language."""
    if not content:
        return True

    content_lower = content.lower().strip()
    first_part = content_lower[:400]
    for pattern in REJECT_PATTERNS:
        if re.search(pattern, first_part):
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

    if len(first_word) <= 10 and re.match(r'^[a-z]+$', first_word):
        return False

    return True


def has_double_symbol(content: str, symbol: str) -> bool:
    """Check if symbol appears more than twice"""
    if not content or not symbol:
        return False
    
    target = f"${symbol.upper()}"
    count = content.upper().count(target)
    
    return count > 2


def clean_redundant_symbol_references(content: str, symbol: str) -> str:
    """Remove $SYMBOL from middle, keep only first and last occurrence"""
    if not content or not symbol:
        return content
    
    import re
    symbol_upper = symbol.upper()
    pattern = re.compile(rf'\${re.escape(symbol_upper)}', re.IGNORECASE)
    matches = list(pattern.finditer(content))
    
    # Hanya bersihkan jika muncul lebih dari 2 kali
    if len(matches) <= 4:
        return content
    
    # Hapus hanya yang di tengah (pertahankan 2: awal dan akhir)
    keep_indices = {matches[0].start(), matches[-1].start()}
    result = []
    last_end = 0
    for match in matches:
        start, end = match.start(), match.end()
        if start in keep_indices:
            result.append(content[last_end:end])
        else:
            # Skip this $SYMBOL, add space instead
            result.append(content[last_end:start])
        last_end = end
    result.append(content[last_end:])
    
    cleaned = ''.join(result)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

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
    
    # 8. Tambahkan $SYMBOL di awal jika hilang
    if not content.startswith(f"${symbol_upper}"):
        content = f"${symbol_upper} " + content
    
    # 9. Tambahkan CTA di akhir jika tidak ada
    content = content.strip()
    cta_pattern = rf'tracking \${symbol_upper}\.'
    if not re.search(cta_pattern, content, re.IGNORECASE):
        content += f"\n\ntracking ${symbol_upper}."
    
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

    if len(content) < 100:
        return False, "Content too short"

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
    if not _recent_posts:
        return False

    words = set(content.lower().split())
    for prev in _recent_posts[-5:]:
        prev_words = set(prev.lower().split())
        if not words or not prev_words:
            continue
        intersection = words.intersection(prev_words)
        similarity = len(intersection) / max(len(words), len(prev_words))
        if similarity > threshold:
            return True
    return False


def record_post(content: str):
    """Add post to history."""
    _recent_posts.append(content)
    if len(_recent_posts) > 20:
        _recent_posts.pop(0)


def get_reject_stats():
    """Return stats about common reject reasons"""
    pass
