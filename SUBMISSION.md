# Submission: start here

## 1. Everything behind the optimizer and evaluator

| What | Where |
|---|---|
| Optimizer code | `optimizer/` (main, ir, analyze, passes, cost); entry point `./optimize`, also wired into `minivm-takehome/optimize` |
| Evaluator code | `evaluator/` (main, vm, datagen, progen, compare); entry point `./evaluate`, also wired into `minivm-takehome/evaluate` |
| Scripts and tools | `tools/` (bench, loop runner, meta-eval and fakes, test-data and stress generators, session exporter, hooks) |
| Tests | `tests/` (cases easy/medium/complex, second schema `hr`, baselines, `runbook.md`); generated data is rebuilt by `tools/make_testdata.py` |
| Prototypes | `prototype_code/` (first optimizer and evaluator experiments) |
| Plans and docs | `BUILD_PLAN.md`, `PLAN_REVIEW.md` (independent review), `notes/` (initial prompt, research, tricky rules) |
| Logs | `progress.md` (one row per iteration), `runs/` (evaluator, test-suite and meta-eval reports), `.apd/hooks.log` |
| Prompts | `prompts/` (every user prompt and every subagent prompt, per session; `INDEX.md` lists sessions) |
| Raw agent session files | `ai-sessions/raw/<session-id>.json` + `.history.jsonl`, for main sessions and subagents. Copied verbatim from `~/.snowflake/cortex/conversations`; only embedded base64 file payloads are replaced with a placeholder so no binaries ship. `ai-sessions/*.html` are readable walkthroughs, alongside the raw files rather than replacing them; `ai-sessions/TEST_SESSION.html` covers the final session (held-out check, analysis, packaging). |
| Git history | `git-history/` (`git_log.txt` full log with stats, `git_log_patch.txt` every patch, `git_reflog.txt`). The package ships without `.git` because an early commit contained a PDF; these text exports carry the full history. |

**Not included:** binaries (`minivm-takehome/bin/`, the one-pager PDF), and generated output (`eval_out/`, caches). The held-out trap set used for the final check was kept out of the build sessions and is not included either. The last session (`c9f778f7`) did read three of its cases while analysing the optimizer's report, and that is visible in its raw transcript.

## 2. Written plan

`FUTURE_PLAN.md`: what I would do with a few days and unlimited compute and tokens.

## 3. AI models and spend

`AI_USAGE.md`: models, tokens and credits, from Snowflake's Cortex Code usage history (`SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_COCO_USAGE_HISTORY`). **≈ 51.9 credits in total**, mostly claude-opus-5-5 in Cortex Code Desktop (44.0), plus openai-gpt-5.4 for the independent review (5.3), with small amounts of claude-sonnet-5-5 and gemini-3.7-flash.

**Split by phase:**

| Phase | Sessions | Credits | Share |
|---|---|---|---|
| Planning | research, prototypes and build plan (Desktop) + independent plan review (CLI) | ≈ 22.7 | 44% |
| Building | evaluator, test suite and optimizer skeleton (with 3 subagents) + optimizer rules 1–4 | ≈ 21.6 | 42% |
| Testing | held-out check, analysis of the misses, packaging | ≈ 2.9 so far | 6% |
| Not attributed | other CLI use, a build session reopened later | ≈ 4.7 | 9% |

**Mistake: planning ran at extra-high thinking when medium would have done.** The raw session files record a thinking-effort setting per message. Planning is the only session that used `xhigh` (20:05–20:37 UTC). In that window each request cost about **2.2× the credits** of a medium request (0.159 vs 0.073) and wrote about 5× the output tokens. Building and testing ran at medium or low. Running those 27 requests at medium would have saved about **2.3 credits, ~4% of the total**. The work itself (reading docs, hand-optimizing examples, drafting a plan) didn't need the extra reasoning. Next time, effort is set per task: high only for hard reasoning such as proving a rewrite safe, and medium or low for routine work.

## How to run

See `tests/runbook.md`. In short: `./evaluate ./optimize` checks the optimizer for defects, and `python3 tools/bench.py ./optimize -q` reports the suite speedup. You need `bin/minivm` from the original take-home bundle placed at `minivm-takehome/bin/`.
