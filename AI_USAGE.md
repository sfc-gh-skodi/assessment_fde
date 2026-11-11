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
| **Planning** (research, prototypes, build plan; session `cf78df4d`) | Desktop | ~18.0 |
| **Planning:** independent plan review | CLI | ~4.7 |
| **Building:** session 1 (evaluator, test suite, optimizer skeleton; `fbd23c3f`) | Desktop, 3 subagents | ~19.2 |
| **Building:** session 2 (optimizer rules 1–4; `d65688c6`) | Desktop | ~2.4 |
| **Testing:** held-out check, analysis, packaging (`c9f778f7`) | Desktop | ~2.9 so far |
| Not attributed to a session (other CLI use, `d65688c6` reopened later) | CLI + Desktop | ~4.7 |

By phase: **planning ≈ 22.7 (44%)**, **building ≈ 21.6 (42%)**, **testing ≈ 2.9 (6%)**, unattributed ≈ 4.7 (9%).

The planning figure was ~15.8 in the planning session's own record. Re-querying the same window later gives ~18.0, most likely because ACCOUNT_USAGE had not caught up when it was first measured.

## Lesson: thinking effort was set too high for planning

Each message in the raw session files records a `thinkingEffort`. Planning (`cf78df4d`) is the only session that used **xhigh**; building and testing ran at medium or low. Desktop usage for the planning session, split by when the effort changed:

| Effort window (UTC) | Requests | Output tok / request | Credits | Credits / request |
|---|---|---|---|---|
| low, 19:50–20:05 (claude-sonnet-5-5) | 21 | ~220 | 0.35 | 0.017 |
| **xhigh, 20:05–20:37** (claude-opus-5-5) | 27 | ~6,660 | **4.29** | **0.159** |
| high, 20:37–20:42 | 3 | ~4,270 | 0.46 | 0.153 |
| medium, 20:42–22:32 | 177 | ~1,280 | 12.94 | 0.073 |

At xhigh each request wrote about 5× the output tokens of a medium request and cost about 2.2× the credits. Planning work (reading the docs, hand-optimizing the examples, drafting the plan) did not need that much reasoning; medium would have done. At the medium rate those 27 requests would have cost about 2.0 credits, so **xhigh cost roughly 2.3 extra credits, about 4% of the project total**. The amount is small, but it's avoidable. Next time, thinking effort is set per task: high only for hard reasoning, such as proving a rewrite safe, and medium or low for routine work.

Dollar cost depends on the account's contracted credit price, which I have not assumed here.
