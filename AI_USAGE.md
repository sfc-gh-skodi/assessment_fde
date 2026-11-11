# AI models used and spend

All AI work was done in **Snowflake Cortex Code**: the Desktop app for planning, building and packaging, and the CLI for an independent plan review. Usage is billed in Snowflake credits.

**Source:** `SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_COCO_USAGE_HISTORY` for user `SKODI` from 2026-11-10 00:00 UTC, queried 2026-11-11. ACCOUNT_USAGE can lag by a few hours, so the last turns of the final session may be missing.

## Totals by model

| Interface | Model | Requests | Input tok | Cache-read tok | Cache-write tok | Output tok | Credits |
|---|---|---|---|---|---|---|---|
| Desktop | claude-opus-5-5 | 533 | 1,234 | 135,380,413 | 6,814,955 | 943,630 | 44.02 |
| CLI | openai-gpt-5.4 | 77 | 2,753,785 | 9,719,040 | 0 | 21,576 | 5.34 |
| CLI | claude-opus-5-5 | 26 | 68 | 3,115,769 | 584,372 | 11,401 | 2.08 |
| Desktop | claude-sonnet-5-5 | 21 | 54 | 2,489,352 | 135,316 | 4,686 | 0.35 |
| CLI | gemini-3.7-flash | 34 | 55,581 | 0 | 0 | 22,891 | 0.07 |
| Desktop | gemini-3.7-flash | 12 | 4,419 | 0 | 0 | 3,722 | 0.01 |
| **Total** | | **703** | **~2.8 M** | **~150.7 M** | **~7.5 M** | **~1.0 M** | **≈ 51.9** |

Most input is prompt-cache reads: long agent sessions resend context, which is cached.

## Rough split by phase

Figures come from the per-session sections in `ai-sessions/*.html`, attributed by interface and session start time, so they are approximate.

| Phase | Where | Credits |
|---|---|---|
| Planning (research, prototypes, build plan) | Desktop | ~15.8 |
| Independent plan review | CLI | ~4.7 |
| Build session 1 (evaluator, test suite, optimizer skeleton) | Desktop, 3 subagents | ~19.2 |
| Build session 2 (optimizer rules 1–4) | Desktop | ~2.4 |
| Held-out analysis and packaging (this session) | Desktop | remainder ≈ 9.8 (also includes ~2.8 CLI credits not attributed to the review session) |

Dollar cost depends on the account's contracted credit price, which I have not assumed here.
