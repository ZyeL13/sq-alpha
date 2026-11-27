# sq-alpha experiments — one variable per row

Append-only: a new experiment appends a row, never edits an old one.
The active variable is stamped into `logs/posts.csv` as
`prompt_version`, so each row is joinable to the experiment that
produced it. A threshold or parameter change is a new row, never a
silent edit.

| date | variable | value | control | note |
|---|---|---|---|---|
| 2026-11-20 | prompt_format | json-v1 (vs `<post>`-tag baseline) | cashtag-first + gate unchanged | step 1: JSON output {event, fact, interpretation, angle, post}, code-picked angle, few-shot, code validation (max 1 retry), abstain 50.0, Luna first (temp 0.5) |
| 2026-11-27 | article_format | article-json-v1 (vs `<post>`-tag article baseline) | short-form JSON path + cashtag rules unchanged | article redesign: JSON article {title, stance, 7 sections, headline, deck}, research pack (snapshot + path facts + code-derived stance), §6 gates (repetition, numbers, missing-data, differentiation, truncation), PIL banner styles A–E with deterministic AUTO + variety guard, loud refusal over 6000 chars. Hypothesis: each section adds new info; no repeated disclaimer; complete conclusion. Success metric: PYR-style before/after (spec §9) — 550–750 words, all 7 sections complete, limitation sentences outside LIMITS ≤ 4, pairwise section Jaccard ≤ 0.45, every unit number matches the snapshot, stance BEARISH stated, banner style ≠ previous article's style, CSV format=longform + prompt_version=article-v1 + card_type=banner:<style>. |
| 2026-11-27 | experiment_14day | Phase 1 rotation deep-signal/pulse/contrarian/onchain, 1 primary post/day 07:30–09:30 WIB, window-gated (EXPERIMENT_POST_WINDOW) | short-form JSON path + cashtag-first + article §6 gates unchanged; §5.8 hybrid image-model NOT built | 14-day experiment (audit §F): 4 formats rotate by logged-post count (Phase 1 Days 1–7 fixed order, Phase 2 rotation continues as fallback), every post ends with one specific question (question gate + 1 retry), visuals rotate banner/card/chart with a banner-vs-card switch in finalize. Hypothesis: morning-window posts with a specific question earn replies. Success metric (audit §F.1): median score across the 14 primary posts ≥ 20 (2× baseline median 10) + ≥ 4 of 14 earn ≥ 1 reply; guardrail ≤ 2 morning posts scoring < 5. Phase 2 format is a human decision via EXPERIMENT_FORMAT (no winner/adaptive logic in code); Day-12 second post is a manual action, not code. CSV mode/hypothesis/variable_tested recorded per post. |
