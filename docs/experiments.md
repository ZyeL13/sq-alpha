# sq-alpha experiments — one variable per row

Append-only: a new experiment appends a row, never edits an old one.
The active variable is stamped into `logs/posts.csv` as
`prompt_version`, so each row is joinable to the experiment that
produced it. A threshold or parameter change is a new row, never a
silent edit.

| date | variable | value | control | note |
|---|---|---|---|---|
| 2026-11-20 | prompt_format | json-v1 (vs `<post>`-tag baseline) | cashtag-first + gate unchanged | step 1: JSON output {event, fact, interpretation, angle, post}, code-picked angle, few-shot, code validation (max 1 retry), abstain 50.0, Luna first (temp 0.5) |
