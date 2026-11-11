# AI models used and spend

All AI work was done in **Snowflake Cortex Code**: the Desktop app for planning, building and packaging, and the CLI for an independent plan review. Usage is billed in Snowflake credits.

**Source:** `SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_COCO_USAGE_HISTORY` for user `SKODI` from 2026-11-10 00:00 UTC, last queried 2026-11-11 ~12:45 UTC. ACCOUNT_USAGE can lag by a few hours, so the last turns of the final sessions may be missing. Per-session detail for the two late sessions (`d65688c6`, `c9f778f7`): see "The last two sessions, exactly" below.

## Totals by model

| Interface | Model | Requests | Input tok | Cache-read tok | Cache-write tok | Output tok | Credits |
|---|---|---|---|---|---|---|---|
| Desktop | claude-opus-5-5 | ~730 | 1,670 | 194,366,663 | 9,873,348 | 1,146,880 | 60.87 |
| CLI | openai-gpt-5.4 | 77 | 2,753,785 | 9,719,040 | 0 | 21,576 | 5.34 |
| CLI | claude-opus-5-5 | 26 | 68 | 3,115,769 | 584,372 | 11,401 | 2.08 |
| Desktop | claude-sonnet-5-5 | 21 | 54 | 2,489,352 | 135,316 | 4,686 | 0.35 |
| CLI | gemini-3.7-flash | 34 | 55,581 | 0 | 0 | 22,891 | 0.07 |
| Desktop | gemini-3.7-flash | 12 | 4,419 | 0 | 0 | 3,722 | 0.01 |
| **Total** | | **~900** | **~2.8 M** | **~209.7 M** | **~10.6 M** | **~1.2 M** | **≈ 68.7** |

Most input is prompt-cache reads: long agent sessions resend context, which is cached.

## Rough split by phase

Planning and build session 1 are attributed by interface and start time (from the per-session sections in `ai-sessions/session_summary/*.html`). The two late sessions are attributed exactly, by their `THREAD_ID`.

| Phase | Where | Credits |
|---|---|---|
| **Planning** (research, prototypes, build plan; session `cf78df4d`) | Desktop | ~18.0 |
| **Planning:** independent plan review | CLI | ~4.7 |
| **Building:** session 1 (evaluator, test suite, optimizer skeleton; `fbd23c3f`) | Desktop, 3 subagents | ~19.2 |
| **Building:** session 2 (optimizer rules 1–8, incl. when reopened; `d65688c6`) | Desktop | 10.65 |
| **Testing:** held-out check, analysis, rules 9–11, packaging (`c9f778f7`) | Desktop | 12.99 |
| Not attributed to a session (other CLI use, title generation) | CLI + Desktop | ~3.2 |

By phase: **planning ≈ 22.7 (33%)**, **building ≈ 29.9 (43%)**, **testing ≈ 13.0 (19%)**, unattributed ≈ 3.2 (5%).

The planning figure was ~15.8 in the planning session's own record. Re-querying the same window later gives ~18.0, most likely because ACCOUNT_USAGE had not caught up when it was first measured.

## Lesson: thinking effort was set too high for planning

Each message in the raw session files records a `thinkingEffort`. Planning (`cf78df4d`) is the only session that used **xhigh**; building and testing ran at medium or low. Desktop usage for the planning session, split by when the effort changed:

| Effort window (UTC) | Requests | Output tok / request | Credits | Credits / request |
|---|---|---|---|---|
| low, 19:50–20:05 (claude-sonnet-5-5) | 21 | ~220 | 0.35 | 0.017 |
| **xhigh, 20:05–20:37** (claude-opus-5-5) | 27 | ~6,660 | **4.29** | **0.159** |
| high, 20:37–20:42 | 3 | ~4,270 | 0.46 | 0.153 |
| medium, 20:42–22:32 | 177 | ~1,280 | 12.94 | 0.073 |

At xhigh each request wrote about 5× the output tokens of a medium request and cost about 2.2× the credits. Planning work (reading the docs, hand-optimizing the examples, drafting the plan) did not need that much reasoning; medium would have done. At the medium rate those 27 requests would have cost about 2.0 credits, so **xhigh cost roughly 2.3 extra credits, about 3% of the project total**. The amount is small, but it's avoidable. Next time, thinking effort is set per task: high only for hard reasoning, such as proving a rewrite safe, and medium or low for routine work.

## The last two sessions, exactly

`d65688c6` (MiniVM Program Optimizer) and `c9f778f7` (test session) are attributed by `THREAD_ID` (from each local session file), so the numbers don't overlap. Both used claude-opus-5-5 with no subagents.

| Session | Title | What it did | Thread | First → last use (UTC) | Requests | Input tok | Cache-read tok | Cache-write tok | Output tok | Credits |
|---|---|---|---|---|---|---|---|---|---|---|
| `d65688c6-2dd5-4500-a93d-ca38d871240b` | MiniVM Program Optimizer | build session 2: optimizer rules 1–4, then (reopened) register reuse and rules 5–8 | 82264130449 | 11-11 01:38 → 12:34 | 110 | 242 | 23,232,128 | 2,416,789 | 131,540 | **10.65** |
| `c9f778f7-7883-4ba4-8fe8-befd93970962` | Golden Set Optimizer Report (test session) | held-out check, analysis, rules 9–11, packaging, folder clean-up | 82264130453 | 11-11 02:54 → 12:40 | 163 | 376 | 46,654,307 | 2,312,051 | 136,650 | **12.99** |
| **Both** | | | | | **273** | **618** | **69,886,435** | **4,728,840** | **268,190** | **23.64** |

Dollar cost depends on the account's contracted credit price, which I have not assumed here.
