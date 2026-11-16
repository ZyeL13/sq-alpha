# schedulers/orchestrator.py (lengkap dengan logging audit)
import time
import random
import threading
from dataclasses import dataclass
from datetime import datetime
from collections import deque

from collectors.binance import attach_btc_change, fetch_all_binance, fetch_new_listings
from collectors.coingecko import enrich_tokens
from collectors.coinmarketcap import enrich_tokens_cmc
from collectors.rss_news import fetch_all_news, get_catalyst_summary, assign_news_to_tokens, find_big_unmatched, suggest_review_cashtag
from llm import was_rate_limited_since
from storage.news_dedup import is_news_seen, mark_news_used, clear_old_news_entries
from storage.news_review import queue_for_review
from storage.memory_store import format_memory_block, get_memory, record_memory
from processors.normalize import normalize_token
from processors.classify import classify
from processors.score import score_token
from processors.dedupe import is_duplicate, mark_posted, clear_old_entries
from processors.draft_scoring import pick_winner, score_draft
from prompts.styles import card_type_angle, select_card_type, select_post_format
from prompts.reactions import advance_variant, draw_reaction, record_reaction_used
from generators.post_generator import extract_closing_question, generate_longform, generate_post
from schedulers.card_renderer import CardRenderError, render_card
from schedulers.snapshot import CardSnapshot, build_snapshot
from schedulers.poster import post_to_targets
from storage.format_counter import get_format_counts, increment_format_count
from config import (
    PROCESSOR_WORKERS,
    COINGECKO_ENABLED,
    WIB,
    RSS_ENABLED,
    RSS_REFRESH_INTERVAL,
    RSS_MAX_ARTICLES_PER_SOURCE,
    JIT_SCHEDULING,
    DRAFT_POOL_SIZE,
    SCHEDULE_BUFFER_MAX,
)
from schedulers.timing import get_post_delay, get_current_session
from storage.post_counter import can_post, DAILY_POST_LIMIT, get_today_posts, get_seconds_until_reset
import logging_config
from storage.persistent_queue import PersistentQueue
from storage.scheduled_post_queue import ScheduledPostQueue

logger = logging_config.get_logger("orchestrator")
data_queue = PersistentQueue()
stop_flag = threading.Event()
# Coordinates the daily-limit reset sleep: exactly one thread sleeps
# until the 07:00 WIB reset, the others wait for it (see check_and_sleep).
_reset_lock = threading.Lock()
_reset_in_progress = threading.Event()

# Setup audit logger
from logging_config import get_audit_logger
audit_logger = get_audit_logger()

# Rate limiter untuk poster
_post_times = deque(maxlen=10)

# News cache (interval & jumlah artikel diambil dari config.py —
# RSS_REFRESH_INTERVAL / RSS_MAX_ARTICLES_PER_SOURCE / RSS_ENABLED).
_news_cache = []
_last_news_refresh = 0


def has_daily_quota(queued: int) -> bool:
    """Quota-aware scheduling gate: posted today + already queued
    must stay under DAILY_POST_LIMIT, so the queue cannot overfill
    past the daily cap and burst-fire at the 07:00 WIB reset."""
    return get_today_posts() + queued < DAILY_POST_LIMIT


def can_post_now(min_interval: int = 10):
    """Check if we can post now (min_interval seconds between posts)"""
    now = time.time()
    if _post_times:
        last_post = _post_times[-1]
        if now - last_post < min_interval:
            return False, min_interval - (now - last_post)
    return True, 0


def check_and_sleep():
    """Check if the daily limit is reached; sleep until reset if so.

    Returns True if the caller should stop, False to keep working.
    When the limit is hit, exactly one thread sleeps until the 07:00 WIB
    reset; the other threads wait for that reset instead of exiting —
    the old _shutdown flag made every other thread break out of its
    loop permanently, so only the sleeping thread survived the reset.
    The sleep is interruptible: a stop request during the wait returns
    True immediately instead of being cleared away afterwards.
    """
    if can_post():
        return False

    with _reset_lock:
        owner = not _reset_in_progress.is_set()
        if owner:
            _reset_in_progress.set()

    if not owner:
        # Another thread is already sleeping until reset; wait for it.
        # Short wait timeout: clearing the event does not wake waiters,
        # so poll frequently instead of sleeping through the reset.
        while _reset_in_progress.is_set():
            if stop_flag.is_set():
                return True
            _reset_in_progress.wait(timeout=1)
        return False

    # This thread owns the reset sleep.
    seconds_until_reset = get_seconds_until_reset()
    hours = seconds_until_reset // 3600
    minutes = (seconds_until_reset % 3600) // 60

    print(f"\n  🛑 DAILY LIMIT REACHED: {get_today_posts()}/{DAILY_POST_LIMIT}")
    print(f"  📅 Reset in {hours}h {minutes}m (7 AM WIB)")
    print(f"  💤 Sleeping {hours}h {minutes}m until reset...\n")

    audit_logger.info(f"DAILY_LIMIT|{get_today_posts()}|sleep_{hours}h{minutes}m")

    stopped = stop_flag.wait(timeout=seconds_until_reset)
    if stopped:
        _reset_in_progress.clear()
        return True

    from storage.post_counter import reset_counter
    reset_counter()

    _reset_in_progress.clear()
    print("  🌅 New day! Resuming pipeline...\n")
    audit_logger.info("DAILY_RESET|resumed")
    return False


def refresh_news_cache():
    """Refresh news cache if needed (no-op when RSS_ENABLED is False)"""
    global _news_cache, _last_news_refresh
    if not RSS_ENABLED:
        return _news_cache
    now = time.time()
    if now - _last_news_refresh > RSS_REFRESH_INTERVAL:
        print("  📰 Refreshing news cache...")
        _news_cache = fetch_all_news(max_per_source=RSS_MAX_ARTICLES_PER_SOURCE)
        _last_news_refresh = now
        print(f"  📰 News cache updated: {len(_news_cache)} articles")
    return _news_cache


def collector_worker():
    """Fetch tokens from Binance + refresh news cache"""
    print("  🧠 Collector started")
    
    while not stop_flag.is_set():
        try:
            if check_and_sleep():
                break

            if JIT_SCHEDULING and \
                    ScheduledPostQueue().get_post_count() >= SCHEDULE_BUFFER_MAX:
                # Buffer full: skip the fetch + queueing cycle (the
                # tokens would sit unread in the PersistentQueue).
                # Wake every 15 min to refresh the news cache only,
                # so generation-time news stays fresh.
                refresh_news_cache()
                stop_flag.wait(timeout=_COLLECTOR_SLEEP_CAP)
                continue

            refresh_news_cache()
            binance_tokens = fetch_all_binance(limit=200)
            new_listings = fetch_new_listings()

            # BTC context for BTC-relative card rules: one attach per
            # batch, carried through the queue like the news fields.
            attach_btc_change(binance_tokens)

            # Enrich market caps (needed for ALPHA classification).
            # CoinGecko first (one cached call for the batch); CoinMarketCap
            # only fills symbols CoinGecko missed, and is a no-op without
            # CMC_API_KEY. Any failure leaves tokens unenriched — classify()
            # then simply skips ALPHA instead of misclassifying.
            try:
                if COINGECKO_ENABLED:
                    binance_tokens = enrich_tokens(binance_tokens)
                binance_tokens = enrich_tokens_cmc(binance_tokens)
            except Exception as e:
                logger.warning(f"Market-cap enrichment failed: {e}")

            # Satu event berita -> satu token paling relevan saja.
            # Artikel yang sudah pernah dipakai sebagai katalis tidak
            # ditempel lagi (feed RSS menampilkan 5 teratas berjam-jam,
            # jadi tanpa ini berita yang sama menempel tiap siklus).
            # Pre-JIT: artikel ditandai "dipakai" saat ditempel di
            # sini, bukan saat post terbit: ini menjamin satu event
            # maksimal satu post. Trade-off yang diterima: kalau
            # token yang mengklaim lalu gagal di score gate/dedupe,
            # event itu hangus dan tidak dicoba ke token lain.
            # JIT: penandaan pindah ke schedule time (spec 5.5) —
            # hanya draft pemenang yang membakar katalisnya; stub
            # artikel minimal ikut antrean supaya processor bisa
            # menandai (dan mengecek ulang) saat schedule.
            news_assignment = assign_news_to_tokens(
                [t.get("symbol", "") for t in binance_tokens], _news_cache)
            # Berita besar yang tidak cocok ke token mana pun masuk
            # antrean review untuk user — tidak auto-post (Langkah 7).
            for article in find_big_unmatched(_news_cache, news_assignment):
                if queue_for_review(article, suggest_review_cashtag(article)):
                    print(f"  👀 Review queue: {article.get('title', '')[:80]}")
            for token in binance_tokens:
                full_symbol = token.get("full_symbol", "")
                symbol = token.get("symbol", "")
                token["age_hours"] = 12 if full_symbol in new_listings else 100

                assigned = [a for a in news_assignment.get(symbol, [])
                            if not is_news_seen(a)]
                if assigned:
                    catalyst = get_catalyst_summary(symbol, assigned)
                    if catalyst:
                        token["news_catalyst"] = catalyst
                        # Snapshot harga/volume SAAT berita ditempel —
                        # dipakai di prompt untuk membandingkan dengan
                        # harga/volume saat post di-generate (Langkah 6).
                        token["price_at_news"] = token.get("price", 0)
                        token["volume_at_news"] = token.get("volume_24h", 0)
                        if JIT_SCHEDULING:
                            token["news_article_keys"] = [
                                {"link": a.get("link", ""),
                                 "title": a.get("title", ""),
                                 "source": a.get("source", "")}
                                for a in assigned[:2]
                            ]
                        else:
                            for article in assigned[:2]:
                                mark_news_used(article, symbol)

            queued = 0
            for token in binance_tokens:
                if not check_and_sleep():
                    data_queue.put("binance", token)
                    queued += 1

            logger.info(f"Fetched {len(binance_tokens)} Binance tokens, queued {queued}")
            print(f"  📰 News cache age: {int(time.time() - _last_news_refresh)}s, {len(_news_cache)} articles")

            clear_old_entries()
            clear_old_news_entries()
            time.sleep(60)

        except Exception as e:
            logger.error(f"Collector error: {e}")
            time.sleep(30)


@dataclass
class Draft:
    """One generated post, pre-render.

    prepare_draft produces it (format decision + one generation, no
    rendering); finalize_draft renders the winner's card/cover. The
    pool scores Drafts and finalizes only the winner, so losing
    drafts never cost a render. `reaction` is the reaction NAME
    (the instruction text lives in prompts.reactions.REACTIONS);
    None for long-form articles and for the pre-JIT path.
    `total_score` is the score gate's weighted total, carried for
    the pool's signal component (the per-signal `scores` dict does
    not contain it).
    """

    content: str
    fmt: str
    title: "str | None"
    token: dict
    category: str
    scores: dict
    total_score: float = 0.0
    snapshot: "CardSnapshot | None" = None
    card_type: "str | None" = None
    reaction: "str | None" = None


def prepare_draft(token, category, scores, reaction=None, memory=None,
                  total_score=0.0):
    """Decide the format, generate once. No rendering.

    The format is decided BEFORE generation (spec section 7: no
    extra LLM passes — exactly one generation call per draft).
    Returns a Draft, or None when nothing could be generated.
    Degradation, never drops:
    - image + missing snapshot (klines failed) -> short text draft,
      and no image slot is consumed.
    - image + no matching card type -> short text draft, and no
      image slot is consumed.
    - longform + generation failure -> ONE fallback generate_post
      call, audit-logged; the only path with a second LLM call.
    Render-failure fallbacks live in finalize_draft, which runs
    only for the scheduled winner.

    `reaction` is a tentative (name, instruction) draw from the
    pool; it replaces the opening angle (and the card-type angle
    mapping) for this draft. `memory` is a pre-formatted MEMORY
    block for the prompt, or None. Both default to the pre-JIT
    behavior: angle deck / card-type mapping, no memory block.
    """
    fmt = select_post_format(token, category, scores, get_format_counts())
    symbol = token.get("symbol", "?")
    snapshot = None

    card_type = None
    if fmt == "image":
        # ONE snapshot for this post: the prompt and the card both
        # read from it, so their numbers can never disagree. No
        # snapshot means no card data — text-only, slot not consumed.
        snapshot = build_snapshot(token)
        if snapshot is None:
            print(f"  ⚠️ No klines for ${symbol}, falling back to short text")
            audit_logger.info(f"IMAGE_FALLBACK|{symbol}|klines_failed")
            fmt = "short"
        else:
            # The card type is decided BEFORE generation and drives
            # the text (mapped opening angle + closing question on
            # the pre-JIT path; the reaction on the JIT path).
            # No matching type: an ordinary post, slot not consumed.
            card_type = select_card_type(
                change=token.get("price_change_percent", 0) or 0,
                volume_ratio=snapshot.volume_ratio,
                range_width_pct=snapshot.range_width_pct,
                range_position=snapshot.range_position,
                btc_relative=snapshot.btc_relative)
            if card_type is None:
                print(f"  ⚠️ No card type for ${symbol}, falling back to short text")
                audit_logger.info(f"IMAGE_FALLBACK|{symbol}|no_card_type")
                fmt = "short"

    reaction_name = reaction[0] if reaction else None

    if fmt == "longform":
        result = generate_longform(token, category, scores)
        if result is None:
            print(f"  ⚠️ Long-form failed for ${symbol}, falling back to short text")
            audit_logger.info(f"LONGFORM_FALLBACK|{symbol}|{category}|generate_failed")
            fmt = "short"
            content = generate_post(token, category, scores,
                                    reaction=reaction, memory=memory)
            if content is None:
                return None
            return Draft(content=content, fmt=fmt, title=None, token=token,
                         category=category, scores=scores,
                         total_score=total_score, reaction=reaction_name)
        title, content = result
        # Long-form articles carry no opener reaction; the tentative
        # draw (if any) is discarded with the draft's reaction slot.
        return Draft(content=content, fmt=fmt, title=title, token=token,
                     category=category, scores=scores,
                     total_score=total_score)

    # Image posts generate from the snapshot-enriched token copy so
    # the prompt carries the same derived numbers the card shows,
    # with the card type's mapped opening angle and a closing
    # question the card repeats — or the pool's reaction on the JIT
    # path. Exactly one LLM call, as always.
    gen_token = token
    opening_angle = None
    closing_question = False
    if fmt == "image" and snapshot is not None:
        gen_token = dict(token)
        gen_token["volume_7d_avg"] = snapshot.volume_7d_avg
        gen_token["volume_ratio_7d"] = snapshot.volume_ratio
        gen_token["btc_change_24h"] = snapshot.btc_change
        if reaction is None:
            opening_angle = card_type_angle(card_type)
        closing_question = True

    content = generate_post(gen_token, category, scores,
                            opening_angle=opening_angle,
                            closing_question=closing_question,
                            reaction=reaction, memory=memory)
    if content is None:
        return None
    return Draft(content=content, fmt=fmt, title=None, token=token,
                 category=category, scores=scores, total_score=total_score,
                 snapshot=snapshot, card_type=card_type,
                 reaction=reaction_name)


def finalize_draft(draft):
    """Render the winner's card/cover. Returns the
    (content, format, title, image_paths) tuple prepare_post has
    always returned. Render-failure fallbacks (unchanged):
    - image + render failure -> scheduled as short text, and no
      image slot is consumed.
    - longform + render failure -> scheduled as an article without
      a cover (the poster publishes coverless articles by design).
      Scheduling a 600-900-word article as "short" would truncate
      it to 900 chars, so the format is kept.
    """
    content, fmt, title = draft.content, draft.fmt, draft.title
    symbol = draft.token.get("symbol", "?")
    image_paths = None
    if fmt == "image":
        try:
            image_paths = [render_card(
                draft.token, snapshot=draft.snapshot,
                card_type=draft.card_type,
                question=extract_closing_question(content),
                reaction=draft.reaction)]
        except CardRenderError as e:
            print(f"  ⚠️ Card render failed for ${symbol} ({e}), falling back to short text")
            audit_logger.info(f"IMAGE_FALLBACK|{symbol}|render_failed")
            fmt = "short"
            image_paths = None
    elif fmt == "longform":
        try:
            # Long-form covers keep the plain style: no snapshot is
            # built on this path, and the cover contract is unchanged.
            image_paths = [render_card(draft.token, style="plain")]
        except CardRenderError as e:
            print(f"  ⚠️ Cover render failed for ${symbol} ({e}), publishing without cover")
            audit_logger.info(f"IMAGE_FALLBACK|{symbol}|cover_render_failed")
            image_paths = None
    return content, fmt, title, image_paths


def prepare_post(token, category, scores, reaction=None, memory=None,
                 total_score=0.0):
    """Thin wrapper: draft + finalize. Existing call sites keep
    working unchanged; the pool path calls the two phases
    separately so only the winner is rendered."""
    draft = prepare_draft(token, category, scores, reaction=reaction,
                          memory=memory, total_score=total_score)
    if draft is None:
        return None
    return finalize_draft(draft)


# ---------------- JIT pool ----------------
# One pool round at a time, even if PROCESSOR_WORKERS ever grows
# past 1: rounds share the reaction deck, the variant cursors, and
# the scheduled queue.
_pool_lock = threading.Lock()

# Buffer-full sleep caps (spec 4.2): the processor wakes when the
# next post fires (+30s) or after 30 min; the collector wakes every
# 15 min to refresh the news cache only. An empty pool round backs
# off 60s so a dry queue or a throttled provider doesn't hot-loop.
_PROCESSOR_SLEEP_CAP = 1800
_COLLECTOR_SLEEP_CAP = 900
_POOL_EMPTY_BACKOFF = 60


def _chain_time(last_time, current_time, delay):
    """Chain a new post after the last scheduled one; fall back to
    now + delay when the queue is empty (last_time None) or the last
    post is already due. None-safe by construction."""
    if last_time and last_time > current_time:
        return last_time + delay
    return current_time + delay


def _sleep_until_next_post(scheduled_queue, cap_seconds):
    """Sleep until the earliest scheduled post fires (+30s), capped.
    Interruptible via stop_flag. A 1s sleep when the queue is empty
    (defensive: callers checked the buffer is full first)."""
    next_time = scheduled_queue.get_next_post_time()
    if next_time is None:
        wait = 1.0
    else:
        wait = max(1.0, next_time - time.time() + 30)
    wait = min(wait, cap_seconds)
    print(f"  💤 Buffer full, sleeping {wait:.0f}s until the next slot...")
    stop_flag.wait(timeout=wait)


def _strip_stale_catalyst(token):
    """Drop a catalyst whose article another post already used (the
    article was attached before that post scheduled). The token
    competes on signal alone; nothing is marked."""
    for key in ("news_catalyst", "price_at_news", "volume_at_news",
                "news_article_keys"):
        token.pop(key, None)


def _collect_candidates(worker_id, pool_size):
    """Pull + classify + gate tokens until pool_size candidates or
    the queue is exhausted this cycle (a get() timeout ends the
    collection). Consumed items are gone whether or not they pass
    the gates — same as the pre-JIT processor. Returns a list of
    (token, category, scored, hook)."""
    from prompts.styles import get_hook

    candidates = []
    while len(candidates) < pool_size:
        item = data_queue.get(timeout=5)
        if item is None:
            break
        source, raw = item
        token = normalize_token(raw, source=source)
        cat = classify(token)
        if not cat:
            continue
        scored = score_token(token, cat)
        if not scored["passes"]:
            print(f"  🚫 P{worker_id}: {token['symbol']} → {cat} "
                  f"(score too low: total={scored['total']:.2f}, "
                  f"primary={scored['primary']:.2f})")
            audit_logger.info(
                f"SCORE_REJECTED|{token['symbol']}|{cat}|"
                f"total={scored['total']:.2f}|primary={scored['primary']:.2f}")
            continue
        hook = get_hook(cat) or "default"
        market_cap = token.get("market_cap", 0)
        if is_duplicate(token["symbol"], cat, market_cap, hook):
            continue
        # normalize_token drops these fields, so carry them from the
        # raw queue item like the pre-JIT processor does.
        for key in ("news_catalyst", "price_at_news", "volume_at_news",
                    "btc_change_24h", "news_article_keys"):
            if key in raw:
                token[key] = raw[key]
        # Catalyst re-check: the article may have been used by a
        # post scheduled after this token was queued (schedule-time
        # marking, spec 5.5). A stale catalyst is stripped, never
        # re-marked.
        stubs = token.get("news_article_keys") or []
        if stubs and any(is_news_seen(s) for s in stubs
                         if isinstance(s, dict)):
            _strip_stale_catalyst(token)
        candidates.append((token, cat, scored, hook))
    return candidates


def _schedule_winner(worker_id, draft, hook, scheduled_queue):
    """Finalize + schedule the pool winner: render, chain the time,
    record every commitment (format cap, dedupe, memory, reaction,
    variant, news). Mirrors the pre-JIT schedule step so queue rows
    stay identical. Returns True."""
    content, fmt, title, image_paths = finalize_draft(draft)
    token = draft.token
    symbol = token["symbol"]
    current_time = time.time()
    delay = get_post_delay()
    scheduled_time = _chain_time(scheduled_queue.get_last_post_time(),
                                 current_time, delay)
    session = get_current_session()
    scheduled_queue.add_post(
        post=content,
        category=draft.category,
        symbol=symbol,
        scheduled_time=scheduled_time,
        hook=hook,
        session=session,
        provider="blockrun",
        format=fmt,
        title=title,
        image_paths=image_paths,
    )
    # Scheduling is the commitment point for the per-format daily
    # caps, the dedupe record, the post memory, the reaction deck,
    # the variant rotation, and the news catalyst: losers record
    # none of these.
    if fmt in ("image", "longform"):
        increment_format_count(fmt)
    mark_posted(symbol, draft.category, hook, token.get("market_cap", 0))
    record_memory(symbol, token.get("price_change_percent", 0), content)
    if draft.reaction:
        record_reaction_used(draft.reaction)
        advance_variant(draft.reaction)
    for stub in token.get("news_article_keys") or []:
        if isinstance(stub, dict):
            mark_news_used(stub, symbol)
    wait_min = (scheduled_time - current_time) / 60
    print(f"  ✍️ P{worker_id}: {symbol} → {draft.category} [{fmt}] "
          f"scheduled in {wait_min:.1f} min")
    audit_logger.info(
        f"SCHEDULED|{symbol}|{draft.category}|{hook}|{session}|"
        f"{int(scheduled_time)}|{fmt}")
    logger.info(f"POST_SCHEDULED: {symbol} -> {draft.category} [{fmt}] "
                f"scheduled in {wait_min:.1f} min")
    return True


def run_pool_round(worker_id, scheduled_queue=None):
    """One JIT pool round: collect -> draft -> score -> schedule the
    winner. Returns True when a post was scheduled. Serialized by
    _pool_lock: at most one round runs at a time.

    Rate-limit early-exit: when a draft call hits a 429, the loop
    stops immediately and the winner is picked from the drafts
    already completed; with zero drafts the round ends empty
    (POOL_EMPTY|rate_limited). DRAFT_POOL_SIZE=1 skips scoring and
    finalizes the single draft directly.
    """
    with _pool_lock:
        queue = scheduled_queue or ScheduledPostQueue()
        if not can_post():
            return False
        if queue.get_post_count() >= SCHEDULE_BUFFER_MAX:
            return False
        pool_size = DRAFT_POOL_SIZE
        candidates = _collect_candidates(worker_id, pool_size)
        if not candidates:
            print(f"  📭 P{worker_id}: pool round, no candidates")
            audit_logger.info("POOL_EMPTY|no_candidates")
            return False
        drafts = []
        rate_limited = False
        for token, cat, scored, hook in candidates:
            memory_rec = get_memory(token["symbol"])
            reaction = draw_reaction(token, memory_rec)
            memory_block = format_memory_block(
                memory_rec, token["symbol"],
                token.get("price_change_percent", 0))
            t0 = time.time()
            draft = prepare_draft(token, cat, scored["scores"],
                                  reaction=reaction,
                                  memory=memory_block or None,
                                  total_score=scored["total"])
            if draft is None:
                if was_rate_limited_since(t0):
                    rate_limited = True
                    print(f"  ⚠️ P{worker_id}: rate limit hit, "
                          "stopping the round early")
                    audit_logger.info("POOL_429|early_exit|"
                                      f"{len(drafts)}_drafts_done")
                    break
                continue
            drafts.append((draft, hook))
        if not drafts:
            reason = "rate_limited" if rate_limited else "all_drafts_failed"
            print(f"  📭 P{worker_id}: pool round empty ({reason})")
            audit_logger.info(f"POOL_EMPTY|{reason}")
            return False
        if pool_size == 1:
            # Single-draft pool: skip scoring, finalize directly.
            winner, winner_hook = drafts[0]
        else:
            recent = queue.get_recent_scheduled_posts(5)
            scored_drafts = []
            for draft, hook in drafts:
                result = score_draft(draft.content, draft.token,
                                     draft.total_score, recent,
                                     draft.snapshot)
                if result is None:
                    audit_logger.info(
                        f"DRAFT_REJECTED|{draft.token['symbol']}|"
                        f"{draft.reaction or '-'}|validate_failed")
                    continue
                audit_logger.info(
                    f"DRAFT_SCORED|{draft.token['symbol']}|"
                    f"{draft.reaction or '-'}|{result.total:.1f}|"
                    f"{result.components_str()}")
                scored_drafts.append((draft, hook, result))
            if not scored_drafts:
                print(f"  📭 P{worker_id}: pool round empty (all_rejected)")
                audit_logger.info("POOL_EMPTY|all_rejected")
                return False
            winner, winner_hook, _ = scored_drafts[pick_winner(
                [s for _, _, s in scored_drafts])]
        print(f"  🏆 P{worker_id}: pool winner ${winner.token['symbol']} "
              f"({len(drafts)}/{len(candidates)} drafts)")
        return _schedule_winner(worker_id, winner, winner_hook, queue)


def processor_worker_jit(worker_id: int):
    """JIT processor: pool rounds while a buffer slot is open, sleep
    while the buffer is full. The daily-limit sleep is the shared
    check_and_sleep (until the 07:00 WIB reset)."""
    print(f"  🧠 Processor {worker_id} started (JIT pool)")
    scheduled_queue = ScheduledPostQueue()
    while not stop_flag.is_set():
        try:
            if check_and_sleep():
                break
            if scheduled_queue.get_post_count() >= SCHEDULE_BUFFER_MAX:
                _sleep_until_next_post(scheduled_queue, _PROCESSOR_SLEEP_CAP)
                continue
            if not run_pool_round(worker_id, scheduled_queue):
                # Empty round (no candidates, all drafts failed, or
                # rate-limited): back off so a dry queue or a
                # throttled provider doesn't hot-loop.
                stop_flag.wait(timeout=_POOL_EMPTY_BACKOFF)
                continue
            time.sleep(random.uniform(2, 5))
        except Exception as e:
            print(f"  ❌ P{worker_id} error: {e}")
            time.sleep(1)


def _processor_target():
    """The processor entry point for this run: JIT pool rounds, or
    the pre-JIT per-token worker when the kill switch is off."""
    return processor_worker_jit if JIT_SCHEDULING else processor_worker


def processor_worker(worker_id: int):
    """Process tokens: normalize → classify → format-select → generate → schedule post"""
    print(f"  🧠 Processor {worker_id} started")
    
    from prompts.styles import get_hook
    
    while not stop_flag.is_set():
        try:
            if check_and_sleep():
                break
            
            item = data_queue.get(timeout=5)
            if item is None:
                time.sleep(1)
                continue
            
            source, raw = item
            token = normalize_token(raw, source=source)
            cat = classify(token)
            
            if cat and has_daily_quota(ScheduledPostQueue().get_post_count()):
                try:
                    # Score gate: skip tokens whose signal is too weak to
                    # be worth a post (see processors/score.py).
                    scored = score_token(token, cat)
                    if not scored["passes"]:
                        print(f"  🚫 P{worker_id}: {token['symbol']} → {cat} "
                              f"(score too low: total={scored['total']:.2f}, "
                              f"primary={scored['primary']:.2f})")
                        audit_logger.info(
                            f"SCORE_REJECTED|{token['symbol']}|{cat}|"
                            f"total={scored['total']:.2f}|primary={scored['primary']:.2f}")
                        continue

                    hook = get_hook(cat) or "default"
                    market_cap = token.get("market_cap", 0)

                    if is_duplicate(token["symbol"], cat, market_cap, hook):
                        continue

                    if "news_catalyst" in raw:
                        token["news_catalyst"] = raw["news_catalyst"]

                    if "price_at_news" in raw:
                        token["price_at_news"] = raw["price_at_news"]
                    if "volume_at_news" in raw:
                        token["volume_at_news"] = raw["volume_at_news"]

                    # normalize_token drops this field, so carry it
                    # from the raw queue item like the news snapshot.
                    if "btc_change_24h" in raw:
                        token["btc_change_24h"] = raw["btc_change_24h"]

                    prepared = prepare_post(token, cat, scored["scores"])
                    if prepared:
                        post, fmt, title, image_paths = prepared
                        current_time = time.time()
                        scheduled_queue = ScheduledPostQueue()

                        last_time = scheduled_queue.get_last_post_time()

                        delay = get_post_delay()
                        if last_time and last_time > current_time:
                            scheduled_time = last_time + delay
                            print(f"  📅 Last post at {last_time:.0f}, scheduling +{delay}s")
                        else:
                            scheduled_time = current_time + delay
                            print(f"  📅 Queue empty, scheduling in {delay}s")

                        session = get_current_session()

                        scheduled_queue.add_post(
                            post=post,
                            category=cat,
                            symbol=token["symbol"],
                            scheduled_time=scheduled_time,
                            hook=hook,
                            session=session,
                            provider="blockrun",
                            format=fmt,
                            title=title,
                            image_paths=image_paths,
                        )

                        # Scheduling is the commitment point for the
                        # per-format daily caps (see storage/format_counter).
                        if fmt in ("image", "longform"):
                            increment_format_count(fmt)

                        mark_posted(token["symbol"], cat, hook, market_cap)

                        wait_min = (scheduled_time - current_time) / 60
                        print(f"  ✍️ P{worker_id}: {token['symbol']} → {cat} [{fmt}] scheduled in {wait_min:.1f} min")

                        # AUDIT LOG: Post dijadwalkan
                        audit_logger.info(f"SCHEDULED|{token['symbol']}|{cat}|{hook}|{session}|{int(scheduled_time)}|{fmt}")
                        logger.info(f"POST_SCHEDULED: {token['symbol']} -> {cat} [{fmt}] scheduled in {wait_min:.1f} min")
                        time.sleep(random.uniform(2, 5))
                    else:
                        print(f"  ⚠️ P{worker_id}: {token['symbol']} → {cat} (no post)")
                        # AUDIT LOG: Gagal generate
                        audit_logger.info(f"NO_POST|{token['symbol']}|{cat}|generate_failed")
                        
                except Exception as inner_e:
                    print(f"  ⚠️ P{worker_id}: Error processing {token.get('symbol', '?')}: {inner_e}")
                    audit_logger.info(f"ERROR|{token.get('symbol', '?')}|{cat}|{str(inner_e)[:50]}")
                    continue
            elif cat:
                # Daily quota full (posted + queued): skip before the
                # LLM call so the queue cannot overfill past the cap.
                print(f"  🚫 P{worker_id}: {token['symbol']} → {cat} (daily quota full, skipping)")
                audit_logger.info(f"QUOTA_FULL|{token['symbol']}|{cat}")
            
            time.sleep(random.uniform(0.5, 1))
            
        except Exception as e:
            print(f"  ❌ P{worker_id} error: {e}")
            time.sleep(1)


def poster_worker():
    """Post scheduled posts when they are due"""
    print("  📤 Poster started (waiting for scheduled posts...)")
    
    scheduled_queue = ScheduledPostQueue()
    
    while not stop_flag.is_set():
        try:
            if check_and_sleep():
                break
            
            # Rate limit check
            can_post_now_flag, wait_time = can_post_now(10)
            if not can_post_now_flag:
                print(f"  ⏳ Rate limit: waiting {wait_time:.0f}s...")
                time.sleep(wait_time)
                continue
            
            # Drop stale due posts (>90 min past scheduled time) at
            # post time, so a backlog built up while the poster was
            # sleeping at the daily limit cannot burst-fire at reset.
            stale = scheduled_queue.delete_old_posts(5400)
            if stale:
                print(f"  🗑️ Dropped {stale} stale scheduled post(s) (>90 min overdue)")
                audit_logger.info(f"STALE_DROPPED|{stale}|90min")

            # Do not claim a row we cannot post: the claim deletes
            # the row, so re-check the daily limit first (the
            # top-of-loop check may have passed before another
            # process consumed the remaining quota).
            if not can_post():
                if check_and_sleep():
                    break
                continue

            # Atomic cross-process claim: the row is deleted inside
            # the claim transaction, so a second pipeline process
            # sharing this queue.db can never post the same row.
            claimed = scheduled_queue.claim_due_post()
            due_posts = [claimed] if claimed is not None else []
            
            if not due_posts:
                next_time = scheduled_queue.get_next_post_time()
                if next_time:
                    wait_time = max(1, next_time - time.time())
                    print(f"  ⏳ Next scheduled post in {wait_time:.0f}s")
                    time.sleep(min(wait_time, 30))
                else:
                    time.sleep(10)
                continue
            
            for post_id, post, cat, sym, hook, session, provider, fmt, title, image_paths in due_posts:
                if not can_post():
                    check_and_sleep()
                    break

                print(f"  📝 Posting {sym} as {cat} [{fmt}]...")
                success = post_to_targets(
                    content=post,
                    category=cat,
                    symbol=sym,
                    hook=hook,
                    session=session,
                    llm_provider=provider,
                    format=fmt or "short",
                    title=title,
                    image_paths=image_paths,
                )
                
                if success:
                    mark_posted(sym, cat)
                    print(f"  ✅ {sym} posted")
                    _post_times.append(time.time())
                    # AUDIT LOG: Post berhasil
                    audit_logger.info(f"POSTED|{sym}|{cat}|{hook}|{session}|{provider}")
                    logger.info(f"POST_SUCCESS: {sym} -> {cat} posted successfully")
                else:
                    print(f"  ❌ {sym} failed to post")
                    # AUDIT LOG: Post gagal
                    audit_logger.info(f"FAILED|{sym}|{cat}|post_to_targets_failed")
                
                # No remove_post(): claim_due_post() already deleted
                # the row atomically when it was claimed.
                check_and_sleep()
            
            time.sleep(2)
            
        except Exception as e:
            print(f"  ❌ Poster error: {e}")
            time.sleep(5)


def run_orchestrator():
    """Start the full pipeline"""
    global _last_news_refresh, _news_cache
    
    print(f"\n{'='*50}")
    print("🚀 Starting Pipeline Orchestrator")
    print(f"📅 {datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')} WIB")
    print(f"📊 Daily limit: {DAILY_POST_LIMIT} posts/day")
    print(f"🧠 JIT scheduling: {'ON' if JIT_SCHEDULING else 'OFF'} "
          f"(pool {DRAFT_POOL_SIZE}, buffer {SCHEDULE_BUFFER_MAX})")
    print(f"📰 News refresh interval: {RSS_REFRESH_INTERVAL}s")
    print(f"{'='*50}\n")
    
    audit_logger.info(f"PIPELINE_START|{datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Auto-clean queues
    print("  🧹 Auto-cleaning queues...")
    scheduled_queue = ScheduledPostQueue()
    deleted_posts = scheduled_queue.delete_old_posts(3600)  # 1 hour
    print(f"  🧹 Cleaned {deleted_posts} expired posts")
    
    deleted_tokens = data_queue.delete_old_entries(24)  # 24 hours
    print(f"  🧹 Cleaned {deleted_tokens} old token entries")
    
    # Initialize news cache
    _last_news_refresh = 0
    _news_cache = []
    refresh_news_cache()
    
    # Start workers
    threading.Thread(target=collector_worker, daemon=True).start()

    processor_target = _processor_target()
    for i in range(PROCESSOR_WORKERS):
        threading.Thread(target=processor_target, args=(i+1,), daemon=True).start()
    
    threading.Thread(target=poster_worker, daemon=True).start()
    
    print("✅ All workers started. Press Ctrl+C to stop.\n")
    
    try:
        while not stop_flag.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping orchestrator...")
        audit_logger.info("PIPELINE_STOP|keyboard_interrupt")
        stop_flag.set()
        time.sleep(2)
        print("👋 Bye!")
