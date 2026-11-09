# SQ-Alpha Editorial v2

Decided with zyel, 2026-11-09. Status: implemented on branch
`refactor/fase-3-smoke-test` (commits 8893a04, a357082, a6bbe93).
Live voice check still pending — run `python scripts/demo_editorial_v2.py`
on the VPS (this VM has no LLM keys).

## Identity

SQ-Alpha | The Skeptical Market Observer. An independent crypto market
observer: skeptical of hype, evidence over narrative, willing to call
the market boring, restrained, analytical, occasionally witty. Not an
AI financial journalist. Quality and credibility over posting quota.

## Decisions

1. **Quality over quota.** Target 10 posts/day, not an obligation.
   Skip when data is insufficient or there is no meaningful insight.
   Never recycle a token's analysis to fill a slot. Skip reasons are
   audit-logged (`SKIPPED|symbol|category|reason`).
2. **Conditional style selection, never a draw.** Randomisation is
   only for delivery variation, never for choosing an opinion.

   | Style | Condition |
   | --- | --- |
   | Analytical | Default |
   | Contrarian | Evidence contradicting consensus (tape since the catalyst moves >= 3% against a >= 3% 24h move) |
   | Dry Humor | A market phenomenon worth satirizing (>= 15% move with no catalyst, or >= 10% move that ended mid-range) |
   | Data Observation | An anomaly or significant change (anomaly score >= 0.7, or volume +50% since the news) |

   Priority: data_observation > contrarian > dry_humor > analytical.
3. **Voice calibration.** Positive few-shot examples (4, incl. a longer
   numbers-led Data Observation so the model learns voice, not one
   sentence shape) + 4 negative examples with WHY (forced
   contrarianism, fake intellectualism, forced sarcasm, manufactured
   conviction) + calibration rules. Key rules: skepticism does not
   require disagreement; if evidence supports the consensus,
   acknowledge it; never imply superior intelligence over the audience.
4. **Guardrails (unchanged).** $cashtag exactly once per post, first
   line. No trade instructions, no financial-advice framing. No
   invented metrics, levels, catalysts, or sentiment.

## Non-goals

No new agent, API call, LLM pass, or publishing-pipeline change.
The orchestrator, poster, scheduler, and daily-limit logic are
untouched. `get_hook()` is still used by the orchestrator for the
dedupe key; only the prompt stopped forcing hook/angle/closer verbatim.

## Where it lives

- `prompts/rebate.py` — REBATE_SYSTEM: identity, principles, forbidden habits.
- `prompts/styles.py` — VOICE_CALIBRATION, STYLE_GUIDANCE,
  EDITORIAL_FORBIDDEN, select_editorial_style(), insufficient_insight().
- `generators/post_generator.py` — build_prompt() (style + calibration,
  no verbatim parts), generate_post() (pre-LLM skip).
- `generators/quality_gate.py` — validate_post() rejects editorial
  violations (rules-based); proofread no longer appends "tracking the move."
- `tests/test_editorial_v2.py` — gates, skip, prompt wiring, gate checks.
- `scripts/demo_editorial_v2.py` — dry-run: 4 synthetic tokens + 1 skip
  case. Never posts, never touches history/queue/counter.

## Week-one KPIs (from 2026-11-09)

| Metric | Target |
| --- | --- |
| Posts with valid data | 100% |
| Duplicate posts | 0 |
| Editorial violations | 0 |
| Posts passing quality check | >= 90% |
| Median views | +30% vs baseline |
| Engagement rate | Measured, no target yet |

30% is an experiment target, not a guarantee about Binance's algorithm.

## Baseline and measurement rule

Baseline (8 Square posts screenshotted by zyel, 2026-11-09): views
2, 9, 30, 44, 55, 65, 69, 72. Median = 49.5, call it ~50. Target
median after week one: >= 65.

**Compare posts at the same age — 24h after publication.** Never
compare a 2-hour-old post with a 24-hour-old post.

How to measure: Creator Center views per post at 24h; audit log
(`logs/post_audit.log`) for SKIPPED reasons, REJECTED editorial
violations, and GENERATED vs REJECTED counts for the quality-check
pass rate. Review date: 2026-11-16. No new features before the first
experiment finishes.
