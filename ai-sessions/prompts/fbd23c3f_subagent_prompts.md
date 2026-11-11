# Prompts sent by the main agent to subagents

Session `fbd23c3f-608b-4330-a7ac-860d8f7fb94a` · Execute MiniVM Build Plan

## Build test suite, data, baselines (generalPurpose)

```
You are the TEST SUITE + TEST DATA + BASELINES builder for repo /Users/skodi/Desktop/take-home-assessment (MiniVM take-home: an optimizer rewrites MiniVM programs to use fewer cycles with identical results; an evaluator checks it). WRITE CODE/FILES. Python 3 stdlib only (3.8+ compatible). Work autonomously, then return a short report.

Read: `BUILD_PLAN.md` §2, §5 (safety traps S1–S10), §11 (test suite plan: easy/medium/complex, data, scale stress); `minivm-takehome/docs/**` (language, running, cycles, instructions); examples in `minivm-takehome/examples/{programs,schema.json,data.json}`; existing tests already written: `tests/cases/{easy,medium,complex}/*.mini` (28 programs, each with a header comment). VM: `minivm-takehome/bin/minivm PROGRAM DATA` prints {"ncols","rows","cycles"}; `bin/minivm --schema DATA` prints schema with stats. You may import `evaluator/vm.py` (runner: `run(prog, data)`, `schema_of(data)`) and `evaluator/datagen.py` (`generate(schema, size, seed, lits)`, `harvest(texts)`) — read-only use, don't edit them.

## Deliverables
1. Expand `tests/cases/`: aim for ~15 easy, ~15 medium, ~12 complex programs on the example schema (keep the existing ones; fix any that are invalid). Each file starts with a `; easy|medium|complex: ...` comment naming the rewrite it targets or the TRAP it guards (e.g. NULL join keys vs GROUP, no-key table fan-out, nullable column with check, DIV guarded by a filter, NUM scale 1.0 vs 1.00 in GMIN/GSUM, Unicode UPPER changes length before LEFT, TOPK ties, empty-table GALL vs GROUP, overwritten registers, NULLEQ joins, sort on `sorted` table with filtered rows, SORT DESC tie-breaks, self-join idioms, 3–4-join star schemas with late filters, labels built before filters). Every program must run without error on `minivm-takehome/examples/data.json` and give NON-EMPTY output there or on generated data.
2. A second hand-written schema + data under `tests/schemas/<name>/` (e.g. an HR/sales schema with different table/column names, composite key, self-ref, sorted, check, nullable refs, a no-key table): `data.json` (valid; check with `bin/minivm --schema`), `schema.json` (output of --schema), and ~10 programs `tests/schemas/<name>/programs/*.mini` (easy→complex) for generalization testing.
3. Test data: `tools/make_testdata.py` — deterministic (fixed seeds) generation into `tests/data/<schema>/{small,medium,large}_*.json` using evaluator/datagen.py with literals harvested from the test programs, validated with --schema. Generated data must be git-ignored (append `tests/data/` to .gitignore) and rebuildable byte-for-byte. Also a scale-stress generator `tools/make_stress.py` writing to `tests/stress/` (gitignored if large): a 20,000-instruction program, a near-10,000-row table set, and a join fan-out near the 4M-values limit — keep these separate from the normal corpus (NOT under tests/cases).
4. Baselines: `tools/bench.py OPTIMIZER [--out FILE]` runs every program in tests/cases (+ examples, + tests/schemas programs) through OPTIMIZER (CLI: `OPTIMIZER program.mini schema.json`, prints a program) on example data + generated test data, and reports per-program and per-tier (examples/easy/medium/complex/schema2) geomean speedup (original cycles / optimized cycles), defect count (results differ: compare rows as multiset unless the program has SORT/TOPK, numbers within 1e-6 relative — you may import evaluator/compare.py functions read-only), optimizer max time, and total cycles. Write `tests/baselines.json` for (a) identity `minivm-takehome/optimize`, (b) hand-optimized `prototype_code/optimizer_agent/hand_opt.sh`, including the ORIGINAL cycles per program per dataset (the baseline the optimizer must beat). Make bench fast (parallel, platform binary via evaluator/vm.py) — target < 30 s.

## Logging (required)
Append one row per iteration to `runs/testsuite_iterations.md` (create with header):
`| # | Time (UTC, date -u +%H:%M) | Approach (ELI5, 1-2 sentences) | Programs (easy/med/complex/schema2) | Baseline result (identity, hand-opt geomeans, defects) | Cost/time (bench wall s) | Takeaway (< 5 sentences) |`

## Boundaries
You own ONLY: `tests/cases/**`, `tests/schemas/**`, `tests/data/` (generated), `tests/stress/`, `tests/baselines.json`, `tools/bench.py`, `tools/make_testdata.py`, `tools/make_stress.py`, `runs/testsuite_iterations.md`, and appending to `.gitignore`. Do NOT edit `evaluator/`, `optimizer/`, `optimize`, `evaluate`, `tests/regressions/`, `progress.md`. Other agents work concurrently (optimizer builder runs ./evaluate constantly, which picks up tests/cases/**/*.mini — so only add programs that are valid; write to a temp name and move into place once verified).
Git: commit as you go, ONLY your paths: `git add tests/cases tests/schemas tests/baselines.json tools/bench.py tools/make_testdata.py tools/make_stress.py runs/testsuite_iterations.md .gitignore && git commit -m "..."` (retry if .git/index.lock exists). Never reset/amend/force. End messages with:

Generated with [Snowflake CoCo](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code)

Co-authored-by: Snowflake CoCo <noreply@snowflake.com>

## Final report (your only message back)
Iteration rows, counts per tier, baseline table (per tier geomean for identity and hand-opt, total original cycles), how to run bench/make_testdata/make_stress, any invalid programs fixed, commit hashes.
```

## Build ./optimize iteratively (generalPurpose)

```
You are the BUILDER of the MiniVM optimizer in repo /Users/skodi/Desktop/take-home-assessment. WRITE CODE. Python 3 stdlib only, must run on Python 3.8+ (no match statements, no 3.10+ only syntax). Work autonomously until done, then return a short report.

## Task
Build `./optimize program.mini schema.json` (repo root, executable sh wrapper -> `python3 optimizer/main.py "$@"`) that prints a program with the SAME results in FEWER cycles, in < 1 s (use an internal deadline ~0.7 s; on any exception/timeout/unsure case print the input program unchanged). Read first: `minivm-onepager` requirements (summarized below), `BUILD_PLAN.md` (§2 lessons, §3 optimizer design, §5 safety rules S1–S10 — obey them), `minivm-takehome/docs/**` (language, values, running, cycles cost model, instructions/*), the 8 examples `minivm-takehome/examples/programs/*.mini` + `schema.json`, and the hand-optimized versions `prototype_code/optimizer_agent/q000N.opt.mini` (each header says which rule it relies on) and known-WRONG versions `q000N.naive.mini` (mistakes you must not make).

Requirements: same results on ANY data satisfying the schema's constraints (key, not_null, refs, check, sorted) — use stats only for cost decisions, never correctness. Output row order must be preserved exactly whenever the original specifies it (safest: always preserve exact order). Numbers within 1e-6 relative (don't change arithmetic; beware NUM scale: 1.0 vs 1.00 print differently, GSUM uses max scale, GMIN/GMAX return first of equals). If the original errors on some data, anything goes; but the optimized program must NEVER error where the original succeeds (S1/S2: an op may only run on a subset of the rows/values it originally ran on unless it is provably total — DIV/IDIV/MOD/DATEADD/NUM arithmetic overflow/mixed-type compares can error). HJOIN never matches NULL keys (unless NULLEQ), GROUP groups NULLs together. customers has no key (joins can fan out). The optimizer must NOT call bin/minivm.

## Suggested architecture (you may improve it)
parser -> SSA IR (registers can be overwritten; `HJOIN a,a,...` same-register form) -> analyses (types from schema, nullability, row-domain/provenance of each register, position vectors "into" which domain, sortedness from `sorted` constraint) -> passes to fixpoint -> cost estimate from docs/cycles.md using stats row counts + simple selectivity -> emit; global guard: if estimated cost not lower, emit input.
Passes in value order (from BUILD_PLAN §3): (1) DCE + CSE (duplicate LOADs/ops); (2) GATHER composition GATHER(GATHER(s,i),j)=GATHER(s,GATHER(i,j)) + gather only columns reaching OUT (late materialization); (3) sink element-wise ops below filters/gathers (compute after filter: safe because it evaluates on a subset of the same values) when not fan-out-expanding; (4) sort reduction: SORT whose keys are a prefix of a table's `sorted` (ASC NF) on rows in stored order (LOAD / ascending IDX subsets) is identity; SORT -> IDX/filter -> SLICE(IOTA) => filter first then TOPK (filter commutes with stable sort); SORT feeding only order-insensitive GALL aggregates (GSUM/GCOUNT/GCOUNTV; GMIN/GMAX only for non-NUM) is dead; (5) filter pushdown through joins: conjuncts of an AND mask that depend on one join side only and are total (comparisons of statically compatible types, IS/ISNULL/NOT/AND/OR, NVL/NULLIFE/RTRIM/TRIM/UPPER/LEFT/SUBSTR/CAT/LEN, YEAR/MONTH/DAY/DOW) can be evaluated on that side before the join — this preserves pair order (i then j); (6) constraint rewrites: always-TRUE predicates (e.g. GE l_qty,1 with not_null+check), exactly-one-match lookup joins (left key derived only by gathers from a not_null column with refs to the right table's single-column key, right key = full unfiltered LOAD of that key) can be postponed after filters; (7) NLJOIN->HJOIN when cheaper; (8) risky idioms (self-join count-of-better -> sort+rank, self-join+GMAX -> GROUP+GMAX+GID with explicit NOT ISNULL key filter, join+SORT+GROUP/GFIRST dedup -> semi-join) ONLY after everything else is green, each guarded by exact pattern match + safety rules.

## Orchestrator–evaluator loop (scripts, not LLM judgment)
After EVERY pass/iteration run:
- `./evaluate ./optimize --quick` (~10 s) while developing; `./evaluate ./optimize --seed N --json runs/opt_iterN.json` (full, ~30 s) for iteration results. It exits non-zero on any defect and saves repros (orig.mini, opt.mini, data.json, defect.txt) under ./eval_out/. Clear ./eval_out between runs.
- `python3 prototype_code/evaluator_agent/eval-proto.py ./optimize --quiet` — reports geomean speedup on the 8 examples x 40 datasets (hand-optimized reference = 2.39x).
- a defect is a red build: fix or disable the rewrite before anything else. Turn every defect you fix into a regression test: copy orig program to `tests/regressions/<name>.mini` (example schema only) — ./evaluate replays tests/regressions automatically.
- check max optimizer time reported (< 1 s; aim < 0.3 s), and test a 20,000-instruction stress program (generate one with a script) finishes < 1 s.
Stopping criteria: 0 defects on full ./evaluate with seeds 1, 2 and 3; eval-proto geomean >= 2.0x on examples; geomean > 1x on generated programs (./evaluate geomean); max optimizer time < 1 s. Stop optimizing further after 2 consecutive iterations with < 3% geomean gain. Never weaken correctness for speed.

## Logging (required)
Append one row per iteration to `runs/optimizer_iterations.md` (create it with this header):
`| # | Time (UTC, from date -u +%H:%M) | Approach (ELI5, 1-2 sentences a 5-year-old could follow) | Defects (quick/full) | Speedup examples (eval-proto) | Speedup all (./evaluate) | Cost/time (max opt s, eval wall s) | Takeaway (< 5 sentences) |`
Keep it tabular and short.

## Boundaries
You own ONLY: `optimizer/**`, `./optimize`, `tests/regressions/**`, `runs/optimizer_iterations.md`, `runs/opt_iter*.json`. Do NOT edit `evaluator/`, `evaluate`, `tests/cases/`, `tools/`, `progress.md`, `BUILD_PLAN.md` (other agents own them and may change them concurrently; if ./evaluate seems broken for a minute, wait and retry). Never import from evaluator/ (independence rule).
Git: commit as you go, one rewrite per commit, ONLY your own paths: `git add optimizer optimize tests/regressions runs/optimizer_iterations.md && git commit -m "..."` (if .git/index.lock exists, wait a few seconds and retry). Never reset/amend/force. Commit messages end with:

Generated with [Snowflake CoCo](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code)

Co-authored-by: Snowflake CoCo <noreply@snowflake.com>

## Final report (your only message back)
Return: the iteration table rows, final metrics (defects per seed, examples geomean, all-programs geomean, per-example speedups q0001..q0008, max optimizer time, stress test time), which passes are enabled/disabled and why, known risks/limitations, and commit hashes.
```

## Harden ./evaluate + meta-eval (generalPurpose)

```
You are the EVALUATOR hardener (red team) for repo /Users/skodi/Desktop/take-home-assessment. WRITE CODE. Python 3 stdlib only, must run on Python 3.8+. Work autonomously, then return a short report.

## Context
Assignment: `./evaluate OPTIMIZER` tests any optimizer with the CLI `OPTIMIZER program.mini schema.json` (prints an optimized MiniVM program). Exit 0 if no defects, non-zero if any. A defect = an optimized program whose results differ from the original's: same results required on any data satisfying the schema's constraints; order doesn't matter unless the input program specifies it; numbers within 1e-6 relative; if the original errors, anything goes; optimizer must take ≤ 1 s per program. Evaluator must finish in ≤ 2 minutes and may use bin/minivm. Read: `BUILD_PLAN.md` §4 (evaluator design), §6 (rubric), §7 (unclear rules Q1–Q10 and chosen defaults), §10; `notes/tricky_rules.md`; `minivm-takehome/docs/**`; the prototype `prototype_code/evaluator_agent/{eval-proto.py,fake_opt.py,meta_eval.py,tricky_checks.py}`.
A production evaluator already exists (orchestrator wrote it, committed d7c30ff): `./evaluate` -> `evaluator/main.py`, with `evaluator/vm.py` (platform binary runner), `evaluator/datagen.py` (constraint-respecting tricky data, any schema), `evaluator/progen.py` (random legacy-style program generator + random schemas), `evaluator/compare.py` (parser, output_ordered, static output types, tie-aware comparison by instrumenting the original to also output sort keys, TOPK/SLICE cut-off ties => WARN). Current results: identity optimizer 0 defects (quick 777 checks 5 s; full ~3800 checks 23 s); naive_opt.sh caught.

## Your job (iterate with scripts)
1. Port the meta-eval: `tools/fakes.py` (fake optimizers MODE prog schema: at least the prototype's 8 honest + 11 buggy, plus NEW ones you design from the spec only, e.g. honest: tie-reordering after stable sort with ties where the original's tie order is not "specified" — decide carefully, HJOIN<->NLJOIN, DCE, register rename, reformat/case; buggy: drop NVL, GE->GT, drop NOT ISNULL filter, swap join sides, TOPK n-1, remove a DIV-guarding filter (adds an error), dedup a no-key table, filter pushed above a SLICE, wrong GSUM->GCOUNT, change string literal case, 1e-5 drift, emit invalid program, sleep 1.5 s) and `tools/meta_eval.py` that runs ./evaluate --quick against each fake and reports CAUGHT/MISSED/OK/FALSE-ALARM to `runs/meta_report.md`. Targets: 100% buggy caught, 0 false alarms.
2. Fix evaluator weaknesses you find (misses or false alarms): data generator coverage (plant literals, ties, NULL/'' keys, empty tables, rows > TOPK limits, data that makes originals error), comparator rules, order/tie detection, instrumentation robustness, random schema/program generator validity (count how many generated programs are skipped on every dataset / always empty output — keep only useful ones, or improve generation), determinism (same seed -> identical report), and timing (full run < 60 s target, hard < 120 s with watchdog). Verify `./evaluate` works when invoked from another cwd and with a relative optimizer path, and that it never writes files outside a temp dir except ./eval_out repros.
3. Port `prototype_code/evaluator_agent/tricky_checks.py` ideas into `tools/eval_selftest.py` covering compare.py rules (BOOL vs INT, STR '1.0' vs '1.00' typed, numeric tolerance, tie blocks, ordered detection), runnable in < 10 s.
Run `./evaluate minivm-takehome/optimize`, `./evaluate prototype_code/optimizer_agent/hand_opt.sh` (must be 0 defects) and `./evaluate prototype_code/optimizer_agent/naive_opt.sh` (must catch) after each change.

## Logging (required)
Append one row per iteration to `runs/evaluator_iterations.md` (create with header):
`| # | Time (UTC, date -u +%H:%M) | Approach (ELI5, 1-2 sentences) | Buggy caught | False alarms | Checks / wall s (quick, full) | Takeaway (< 5 sentences) |`

## Boundaries
You own ONLY: `evaluator/**`, `./evaluate`, `tools/fakes.py`, `tools/meta_eval.py`, `tools/eval_selftest.py`, `runs/meta_report.md`, `runs/evaluator_iterations.md`. You must NOT read or import anything under `optimizer/` or `./optimize` (independence: evaluator must be black-box). Another agent is concurrently building the optimizer and running `./evaluate` constantly: keep `./evaluate`'s CLI (`OPTIMIZER [--seed S] [--quick] [--json OUT] [--keep DIR] [-v]`) stable, and make each edit leave it working (run `./evaluate minivm-takehome/optimize --quick` right after edits). Another agent owns `tests/` (it may add test programs under tests/cases which ./evaluate picks up).
Git: commit as you go, ONLY your paths: `git add evaluator evaluate tools/fakes.py tools/meta_eval.py tools/eval_selftest.py runs/meta_report.md runs/evaluator_iterations.md && git commit -m "..."` (retry if .git/index.lock exists). Never reset/amend/force. End messages with:

Generated with [Snowflake CoCo](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code)

Co-authored-by: Snowflake CoCo <noreply@snowflake.com>

## Final report (your only message back)
Iteration table rows, final meta-eval verdict table (each fake: expected, result, defect count), quick/full wall times, any rule decisions you made (and why), remaining known gaps, commit hashes.
```
