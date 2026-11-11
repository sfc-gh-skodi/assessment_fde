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
| Raw agent session files | `ai-sessions/raw/<session-id>.json` + `.history.jsonl`, for main sessions and subagents. Copied verbatim from `~/.snowflake/cortex/conversations`; only embedded base64 file payloads are replaced with a placeholder so no binaries ship. `ai-sessions/*.html` are readable walkthroughs, alongside the raw files rather than replacing them. |
| Git history | `git-history/` (`git_log.txt` full log with stats, `git_log_patch.txt` every patch, `git_reflog.txt`). The package ships without `.git` because an early commit contained a PDF; these text exports carry the full history. |

**Not included:** binaries (`minivm-takehome/bin/`, the one-pager PDF), and generated output (`eval_out/`, caches). The held-out trap set used for the final check was kept out of the build sessions and is not included either. The last session (`c9f778f7`) did read three of its cases while analysing the optimizer's report, and that is visible in its raw transcript.

## 2. Written plan

`FUTURE_PLAN.md`: what I would do with a few days and unlimited compute and tokens.

## 3. AI models and spend

`AI_USAGE.md`: models, tokens and credits, from Snowflake's Cortex Code usage history (≈ 51.9 credits in total).

## How to run

See `tests/runbook.md`. In short: `./evaluate ./optimize` checks the optimizer for defects, and `python3 tools/bench.py ./optimize -q` reports the suite speedup. You need `bin/minivm` from the original take-home bundle placed at `minivm-takehome/bin/`.
