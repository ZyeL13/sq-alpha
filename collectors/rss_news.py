# collectors/rss_news.py
import calendar
import re
import time
import feedparser
import logging
import requests
from typing import List, Dict, Any

log = logging.getLogger(__name__)

# Berita lebih tua dari ini tidak lagi dipakai sebagai katalis: target
# post adalah <=1 jam sejak kejadian (lihat audit berita Fase 1).
NEWS_MAX_AGE_SECONDS = 3600

# Hanya sumber yang valid dan cepat.
# theblock + cryptoslate ditambah Langkah 8 — keduanya diverifikasi
# live (200 + RSS valid + tanggal terbit terbaca) pada 2026-11-08.
# Pengumuman resmi Binance TIDAK ditambah: Binance tidak menyediakan
# RSS resmi (https://www.binance.com/en/support/announcement/rss
# mengembalikan 202 kosong), dan scraping halaman pengumuman tanpa
# jalur resmi tidak dilakukan.
RSS_SOURCES = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "decrypt": "https://decrypt.co/feed",
    "theblock": "https://www.theblock.co/rss.xml",
    "cryptoslate": "https://cryptoslate.com/feed/",
}

RELEVANT_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "binance", "bnb",
    "crypto", "blockchain", "defi", "nft", "web3", "altcoin", "token",
    "listing", "launch", "airdrop", "upgrade", "fork", "halving",
    "regulation", "sec", "fed", "inflation", "etf",
]

def parse_entry_timestamp(entry: Dict[str, Any]) -> float:
    """Epoch (UTC) dari tanggal terbit sebuah entri feed.

    feedparser sudah menormalisasi pubDate ke `published_parsed`
    (struct_time UTC) untuk semua format umum — RFC-822, GMT, ISO-8601.
    Pakai itu, jangan parse string tanggal manual: pemotongan string
    lama (`published[:25]` + strptime %z) selalu gagal dan membuat
    semua artikel jatuh ke fallback "sekarang".

    Kembalikan 0.0 kalau entri tidak punya tanggal yang bisa dipercaya:
    umur artikel yang tidak diketahui tidak boleh dianggap baru.
    """
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return 0.0
    try:
        return float(calendar.timegm(parsed))
    except Exception:
        return 0.0


def is_fresh(article: Dict[str, Any], max_age_seconds: int = NEWS_MAX_AGE_SECONDS,
             now: float = None) -> bool:
    """True kalau artikel masih dalam batas umur (default 1 jam).

    Artikel tanpa timestamp yang bisa dipercaya (timestamp 0) dianggap
    basi — lebih aman membuangnya daripada menempelkan berita yang
    mungkin sudah berhari-hari sebagai katalis "hari ini".
    """
    ts = article.get("timestamp", 0) or 0
    if ts <= 0:
        return False
    if now is None:
        now = time.time()
    return (now - ts) <= max_age_seconds


def fetch_feed(source_name: str, url: str, max_articles: int = 10, timeout: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch and parse RSS feed from a single source with timeout.
    """
    try:
        # Gunakan requests untuk kontrol timeout
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        
        articles = []
        for entry in feed.entries[:max_articles]:
            published = entry.get('published', entry.get('updated', ''))
            pub_time = parse_entry_timestamp(entry)
            if pub_time <= 0:
                log.warning(f"No trustworthy date for article in {source_name}: "
                            f"{entry.get('title', '')[:80]!r}")
            
            articles.append({
                "title": entry.get('title', ''),
                "link": entry.get('link', ''),
                "summary": entry.get('summary', '')[:300],
                "published": published,
                "timestamp": pub_time,
                "source": source_name,
            })
        return articles
    except requests.exceptions.Timeout:
        log.warning(f"Timeout fetching {source_name}")
        return []
    except requests.exceptions.RequestException as e:
        log.warning(f"Request error fetching {source_name}: {e}")
        return []
    except Exception as e:
        log.error(f"Unexpected error fetching {source_name}: {e}")
        return []

def is_relevant(article: Dict[str, Any]) -> bool:
    text = (article.get('title', '') + ' ' + article.get('summary', '')).lower()
    return any(kw in text for kw in RELEVANT_KEYWORDS)

def fetch_all_news(max_per_source: int = 5,
                   max_age_seconds: int = NEWS_MAX_AGE_SECONDS) -> List[Dict[str, Any]]:
    all_articles = []
    for source_name, url in RSS_SOURCES.items():
        print(f"  📡 Fetching {source_name}...")
        articles = fetch_feed(source_name, url, max_per_source)
        fresh = [a for a in articles if is_fresh(a, max_age_seconds)]
        dropped = len(articles) - len(fresh)
        if dropped:
            print(f"  ⏳ {source_name}: dropped {dropped} stale/undated articles")
        for article in fresh:
            if is_relevant(article):
                all_articles.append(article)
        time.sleep(1)  # Jeda antar sumber
    
    all_articles.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    print(f"  📰 Fetched {len(all_articles)} relevant news articles")
    return all_articles[:20]


# ---------- Matching berita ke token (skor relevansi) ----------
#
# Dulu: substring murni (`symbol in title+summary`) — $SOL cocok dengan
# "solution", $ETH dengan "tether"/"method", $ONE dengan "someone".
# Sekarang: word-boundary untuk simbol Latin, substring hanya untuk
# simbol non-Latin, plus nama lengkap/alias, semuanya diberi skor dan
# di bawah threshold tidak ditempel sebagai katalis.

# Nama lengkap / alias untuk 20 token teratas (nama resmi proyek —
# bukan alias karangan). Dipakai agar "Ethereum upgrade" cocok ke ETH
# meskipun simbolnya tidak disebut.
TOKEN_NAMES = {
    "BTC": ["bitcoin"],
    "ETH": ["ethereum", "ether"],
    "BNB": ["binance coin"],
    "SOL": ["solana"],
    "XRP": ["ripple"],
    "DOGE": ["dogecoin"],
    "ADA": ["cardano"],
    "TRX": ["tron"],
    "AVAX": ["avalanche"],
    "LINK": ["chainlink"],
    "DOT": ["polkadot"],
    "LTC": ["litecoin"],
    "BCH": ["bitcoin cash"],
    "NEAR": ["near protocol"],
    "UNI": ["uniswap"],
    "ATOM": ["cosmos"],
    "XLM": ["stellar"],
    "ETC": ["ethereum classic"],
    "HBAR": ["hedera"],
    "TON": ["toncoin"],
}

# Simbol yang juga kata umum bahasa Inggris. Kata "one"/"apt"/"sol"
# sebagai kata biasa (bukan cashtag, bukan nama proyek) hampir selalu
# bukan tentang tokennya — "ONE more reason", "apt analysis".
# Untuk simbol-simbol ini, kecocokan kata biasa hanya bernilai setengah
# (di bawah threshold sendirian); yang lolos adalah bentuk $CASHTAG
# ("$APT", "$ONE") atau nama lengkap proyek ("Aptos", "Harmony" tidak
# ada di TOKEN_NAMES — sengaja, karena "harmony" juga kata umum).
COMMON_WORD_SYMBOLS = {
    "APT", "ONE", "SOL", "DOT", "NEAR", "LINK", "ATOM", "GAS", "HOT",
    "SUN", "WIN", "VET", "AMP", "BAT", "DASH", "BAND",
}

# Bobot sumber (dipakai sebagai pengali skor). theblock/cryptoslate 1.5:
# outlet crypto-native dengan liputan orisinal yang umumnya memecah
# berita lebih cepat dari tiga media lama (1.0). Bukan sumber primer
# resmi — tidak ada sumber primer dengan RSS yang bisa diverifikasi
# (lihat catatan di RSS_SOURCES). Bobot tidak meloloskan match lemah:
# sebutan simbol di summary saja (1.0 x 1.5 = 1.5) tetap di bawah
# threshold 2.0.
SOURCE_WEIGHTS = {
    "coindesk": 1.0,
    "cointelegraph": 1.0,
    "decrypt": 1.0,
    "theblock": 1.5,
    "cryptoslate": 1.5,
}

# Skor minimal agar artikel ditempel sebagai katalis. Disengaja 2.0:
# satu sebutan simbol di summary saja (1.0) tidak cukup — harus ada di
# judul, atau nama lengkapnya disebut, atau bentuk $CASHTAG-nya.
MATCH_THRESHOLD = 2.0


def get_source_weight(source: str) -> float:
    return SOURCE_WEIGHTS.get(source, 1.0)


def _word_in(text: str, phrase: str) -> bool:
    """True kalau `phrase` muncul sebagai kata/frasa utuh di `text`."""
    pattern = r"\b" + r"\s+".join(re.escape(w) for w in phrase.split()) + r"\b"
    return re.search(pattern, text, re.IGNORECASE) is not None


def _cashtag_in(text: str, symbol: str) -> bool:
    """True kalau bentuk $SIMBOL muncul di `text` (tidak peduli kapital)."""
    return re.search(r"\$" + re.escape(symbol) + r"\b", text, re.IGNORECASE) is not None


def score_article_for_symbol(symbol: str, article: Dict[str, Any]) -> float:
    """Skor relevansi artikel terhadap sebuah simbol (0 = tidak relevan).

    Judul berbobot lebih tinggi dari summary; nama lengkap lebih tinggi
    dari simbol; bentuk $CASHTAG tidak kena penalti kata-umum karena
    cashtag tidak ambigu. Simbol non-Latin (mis. $币安人生) tetap
    dicocokkan sebagai substring — word boundary tidak berlaku untuk
    aksara CJK. Skor akhir dikali bobot sumber artikel.
    """
    if not symbol:
        return 0.0
    title = article.get("title", "") or ""
    summary = article.get("summary", "") or ""

    # Per lokasi (judul / summary): nama lengkap ditambah sinyal simbol
    # terkuat di lokasi itu. Bentuk $CASHTAG dan kata biasa di lokasi
    # yang sama adalah satu kemunculan yang sama — diambil max-nya,
    # bukan dijumlah (kalau tidak, "$SOL rallies" terhitung ganda).
    def _location_score(text: str, name_points: float,
                        cashtag_points: float, word_points: float) -> float:
        pts = 0.0
        for name in TOKEN_NAMES.get(symbol.upper(), []):
            if _word_in(text, name):
                # Jangan hitung "ethereum" kalau teks sebenarnya menyebut
                # "ethereum classic" (milik ETC) — begitu juga
                # "bitcoin" di dalam "bitcoin cash" (milik BCH).
                shadowed = any(
                    other != name and other.startswith(name + " ")
                    and _word_in(text, other)
                    for names in TOKEN_NAMES.values() for other in names
                )
                if not shadowed:
                    pts += name_points
                break
        if symbol.isascii() and symbol.isalnum():
            symbol_pts = 0.0
            if _cashtag_in(text, symbol):
                # Bentuk $CASHTAG selalu dihitung penuh — tidak ambigu.
                symbol_pts = cashtag_points
            elif _word_in(text, symbol):
                # Kata biasa; simbol kata-umum hanya setengah nilai.
                is_common_word = symbol.upper() in COMMON_WORD_SYMBOLS
                symbol_pts = word_points / 2 if is_common_word else word_points
            pts += symbol_pts
        else:
            # Simbol non-Latin: substring (mis. 币安人生). Word boundary
            # tidak ada artinya untuk aksara CJK.
            if symbol.lower() in text.lower():
                pts += word_points
        return pts

    score = (_location_score(title, 3.0, 2.0, 2.0)
             + _location_score(summary, 2.0, 1.0, 1.0))

    if score <= 0:
        return 0.0
    return score * get_source_weight(article.get("source", ""))


def get_news_for_symbol(symbol: str, articles: List[Dict[str, Any]],
                        threshold: float = MATCH_THRESHOLD) -> List[Dict[str, Any]]:
    """Artikel yang relevan untuk `symbol`, diurutkan berdasarkan skor.

    Hanya artikel dengan skor >= threshold yang dikembalikan (maks 3).
    Setiap artikel yang dikembalikan adalah salinan dengan kunci
    tambahan "match_score" — skor dipakai langkah dedupe (Langkah 4)
    untuk memilih token paling relevan saat satu artikel cocok ke
    banyak token.
    """
    scored = []
    for article in articles:
        score = score_article_for_symbol(symbol, article)
        if score >= threshold:
            copy = dict(article)
            copy["match_score"] = score
            scored.append(copy)
    scored.sort(key=lambda a: a["match_score"], reverse=True)
    return scored[:3]

def assign_news_to_tokens(symbols, articles: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Tetapkan tiap artikel ke SATU token paling relevan saja.

    Satu event berita hanya boleh jadi satu post: kalau sebuah artikel
    cocok ke banyak token (mis. "Bitcoin and Ethereum rally"), hanya
    token dengan skor tertinggi yang mendapatkannya. Seri dimenangkan
    token yang lebih dulu di `symbols` (urutan fetch Binance, kira-kira
    volume tertinggi dulu). Artikel di bawah threshold tidak ditugaskan
    ke siapa pun.

    Kembalikan dict symbol -> daftar artikel (maks 3 per simbol,
    diurutkan berdasarkan skor). Fungsi murni — tidak menyentuh
    penyimpanan; pencatatan pemakaian ada di storage/news_dedup.py.
    """
    assignment: Dict[str, List[Dict[str, Any]]] = {}
    for article in articles:
        best_symbol = None
        best_score = 0.0
        for symbol in symbols:
            score = score_article_for_symbol(symbol, article)
            if score >= MATCH_THRESHOLD and score > best_score:
                best_symbol = symbol
                best_score = score
        if best_symbol is None:
            continue
        copy = dict(article)
        copy["match_score"] = best_score
        assignment.setdefault(best_symbol, []).append(copy)
    for symbol in assignment:
        assignment[symbol].sort(key=lambda a: a["match_score"], reverse=True)
        assignment[symbol] = assignment[symbol][:3]
    return assignment


# ---------- Berita besar tanpa token (antrean review) ----------
#
# Berita makro/regulatori sering tidak menyebut satu token pun, tapi
# tetap penting (ETF, The Fed, SEC, hack). Kriteria "besar" di bawah
# ini sengaja sederhana dan didokumentasikan: kata kunci peristiwa
# besar (word-boundary) di judul/summary. Artikel yang lolos kriteria
# tapi tidak ditugaskan ke token mana pun masuk antrean review
# (storage/news_review.py) — TIDAK auto-post.

BIG_EVENT_KEYWORDS = [
    "etf", "sec", "fed", "federal reserve", "interest rate",
    "hack", "exploit", "lawsuit", "court ruling", "bankruptcy",
    "halving", "stablecoin", "depeg", "blackrock", "fidelity",
    "grayscale", "treasury", "reserve", "ban",
]

# Cashtag default untuk berita pasar yang luas tanpa token spesifik:
# $BTC sebagai proksi pasar. Bukan klaim bahwa beritanya "tentang BTC".
REVIEW_DEFAULT_CASHTAG = "$BTC"


def is_big_unmatched(article: Dict[str, Any]) -> bool:
    """True kalau artikel menyebut peristiwa besar (lihat daftar di atas)."""
    text = (article.get("title", "") or "") + " " + (article.get("summary", "") or "")
    return any(_word_in(text, kw) for kw in BIG_EVENT_KEYWORDS)


def suggest_review_cashtag(article: Dict[str, Any]) -> str:
    """Cashtag paling relevan untuk artikel yang tidak cocok token mana pun.

    Kalau artikelnya sendiri menulis cashtag eksplisit ($HYPE, $SOL, ...),
    pakai yang pertama disebut. Kalau tidak ada, pakai $BTC sebagai
    proksi pasar yang luas — didokumentasikan sebagai default, bukan
    sebagai hasil matching.
    """
    text = (article.get("title", "") or "") + " " + (article.get("summary", "") or "")
    found = re.findall(r"\$([A-Za-z0-9]{2,10})\b", text)
    if found:
        return "$" + found[0].upper()
    return REVIEW_DEFAULT_CASHTAG


def find_big_unmatched(articles: List[Dict[str, Any]],
                       assignment: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Artikel segar yang besar tapi tidak ditugaskan ke token mana pun.

    Dibandingkan lewat (link, judul): assign_news_to_tokens mengembalikan
    salinan artikel, jadi identitas objek tidak bisa dipakai.
    """
    assigned = {(a.get("link", ""), a.get("title", ""))
                for arts in assignment.values() for a in arts}
    return [a for a in articles
            if (a.get("link", ""), a.get("title", "")) not in assigned
            and is_big_unmatched(a)]


def get_catalyst_summary(symbol: str, articles: List[Dict[str, Any]]) -> str:
    relevant = get_news_for_symbol(symbol, articles)
    if not relevant:
        return ""
    
    summaries = []
    for article in relevant[:2]:
        title = article.get('title', '')
        source = article.get('source', '')
        # Format lebih ringkas
        summaries.append(f"• {title[:100]} ({source})")
    
    return "\n".join(summaries)
