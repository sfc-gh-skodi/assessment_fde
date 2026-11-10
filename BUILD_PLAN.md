# BUILD_PLAN — MiniVM optimizer + evaluator

Goal: `./optimize program.mini schema.json` prints a faster equivalent program (<1 s).
`./evaluate OPTIMIZER` exits non-zero if the optimizer ever changes results (<2 min).
**Correctness first: a wrong answer is worse than a slow one.**

Numbers marked **[measured]** come from `bin/minivm` on this machine; **[est]** are estimates.

---

## 0. Facts we build on

| Fact | Source |
|---|---|
| All 8 examples reproduce `examples/expected/*.json` rows and cycles exactly | [measured] |
| `bin/minivm --schema examples/data.json` regenerates `examples/schema.json` exactly, so we can make schemas for our own data | [measured] |
| One `bin/minivm` run takes ~42 ms (mostly process start); python start ~31 ms; 16 cores | [measured] |
| Example cycles: q1 13766, q2 3617, q3 8562, q4 18442, q5 5518, q6 6338, q7 2596, q8 1524 | [measured] |
| Hot spots: q4 GATHER 6672 + UPPER/RTRIM 5132; q1 CAT+LEFT 7124; q3/q6 self-HJOIN+GROUP ≈ 3200 each; redundant SORTs in q1/q4/q5 | [measured, prefix-diff profiler] |
| Dead `DIV x,0` still errors, so dead-code removal can only remove errors (allowed: "if the input errors, anything goes") | [measured] |
| NUM prints keep scale (`"2.0"` vs `"2.00"`); INT+NUM gives NUM; INT beyond ±2^63 prints as a string | [measured] |
| HJOIN = NLJOIN results, ordered by (i, j); NULL keys never match unless `NULLEQ` | [measured] |
| GROUP treats NULL = NULL, and `1` and `1.00` share a group; groups are numbered by first appearance | [measured] |
| IDX drops FALSE and NULL; IF treats a NULL condition as FALSE; `IS` is never NULL | [measured] |
| Type errors are per row, and never on empty or all-NULL columns, so whether a program fails depends on its data | [measured] |
| Empty GALL: GCOUNT 0, GSUM/GMIN/GFIRST NULL; GATHER of a NULL index errors | [measured] |
| VM limits: 20k instructions, 4M values per register, 64M total, ~300M work, 10k rows per table | docs |

---

## 1. Requirements → how we meet them → how we prove it

| # | Requirement (one-pager) | How we meet it | Proof |
|---|---|---|---|
| R1 | `./optimize program.mini schema.json` prints a program | Python 3 stdlib only, no deps; on any internal failure it prints the input unchanged | runner checks exit 0 and that `bin/minivm` parses the output |
| R2 | Same results on any data satisfying the schema constraints | rewrites are justified only by semantics plus **constraints** (never stats); each rewrite has a written safety rule (§3) | evaluator over many generated datasets (§4) plus mutant-optimizer recall test |
| R3 | Order doesn't matter unless the program specifies it | the optimizer always **preserves exact order** (strictest); the evaluator compares order only when the original specifies it (§2 Q1) | rubric O2 |
| R4 | Numbers within 1e-6 relative | the optimizer avoids changing arithmetic, so values are usually bit-identical; the comparator uses a relative tolerance | rubric O3 |
| R5 | Input errors → anything goes | the evaluator skips (program, data) pairs where the original errors | rubric O5 |
| R6 | ≤1 s per program | linear-ish passes and a hard internal deadline (0.8 s) that falls back to the best result so far | runner times every call; p100 reported |
| R7 | Fewer cycles, "noticeably faster" on unseen programs | general passes, not example-specific hacks; measured on held-out generated programs | perf report: speedup per program and geomean |
| R8 | `./evaluate OPTIMIZER` exits 0 or non-zero; any optimizer with the same CLI | black-box: calls `OPTIMIZER prog schema` as a subprocess | identity optimizer → exit 0; mutant optimizers → non-zero |
| R9 | Evaluator ≤2 min, may use `bin/minivm` | parallel pool (16 workers), 100 s wall-clock budget, deterministic seed | runner reports wall time |
| R10 | Submission: code, prompts, logs, raw sessions, git history, no binaries, models and spend, "few days" plan | §10 | checklist before sending |

---

## 2. Open questions → default we use

| # | Question | Default |
|---|---|---|
| Q1 | When does the program "specify" order? | Order is specified iff the row positions reaching `OUT` come from a `SORT`/`TOPK` and no later reordering (join/group) loses that order. Otherwise compare as multisets. The **optimizer** preserves order regardless. |
| Q2 | Is `"2.0"` vs `"2.00"` a difference? Or INT `2` vs NUM `"2.0"`? | Numbers are compared by value (rule R4), so no. Type is not compared for numbers; STR/DATE/BOOL/NULL must match exactly. |
| Q3 | Does a NULL equal a NULL in output comparison? | Yes. NULL vs non-NULL is a defect. |
| Q4 | Is a different `ncols` or column order a defect? | Yes, always. |
| Q5 | Optimized program errors, times out (>1 s) or hits a VM limit where the original succeeds? | Defect. |
| Q6 | Optimizer crashes or prints garbage? | Defect (counted as "optimizer failure"). |
| Q7 | Can we rely on `stats`? | Only for **cost choices** (HJOIN vs NLJOIN, which side to filter), never for correctness. Stats describe one dataset. |
| Q8 | "Faster" measured how? | `cycles` reported by `bin/minivm`, on the example data and on generated data. |
| Q9 | Can the optimizer run `bin/minivm`? | Not required, and we don't depend on it (the grader may not provide it to `optimize`). |
| Q10 | Hidden programs: same shape as the examples? | Assume "legacy" SQL-ish plans: wide GATHER fan-outs, late filters, self-joins, redundant sorts, dead columns. |

---

## 3. Optimizer design

**Pipeline:** parse → SSA IR (rename registers, def-use, value metadata: source table, row domain, type, nullability, sortedness) → passes to a fixpoint → cost check → emit.
**Global guard:** if the optimized program's estimated cost ≥ the original's, or any pass throws, emit the original.

### Rewrites ranked by (gain ÷ risk)

| Rank | Rewrite | Gain [est] | Risk | Safety rule |
|---|---|---|---|---|
| 1 | **Dead-code elimination** (unused LOAD/GATHER/string ops; e.g. q7 `upper r14`, `dow r15`) | 5–25% | very low | Removing instructions only removes possible errors. Never remove `OUT`. |
| 2 | **GATHER composition and sinking**: `GATHER(GATHER(s,i),j)` → `GATHER(s, GATHER(i,j))`; carry *index vectors* through joins and filters and gather payload columns only at the end, only for columns that reach `OUT` | 20–50% on wide plans (q1, q4, q5) | low | Identity of index composition. Indices are in range by construction (same as the original). |
| 3 | **CSE**: duplicate LOADs and identical ops (q2 loads `l_disc` twice) | small | very low | Pure ops are deterministic. |
| 4 | **Late materialization of element-wise ops**: compute `f(x)` after filters (`f(GATHER(x,i)) = GATHER(f(x),i)`), only on surviving rows | 20–40% (q1, q4, q7 string ops) | low | Evaluating on a *subset* of rows can only remove errors. **Never** move an op onto rows it wasn't evaluated on, and never onto a join-expanded domain larger than the original (cost check). |
| 5 | **Constraint rewrites**: `SORT` keys = prefix of `sorted` ASC NF on an unpermuted table → identity; predicate always TRUE by `not_null` + `check` (q1 `GE l_qty,1`) → drop it; `key` uniqueness ⇒ joins are at most 1:1, so a GROUP on key cols is identity | 5–15% | low-med | Uses only declared constraints. Must also prove the column isn't permuted or filtered in between (sortedness survives IDX/GATHER-by-ascending-index only). |
| 6 | **Filter pushdown below joins** (q4 filters after 4 joins) | 30–70% on q4-like plans | med | Filtering the left side with IDX preserves the (i, j) output order. Applies only when the predicate depends on one side. Cast-free: same ops, fewer rows. |
| 7 | **Sort reduction**: `SORT` + slice-first-n → `TOPK`; sort after filters, not before; drop sorts whose order is later destroyed | 5–20% | med | TOPK = first n of the same stable SORT (doc). Ties are preserved because both are stable. |
| 8 | **Join algorithm choice** HJOIN ↔ NLJOIN by cost model | small-med | very low | Identical results by spec; only cost differs. Stats are fine here. |
| 9 | **Idiom rewrites** (pattern-matched, each behind a precise matcher): self-join + GROUP + GMAX → `GROUP/GMAX/GID/GATHER` (q6); "count of better rows" top-n per group → sort + rank (q3); join-then-dedup semi-join → dedup the right side first (q5) | 2–10× on those programs | **high** | Must match NULL semantics exactly: HJOIN drops NULL keys but GROUP keeps them, so filter out NULL keys explicitly; GMAX "first of equals" printing scale. Only enabled after the evaluator passes with 0 defects on targeted stress data. |

**Rule: never trade correctness for cycles.** Each rewrite ships with a unit test (before/after program pair) plus targeted adversarial data.

**VM-limit safety:** no rewrite may increase any register's maximum length or the total HJOIN/GROUP input (work limit). This is checked by the cost estimator.

---

## 4. Evaluator design (`./evaluate OPTIMIZER`)

1. **Corpus (seeded, deterministic).**
   - The 8 example programs.
   - **Generated programs**: a template generator over the example schema that emits legacy-style plans: scan/filter/project, 1–4 joins along `refs`, group-aggregate, sort/topk/slice, string transforms (NULLIFE/RTRIM/UPPER/CAT/LEFT), dates, arithmetic, with deliberate bloat (wide fan-outs, late filters, dead columns, self-joins).
   - **Mutants of the examples** (swap predicates or literals, change sort keys or directions).
   - Programs are type-correct by construction, and are kept only if the original runs without error on at least one dataset.
2. **Data (per schema).** A constraint-respecting generator: unique `key`s, `refs` drawn from the parent key (plus NULLs where nullable), `check` bounds including boundaries, `sorted` order, `not_null`. It is adversarial: NULLs, ties, `'Open '`/`'OPEN'`/`'open'`, empty strings, empty tables, 1-row tables, duplicate join keys, NUM scale variants (`1.0` vs `1.00`), boundary dates. Every dataset is validated by `bin/minivm --schema` (it checks constraints), and its schema file is produced the same way.
3. **Run.** For each program: call `OPTIMIZER prog.mini schema.json` once (1 s timeout). Then run the original and optimized programs on K datasets (K≈8–12).
4. **Compare** with the rubric in §5. Skip pairs where the original errors.
5. **Report** defects with a minimal repro (program, optimized program, dataset, diff) saved to `eval_out/`. Exit 1 if there are any defects (or optimizer failures), else 0.
6. **Budget** [est from measurements]: ~60 programs × (1 optimizer call + 2×10 VM runs) ≈ 1,300 runs × 42 ms ÷ 16 workers ≈ 4–8 s, plus optimizer time ≤ 60 s worst case in parallel. A hard watchdog at 100 s stops new work, prints the report, and exits non-zero if any defect was found so far.

**Evaluator self-test (meta-eval):**
- The identity optimizer (`cat`) must give 0 false alarms.
- A set of **known-bad mutant optimizers** must each be caught: drop a filter, flip `ASC`/`DESC`, drop `NULLEQ`, drop a tie-break sort key, replace `IS` with `EQ`, reorder unsorted output only (must *not* be flagged when order isn't specified), change NUM rounding, introduce DIV-by-zero on filtered rows.
- Recall = caught ÷ mutants. Target 100%.

---

## 5. Eval rubric

**Outputs (per program × dataset):**
- **O1** `ncols` equal, and the optimized run succeeds whenever the original succeeds.
- **O2** Rows equal as a list if order is specified (Q1), else as a multiset (sort both by canonical key).
- **O3** Numbers (INT or NUM, parsed exactly via `Decimal`) satisfy `|a−b| ≤ 1e-6·max(|a|,|b|)` (`a==b` for 0). STR/DATE/BOOL are exact; NULL = NULL.
- **O4** The optimized program doesn't exceed VM limits or the 1 s optimizer limit.
- **O5** If the original errors, the pair is skipped (not a defect).

**Programs (performance):**
- **P1** Cycles of optimized vs original per dataset: speedup ratio, plus a geomean over the corpus.
- **P2** Instruction count before and after.
- **P3** Peak register size and VM-limit headroom (never worse than the original).
- **P4** Optimizer wall time (max must be < 1 s).
- **P5** Regression flag: optimized cycles > original cycles on any dataset (allowed but reported; target zero).

**Evaluator:**
- **E1** Defects caught on mutant optimizers (recall, target 100%).
- **E2** False alarms on the identity and correct optimizers (target 0).
- **E3** Wall time (< 120 s; target < 60 s).
- **E4** Determinism: the same seed gives the same verdict.

---

## 6. Stopping criteria for the build ↔ evaluate loop

- **Success, stop:** 0 defects on the full eval with 3 different seeds; E1 = 100% and E2 = 0; geomean speedup ≥ 2× on examples [target est]; all optimizer calls < 1 s; evaluator < 2 min.
- **No more improvement, stop that rewrite:** two consecutive iterations where geomean cycles improve by < 3%, or a rewrite's gain doesn't justify its risk. Move to the next rank, or stop.
- **Budget used up, stop:** user time hits 2h45m, or the AI token budget reaches its cap (we track per session). Ship the last green commit.
- **Ask the user when:** a rewrite depends on an open-question interpretation (Q1/Q2); a defect can't be explained within 2 attempts; a fix requires dropping a rewrite that gives > 20% of the gain; or any destructive git action (history rewrite for binaries, §10).
- **Hard rule:** any defect is a red build. Revert or disable the rewrite before doing anything else.

---

## 7. Failure modes

| Failure | Detection | Fix / prevention |
|---|---|---|
| Rewrite changes NULL semantics (HJOIN vs GROUP NULL keys) | targeted NULL-heavy data; mutant tests | explicit NULL filters in idiom rewrites; per-rewrite unit tests |
| Rewrite introduces an error (DIV by 0, type error, out-of-range GATHER, DATEADD overflow) on rows the original skipped | O1 failures on adversarial data | the "subset of evaluated rows" rule (§3 #4) |
| Lost tie order (unstable reorder) | O2 on tie-heavy data | always preserve order; only stable sorts and IDX/ascending composition |
| Relying on stats instead of constraints | data generator deliberately violates stats (different ranges, distincts) | lint: the correctness path never reads `stats` |
| Order-insensitive comparison hides a real defect, or order-sensitive gives false alarms | meta-eval with "reorder-only" mutant | Q1 detector unit-tested on all 8 examples |
| NUM scale or rounding differences | O3 tolerance; DIV/MUL results compared via Decimal | don't reassociate arithmetic |
| Optimized program blows VM limits (join expansion) | O4; P3 report | cost check: never increase peak register size or HJOIN/GROUP input |
| Optimizer > 1 s on big programs (20k instructions) | timing in runner; a stress program with 20k lines | linear passes, iteration cap, 0.8 s deadline → fall back |
| Evaluator > 2 min | wall-time report | watchdog at 100 s; parallel pool; cap on corpus size |
| Generator makes invalid data | `bin/minivm --schema` rejects it | regenerate; count rejections in the report |
| Overfitting to 8 examples | held-out generated programs scored separately | rewrites must be general passes; idioms gated |

---

## 8. Test suite and runners

**Easy** (one pass each): DCE-only, CSE-only, SORT on a sorted table, always-true predicate, HJOIN↔NLJOIN choice, empty tables, all-NULL columns.
**Medium:** examples q7, q8, q2; filter pushdown through one join; SORT+SLICE→TOPK; string op after filter.
**Complex:** q1, q4, q5 (multi-join fan-outs); q3, q6 (self-join idioms); generated 3–4-join plans; 20k-instruction stress program for timing.

Layout:
```
tests/cases/{easy,medium,complex}/NAME.mini     # + optional NAME.expect_opt (golden)
tests/data/                                     # generated datasets + schemas
tools/gen_data.py  tools/gen_prog.py  tools/compare.py  tools/profile.py
run_tests.sh   # unit + suite: each case × each dataset, original vs optimized
run_eval.sh    # ./evaluate ./optimize + meta-eval (identity + mutants)
```
Every run prints a report: `pass/fail per case | cycles orig→opt (×speedup) | instructions | max opt time | defects | geomean`. It also appends a JSON line to `notes/runs.jsonl` for trend tracking.

---

## 9. Progression log

`notes/PROGRESSION_LOG.md` gets one entry per iteration: *date · approach tried · result (defects, geomean, timing) · what we learned · keep/revert*. The first entries are the facts in §0 and the probe results.

---

## 10. Timeline (2–3 h of user time)

| Time | Work | Checkpoint |
|---|---|---|
| 0:00–0:20 | Scaffolding: parser/IR/emitter (round-trip = identity), compare.py, data generator validated by `--schema` | CP1: identity optimizer round-trips all examples, eval = 0 defects |
| 0:20–0:50 | Evaluator v1: corpus = examples + datasets, parallel, rubric, report; meta-eval mutants | CP2: identity 0 false alarms, mutants caught |
| 0:50–1:40 | Optimizer passes 1–5 (DCE, GATHER sinking, CSE, late materialization, constraint rewrites), iterating with the eval | CP3: 0 defects, geomean ≥ 1.5× [target] |
| 1:40–2:15 | Passes 6–8 (filter pushdown, sort reduction, join choice); program generator for held-out tests | CP4: 0 defects on 3 seeds |
| 2:15–2:40 | Idioms (#9) only if green; otherwise skip | CP5 |
| 2:40–3:00 | Submission packaging (§11) | done |

**Cut order if late:** idiom rewrites (#9) → program generator (keep examples + mutants) → join choice → sort reduction. **Never cut:** the evaluator, meta-eval, or the fall-back-to-original guard.

---

## 11. Submission

- **Git history from the start:** commit at every checkpoint, with messages that reference the progression log.
- **No binaries — action needed.** The initial commit (already pushed to `sfc-gh-skodi/assessment_fde`) contains `minivm-takehome/bin/minivm-*` (5 binaries). We need to (a) add `minivm-takehome/bin/` to `.gitignore` and `git rm --cached` it, and (b) **purge it from history** (rewrite plus force-push). This needs explicit approval. The alternative is a fresh repo seeded without `bin/`. Also exclude the `bin/minivm` launcher script, since the one-pager names it explicitly.
- **Raw AI session files:** copy the Cortex Code session files (`~/.snowflake/cortex/conversations/<project>/<session>.json` and `.history.jsonl`) into `ai-sessions/` unmodified.
- **Models and spend:** Cortex Code with `claude-opus-5-5`; record tokens and spend per session in `notes/AI_USAGE.md`.
- **"Few days, unlimited compute" plan:**
  - an equality-saturation (e-graph) optimizer with a calibrated cost model;
  - a cost-based join-order search using stats;
  - translation validation: an SMT or bounded-model check that each rewrite is equivalent under the constraints;
  - a coverage-guided fuzzer for the evaluator, with test-case shrinking;
  - a much larger generated corpus, run in parallel in the cloud;
  - learning which idioms legacy programs use from a big corpus.
