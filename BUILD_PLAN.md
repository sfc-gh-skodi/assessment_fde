# BUILD_PLAN: MiniVM optimizer + evaluator (v2)

**Goal.** `./optimize program.mini schema.json` prints a faster program with the same results, in under 1 s.
`./evaluate OPTIMIZER` exits non-zero if the optimizer ever changes results, and finishes in under 2 minutes.
**Correctness first: a wrong answer is worse than a slow one.**

**Sources.**
- The one-pager, and `minivm-takehome/docs/*`, cited as `[doc: file#section]`.
- `notes/examples.md`, `notes/tricky_rules.md`, `notes/research_{optimizer,evaluator,working_model}.md`.
- `prototype_code/` (see its README).

**Tags.** **[M]** = measured with `bin/minivm`; **[E]** = estimate.

---

## 0. Status: built vs to build

| Component | Status | Evidence / location |
|---|---|---|
| Spec reading, VM probes, per-instruction cycle profile | ✅ done | `notes/examples.md`, `notes/tricky_rules.md` |
| Research: optimizer, evaluator, working model | ✅ done | `notes/research_*.md` |
| Hand-optimized versions of all 8 examples | ✅ done: 3.14× geomean on example data; up to 47× on large data **[M]** | `prototype_code/optimizer_agent/q*.opt.mini` |
| Known-bad baselines (one plausible mistake per example) | ✅ done: 8/8 caught **[M]** | `q*.naive.mini` |
| Comparator `cmp.py`, multi-dataset checker `check.py` | ✅ prototype | `optimizer_agent/` |
| Constraint-respecting tricky data generator (small/medium/large, literals harvested from programs) | ✅ prototype: 39 datasets, all pass `--schema` **[M]** | `gen_data.py`, `make_adv_data.py` |
| Prototype evaluator: order-aware, type-safe comparator, platform binary | ✅ prototype: 1.7 s full run **[M]** | `evaluator_agent/eval-proto.py` |
| Testing the tester: 19 fake optimizers, meta-eval | ✅ done: 11/11 buggy caught, 0/8 false alarms **[M]** | `fake_opt.py`, `meta_eval.py`, `meta_report.md` |
| Tricky-rule regression checks | ✅ 56/56 pass **[M]** | `tricky_checks.py` |
| Binaries purged from git history | ✅ done (force-pushed) | `.gitignore`; history starts at `c8b59b8` |
| **`./optimize`**: parser → IR → passes → emitter | ⬜ to build | §3 |
| **`./evaluate`**: production version of eval-proto | ⬜ to build | §4 |
| Random **program** generator (held-out programs, other schemas) | ⬜ to build | §4.1 |
| Tie-aware order comparison (instrumented original) | ⬜ to build | §4.3, Q1 |
| Data that makes the original error (tests the "anything goes" path) | ⬜ to build | §4.1 |
| Test-case shrinking of defects into regressions | ⬜ to build, stretch goal | §4.4 |
| Progression log, AI usage, raw sessions | ⬜ to start | §11 |

---

## 1. Requirements: how we meet each one, and how we prove it

| # | Requirement (one-pager) | How we meet it | Proof |
|---|---|---|---|
| R1 | `./optimize program.mini schema.json` prints a program | Python 3 stdlib. On any internal error, or an estimate that isn't cheaper, it prints the input unchanged | runner: exit 0, `bin/minivm` parses the output |
| R2 | Same results on any data satisfying the schema's constraints | rewrites justified only by semantics and **constraints** (never stats); safety rules in §5 | evaluator over generated data, plus meta-eval |
| R3 | Order doesn't matter unless the program specifies it | the optimizer always preserves order; the evaluator compares in order when the original specifies it (§4.3) | `b_reverse` caught (172 defects) **[M]** |
| R4 | Numbers within 1e-6 relative | the optimizer doesn't change arithmetic; the comparator compares Decimal values with relative tolerance | `h_tiny_drift` OK, `b_drift` caught **[M]** |
| R5 | If the input program errors, anything goes | the evaluator skips pairs where the original errors | rubric O5 |
| R6 | ≤ 1 s per program | linear passes; internal deadline at 0.8 s, then fall back | runner reports max optimizer time |
| R7 | Noticeably faster, on unseen programs and data | general passes (§3), held-out generated programs | perf report: geomean speedup on examples and on held-out programs |
| R8 | `./evaluate OPTIMIZER` exits 0 or non-zero; works for any optimizer with the same CLI | black box: subprocess call plus `bin/minivm` only | meta-eval verdict table |
| R9 | Evaluator ≤ 2 min, may use `bin/minivm` | platform binary (8.3 ms/run), parallel, watchdog at 100 s | wall time in every report |
| R10 | Submission: code, prompts, logs, raw sessions, git history, no binaries, models and spend, "few days" plan | §11 | checklist |

---

## 2. What the examples were hiding (learnings from hand-optimizing)

Each row: the original program's cost, what made it slow, and what that means for the optimizer.

| Example | Cycles orig → hand **[M]** | Hidden lesson |
|---|---|---|
| q0001 | 13766 → 1703 (8.1×) | 52% of the cycles are CAT and LEFT building a label for rows a later filter throws away. **Order of work matters more than the work itself.** `SORT` on `lines` is a no-op because of the `sorted` constraint. `GE l_qty,1` is always TRUE because of `not_null` + `check`. |
| q0002 | 3617 → 2011 (1.8×) | The self-join's *counted* side must stay unfiltered. Filtering it too is the naive bug (`q0002.naive`, caught on 17 datasets). Only the outer side may shrink. |
| q0003 | 8562 → 2817 (3.0×; 37× on large) | A "count of better rows" self-join is O(n²) per group. A sort plus per-group rank is linear. The HJOIN silently drops NULL and `''`→NULL keys, and the rewrite must reproduce that. |
| q0004 | 18442 → 2179 (8.5×; 47× on large) | 36% of the cycles are GATHER fan-out across 4 joins. A SORT before GALL/GSUM is useless. **`customers` has no key**, so de-duplicating `c_id` is wrong (`q0004.naive`). |
| q0005 | 5518 → 3294 (1.7×) | Join, then sort, then GROUP de-dup is really a **semi-join**. De-duplicate the small side first. |
| q0006 | 6338 → 2091 (3.0×; 20× on large) | A self-join followed by GMAX is GROUP + GMAX + GID. GROUP puts NULLs in one group but HJOIN never matches them, so an explicit NULL filter is required (`q0006.naive`). |
| q0007 | 2596 → 637 (4.1×) | Filter first, then TOPK instead of SORT, then build the label for 5 rows. The example data has only 3 July-2023 orders and no tied amounts, so `TOPK 4` and a flipped tie-break both **passed on the example data**. |
| q0008 | 1524 → 1249 (1.2×) | Already tight. Dead loads are the only waste. Not every legacy program is slow. |

**Cross-cutting.**
1. The biggest wins are generic, and the clever rewrites are the riskiest:
   - The generic wins are filter-first, late materialization, GATHER sinking, dead-code elimination, and TOPK instead of SORT.
   - The self-join idioms give the largest gains on large data, and they are also the riskiest.
2. Constraints carry the correctness argument:
   - `not_null` + `refs` to a `key` means exactly one match.
   - `sorted` means a SORT on those keys is a no-op.
   - A table with **no key** can fan out a join.
3. **Weak data hides bugs.**
   - A q0004 baseline was missed until the generator planted the programs' own literals (`'KITCHEN'`).
   - Every gain is relative to the data: on small datasets speedups shrink to 1.2–3× because the filter results are often empty.

---

## 3. Optimizer design

**Pipeline.**
1. Parse into an SSA IR.
2. Annotate each register: source table, row domain, type, nullability, sortedness, ordered/monotone.
3. Run the passes to a fixpoint.
4. Estimate cost with the `[doc: cycles.md#cost-table]` model.
5. Emit.

**Global guard:** if the estimated cost isn't lower, an intermediate result would grow, or any pass throws an exception, emit the input unchanged.

| Rank | Rewrite | Gain | Risk | Safety rule (§5) | Prototype evidence |
|---|---|---|---|---|---|
| 1 | Dead-code elimination + CSE | 5–25% | very low | S1 | `h_dce` honest, 0 false alarms |
| 2 | GATHER composition / sinking; gather only the columns that reach OUT | 20–50% on wide plans | low | S7 | q0001, q0004 |
| 3 | Filter first; run element-wise ops after filters (late materialization) | 4–8× on q0001/q0004/q0007 | low | S2, S6 | q0007 2596→637 **[M]** |
| 4 | Sort reduction: TOPK for SORT+slice, dead SORT before order-insensitive aggregates, SORT on `sorted` keys is identity | 5–20% | med | S4, S5 | q0001, q0004, q0007 |
| 5 | Filter pushdown below joins (one-sided, total predicates) | 30–70% on q0004-like plans | med | S2, S3 | q0004 |
| 6 | Constraint rewrites: always-TRUE predicates, exactly-one-match joins | small | med | S8 | q0001 |
| 7 | Join algorithm choice (HJOIN↔NLJOIN by cost; stats allowed here) | small | very low | — | `h_join_swap` honest; NLJOIN is cheaper when one side has ≤ ~5 rows |
| 8 | Idioms: self-join+aggregate → GROUP; rank via sort; semi-join de-dup | 2–47× | **high** | S3, S4, S9 | q0003, q0005, q0006 |

**Skip entirely:** arithmetic re-association, join reordering, anything that uses stats for correctness.
**Gate:** rank 8 is enabled only after 0 defects on NULL-, tie-, scale- and empty-table-heavy data.

---

## 4. Evaluator design (`./evaluate OPTIMIZER`)

1. **Corpus.**
   - Programs: the 8 examples, mutants of the examples, and generated programs from a type-checked template generator over the schema (scan/filter, 1–4 joins along `refs`, GROUP aggregates, SORT/TOPK/SLICE, string/date/arithmetic) with legacy bloat added. Keep a program only if the original succeeds and gives non-empty output on at least one dataset.
   - Data: `gen_data.py` style, constraint-respecting, adversarial, with literals harvested from the programs, all validated by `--schema`. Plus datasets designed to make originals error.
2. **Run.** One optimizer call per program, at most 4 in parallel so machine load can't cause a false "> 1 s". Then VM runs on all cores using the platform binary.
3. **Compare** using the rubric in §6.
   - Order: a data-flow pass over the original decides whether output order is specified (`eval-proto.py: output_ordered`).
   - Ties: compare rows tied on the sort keys as a multiset, by running an *instrumented* original that also outputs the sort keys (still to build).
4. **On a defect:** re-run once, save the repro (program, optimized program, dataset, diff) to `eval_out/`, then shrink it if time remains (stretch goal). Exit 1.
5. **Budget [M]:** 8.3 ms per run means 320 checks take 1.7 s. A watchdog at 100 s stops new work and reports the verdict so far.

### 4.1 Evaluation methods compared

| Method | How | Proves | Catches | False-alarm risk | Cost within 2 min | Use |
|---|---|---|---|---|---|---|
| **Run-and-compare (differential testing)** | run original and optimized on many datasets, compare outputs | that a defect exists (a counterexample); never that there is none | anything the data exercises: NULLs, ties, order, errors, scale | low, if the comparator rules are right | ~1.7 s per 320 checks **[M]** | **primary** |
| **Normalize-and-compare (syntactic)** | canonicalize both programs (rename registers, DCE, sort commutative ops) and diff them | equivalence only when they normalize to identical text | nothing, if any real rewrite happened | none, but almost always "unknown" | ms | fast path: identical after normalizing ⇒ skip running the VM |
| **Metamorphic testing (SQLancer TLP/NoREC, EMI)** | derive related programs or data, e.g. partition on `p` / `NOT p` / `p IS NULL`, add dead code, permute rows that are unsorted by the program | defects that need no reference output | NULL three-valued-logic bugs, order assumptions, stats-as-constraint bugs | low | moderate | data-side only: NULL partitions and row permutations in the generator |
| **Property checks** | invariants without a reference: `ncols` same, row count same for pure projections, VM limits, optimizer time | gross failures | crashes, timeouts, limit blow-ups | none | trivial | always on |
| **Mutation testing of the oracle** | seed bugs into fake optimizers; measure the kill rate | the *evaluator's* recall and precision | weak data, a lenient comparator | — | ~37 s for 19 fakes **[M]** | meta-eval gate on every evaluator change |
| **Translation validation / math proof (Alive2, CompCert)** | encode both programs symbolically under the constraints and ask an SMT solver whether they are equivalent | **equivalence on all data** | everything, within the encoded semantics | none, if the encoding is right | days to build; may be slow per query; semantics are large (NUM rounding, Unicode UPPER, 3-valued logic) | out of scope for 2–3 h; first item in the "few days" plan |
| **Bounded exhaustive (small-scope hypothesis)** | enumerate all tiny databases (e.g. ≤ 3 rows, small value domains) | equivalence on every database up to that size | most semantic bugs, which show up on tiny data | none | grows exponentially with columns and values; feasible for 1–2 tables | stretch goal: NULL/''/tie value domains on 0–3 rows |

**Decision:** run-and-compare is the verdict. Normalize-and-compare is a fast path. Metamorphic ideas shape the data generator. Mutation testing gates the evaluator. Proofs are deferred.

---

## 5. Safety rules: how a rewrite can produce wrong output (with doc citations)

| ID | Trap | Doc evidence | Probe **[M]** | Rule |
|---|---|---|---|---|
| S1 | **Adding an error.** Errors stop the program, and an optimized program that errors is a defect. Removing dead code can only remove errors, which is fine because "if the input errors, anything goes". | "Any error stops the program" `[doc: running.md#errors]`; dead `DIV x,0` still errors | F6, `b_dead_div0` caught (272) | Never add an op that may error. Deleting ops is always allowed. |
| S2 | **Data-dependent errors.** Type errors and DIV by 0 fire only on rows actually used, never on empty or all-NULL columns. | "Types are checked row by row ... whether a program fails can depend on its data" `[doc: instructions/README.md#element-wise-instructions]`; "DIV of NULL by 0 is NULL" (same section) | `DIV` after a `d≠0` filter OK, before it errors | An op may run only on a **subset** of the rows it originally ran on. Never push DIV/IDIV/MOD/DATEADD/overflow-prone ops or comparisons of mixed types above a filter. |
| S3 | **NULL keys: joins vs groups.** HJOIN never matches NULL keys (unless NULLEQ); GROUP puts NULLs together. | "A NULL key matches no key, unless ... NULLEQ" `[doc: instructions/joins.md]`; "NULL equals NULL" `[doc: instructions/grouping.md#group]` | `q0006.naive` caught (24), `b_nulleq` caught (56) | Any join↔group rewrite adds or keeps an explicit `NOT ISNULL(key)` filter. |
| S4 | **Order and ties.** SORT is stable, HJOIN output is ordered by (i, j), and groups are numbered by first appearance. | "Ties keep their input order" `[doc: instructions/sorting.md#sort-keys]`; "ordered by i then j" `[doc: joins.md]`; "groups are numbered from 0 in order of first appearance" `[doc: grouping.md#group-sets]` | `b_reverse` (172), `b_no_tiebreak` (19) | Preserve exact output order. Never swap join sides or reorder the input to GROUP/GFIRST/GMIN/GMAX. |
| S5 | **First-of-equals and NUM scale.** GMIN/GMAX return the first of equal values; GSUM uses the largest scale in the group; `1.0` and `1.00` print differently. | "the first of equals: of 1, 1.0 and 1.00, whichever comes first" `[doc: grouping.md#gmin-gmax]`; "1.0 and 1.00 are equal but print differently" `[doc: values.md#num-range]`; GSUM scale `[doc: grouping.md#gsum]` | F28, F5 | Keep the aggregate input order. Avoid identities that rescale (`x*1.000`, `x+0.0`): equal in value, but they change the printed text. |
| S6 | **Unicode changes length.** UPPER can change the character count, so UPPER and LEFT/SUBSTR don't commute. | "UPPER('straße') is 'STRASSE'" `[doc: strings.md#upper]` | `ß` in generator | Never reorder string ops relative to each other; only move them across filters and gathers. |
| S7 | **VM limits.** Join output counts toward limits; HJOIN/GROUP use up the work budget faster than their cycles suggest. | limits table `[doc: running.md#program-rules]` | 2M-row join takes 425 ms | No rewrite may grow any intermediate result beyond the original's. |
| S8 | **Constraints vs stats.** Constraints hold for every dataset; stats describe one. `check` doesn't imply `not_null`. Tables without a `key` may have duplicates. | "The constraints hold for every table set with this schema; the stats describe only this one" `[doc: running.md#schema-files]`; constraint table `[doc: running.md#constraints]` | `q0004.naive` (no key on customers) | Correctness may use only key, not_null, refs, check and sorted. Stats are used only for cost. |
| S9 | **`sorted` covers stored order only.** It survives IDX, ascending GATHER and the left side of a join, but not the right side of HJOIN, GROUP output, or a SORT on other keys. | "the rows are stored in ascending order ... as ASC NF sorts them" `[doc: running.md#constraints]` | q0001/q0005 identity SORT | Drop a SORT only if its keys are a prefix of `sorted` ASC NF *and* the index is proven ascending from LOAD. |
| S10 | **Literal-only ops and OUT rules.** An element-wise op needs at least one register operand; OUT must be the last instruction and the only OUT. | `[doc: instructions/README.md#element-wise-instructions]`, `[doc: running.md#program-rules]` | F23, F25 | Constant folding must not produce a literal-only op; the emitter always ends with exactly one OUT. |

---

## 6. Eval rubric

```json
{
  "outputs": {
    "O1_ncols": "equal; optimized must succeed whenever original succeeds",
    "O2_rows": "in order if original specifies order (SORT/TOPK reaches OUT), else multiset",
    "O3_numbers": "JSON int or string matching ^-?\\d+(\\.\\d+)?$ -> Decimal, |a-b| <= 1e-6*max(|a|,|b|)",
    "O4_other_values": "NULL==NULL only; STR/DATE exact (no Unicode normalization); BOOL never equals INT",
    "O5_skip": "original errors -> pair skipped, not a defect",
    "O6_limits": "optimizer > 1 s, crash, empty output, or optimized VM error -> defect"
  },
  "programs": {
    "P1_cycles": "speedup per (program, dataset) + geomean",
    "P2_instructions": "count before/after",
    "P3_peak_register": "never larger than original",
    "P4_optimizer_time_max_s": "< 1.0",
    "P5_regressions": "optimized cycles > original on any dataset (reported, target 0)"
  },
  "evaluator": {
    "E1_recall": "caught / buggy fakes (seeded + held-out), target 100%",
    "E2_false_alarms": "flagged honest fakes, target 0 over 10 seeds",
    "E3_wall_time_s": "< 120 (target < 60 at -j4)",
    "E4_determinism": "same seed -> identical report"
  }
}
```

---

## 7. Unclear rules and the assumptions we make

How we handle each: pick the **default that can't produce a false alarm or a wrong optimization**, encode it as a check, log it, and escalate only if the choice changes more than 20% of results.

| # | Unclear point | Options | Default | Why | Encoded in |
|---|---|---|---|---|---|
| Q1 | When does a program "specify" order? Do tied rows count? | (a) whenever SORT/TOPK reaches OUT, strict; (b) the same, but tied rows compared as a multiset; (c) never | **(b)**; today (a) | strict order flags legal reorders of ties | `output_ordered`; tie handling still to build |
| Q2 | `"2.0"` vs `"2.00"`; INT `2` vs NUM `"2.0"` | text equal / numeric equal | numeric equal | "numbers within 1e-6" | `tricky_checks.py` CMP |
| Q3 | STR `'1.0'` vs `'1.00'` print like numbers | infer column types / treat as numbers | treat as numbers (documented gap) | the output JSON has no types | known gap; fix by inferring types |
| Q4 | Tolerance on INTs (`10000000` vs `10000001` passes) | apply to INTs / exact for INTs | apply (spec says "numbers") | follow the spec literally | CMP check |
| Q5 | Near zero (`0` vs `1e-7`) | relative only / add an absolute epsilon | relative only | spec says relative; correct optimizers don't change arithmetic | CMP check |
| Q6 | Ties at a TOPK/SLICE/GFIRST cut-off | fail / warn | warn once tie handling is built | a correct optimizer may choose another tied row | still to build |
| Q7 | Optimizer may use `bin/minivm`? | yes / no | no | the grader may not ship it next to `./optimize` | optimizer design |
| Q8 | Can stats be used? | correctness / cost only | cost only | `[doc: running.md#schema-files]` | S8 |
| Q9 | Optimized program hits a VM limit where the original didn't | defect / skip | defect | the program "gives a different result" (none) | O6 |
| Q10 | How is "faster" measured? | cycles / wall time | cycles | that's what the VM reports | P1 |

---

## 8. Working model: how the agents talk

**Roles.**
- **Orchestrator** (main session): owns the plan and writes task cards; never writes optimizer code.
- **Builder** subagent: implements one rewrite per task.
- **Red-team** subagent: sees only the spec, docs and rubric. It writes fake optimizers and adversarial data, and never sees the optimizer code.
- **Checker:** the `./evaluate` script, not an LLM.
- **Reviewer** subagent: fresh context, for rank ≥ 5 rewrites. Its job: "name the dataset that breaks this".
- **Human:** approves at checkpoints and decides open questions.

```
human ──approve/decide──▶ ORCHESTRATOR ──task.json──▶ BUILDER ──commit + build.json──▶ CHECKER(./evaluate)
  ▲                          │  ▲                                                        │
  └────escalation.json───────┘  └──────verdict.json ◀── REVIEWER ◀── report.json ◀──────┘
                                 RED-TEAM (spec only) ──fakes + data──▶ CHECKER (meta-eval)
```

**Rules.**
- Agents communicate only through **files**, never prose summaries.
- Every message is a JSON document with a schema version.
- Prose goes only in a `notes` field.
- Files live under `runs/<iteration>/`.

```json
// task.json  (orchestrator -> builder)
{"v":1,"task_id":"T07","goal":"sort reduction: SORT+IDX+SLICE -> IDX+TOPK",
 "rewrite_rank":4,"safety_rules":["S4","S5"],"files_allowed":["optimizer/passes/sort.py","tests/cases/medium/*"],
 "done_when":{"defects":0,"geomean_min":1.0,"opt_time_max_s":0.8},"budget":{"wall_min":15,"tokens_k":200}}
```
```json
// build.json  (builder -> checker)
{"v":1,"task_id":"T07","commit":"abc1234","pass":"sort_reduction","tests_added":["medium/topk_after_filter.mini"],
 "claims":[{"rule":"S4","why":"TOPK = first n of the same stable SORT [doc: sorting.md#topk]"}],"notes":""}
```
```json
// report.json  (checker -> everyone; also appended to notes/runs.jsonl)
{"v":1,"commit":"abc1234","seed":0,"checked":320,"skipped":0,"defects":0,"wall_s":1.7,
 "geomean_speedup":2.39,"per_program":[{"name":"q0007","speedup":4.08,"status":"OK"}],
 "meta":{"buggy_caught":11,"buggy_total":11,"false_alarms":0},
 "defect_repros":[]}
```
```json
// verdict.json  (reviewer -> orchestrator)
{"v":1,"commit":"abc1234","decision":"keep|revert|needs_test",
 "counterexample":{"program":"...","dataset":"...","expected":"...","got":"..."},"rules_checked":["S4"]}
```
```json
// escalation.json  (orchestrator -> human)
{"v":1,"question_id":"Q1","options":["strict","tie-multiset"],"recommended":"tie-multiset",
 "impact":"3/320 checks change verdict","blocking":true}
```

**Git discipline.**
- One rewrite per commit.
- A red build gets `git revert`, never a reset or amend.
- Tag green checkpoints `cp1`…`cp5`.
- Each defect becomes a regression in `tests/regressions/`, replayed first on every run.

**Independence.** `evaluate/` never imports `optimizer/`; a grep check enforces this. Only the CLI and `bin/minivm` cross the boundary.

---

## 9. Stopping criteria

```json
{
  "success": ["0 defects on 3 seeds", "meta-eval: 100% buggy caught (seeded + held-out), 0 false alarms",
              "geomean >= 2x on examples, > 1x on held-out programs", "max optimizer time < 1 s", "evaluate < 60 s"],
  "no_more_improvement": "2 consecutive iterations with < 3% geomean gain -> move to next rank or stop",
  "budget": "user time 2h45m or token cap reached -> ship last green tag",
  "ask_human": ["a rule depends on Q1-Q10", "a defect not explained in 2 attempts",
                "a fix would drop > 20% of the gain", "any destructive git action"],
  "hard_rule": "any defect = red build; revert or disable the rewrite before anything else"
}
```

---

## 10. Failure modes

| Failure | Detection | Prevention / fix |
|---|---|---|
| Rewrite breaks NULL semantics | NULL-heavy data; `b_nulleq`, `q0006.naive` | S3 |
| Rewrite introduces an error | O6; `b_dead_div0` | S1, S2 |
| Lost order or ties | order-aware comparator; `b_reverse`, `b_no_tiebreak` | S4 |
| Evaluator too lenient (weak data) | meta-eval misses; `BASELINE_MISSED` in `check.py` | harvest literals; more rows than every TOPK limit; ties; empty tables |
| Evaluator too strict (false alarm) | honest fakes (`h_*`) must pass | Q1–Q5 defaults; tie handling |
| Comparator type confusion | `tricky_checks.py` CMP | strict numeric format; BOOL ≠ INT (both bugs found and fixed **[M]**) |
| Using stats for correctness | generator deliberately violates stats | S8; lint check |
| VM limit blow-up | P3, O6 | S7 cost check |
| Optimizer > 1 s on 20k-line programs | stress test | linear passes; deadline then fall back |
| Evaluator > 2 min | wall time in report | platform binary, watchdog, limits on corpus size |
| Overfitting to the 8 examples | held-out generated programs | general passes; no matching on names |
| Shared bug in optimizer and evaluator | independence grep check | separate parsers |

---

## 11. Test suite, runners, logs, timeline, submission

**Test suite.**
- **Easy:** one rewrite each, e.g. DCE, CSE, SORT on a `sorted` table, an always-TRUE predicate, join swap, empty tables.
- **Medium:** q0007, q0008, q0002; pushdown through one join; TOPK; string ops after a filter.
- **Complex:** q0001, q0004, q0005, q0003, q0006; generated 3–4-join plans; a 20k-instruction stress program.
- **Data:** `gen_data.py` small/medium/large, plus `make_adv_data.py`.

**Runners.**
- `prototype_code/run_all.sh` today (~1 min).
- The real build gets `run_tests.sh` (tier 1, < 15 s) and `run_eval.sh` (tiers 2/3).
- Each prints the §6 report and appends to `notes/runs.jsonl`.

**Progression log.** `notes/PROGRESSION_LOG.md`, one entry per iteration:

```json
{"iter":7,"tried":"...","result":{"defects":0,"geomean":2.4},"learned":"...","decision":"keep|revert"}
```

**Timeline (2–3 h of user time).** Prototyping is already done (≈ CP0).

| Time | Work | Checkpoint |
|---|---|---|
| 0:00–0:25 | `./evaluate`: port eval-proto, add tie handling and repro saving; independence grep check | CP1: meta-eval 11/11, 0 false alarms |
| 0:25–0:50 | `./optimize` skeleton: parse → IR → emit round trip, fallback guard | CP2: identity round trip, 0 defects |
| 0:50–1:40 | Rewrite ranks 1–4 | CP3: 0 defects, geomean ≥ 2× on examples |
| 1:40–2:15 | Ranks 5–7, plus the program generator for held-out tests | CP4: 0 defects on 3 seeds |
| 2:15–2:40 | Rank 8 idioms only if green | CP5 |
| 2:40–3:00 | Submission packaging | done |

**Cut order:** idioms → program generator → join choice → filter pushdown.
**Never cut:** the evaluator, meta-eval, or the fallback guard.

**Submission checklist.**
- Git history from the start. The binaries have already been purged, and `minivm-takehome/bin/` is ignored.
- The one-pager PDF is still tracked. It's a binary file, so decide whether to remove it.
- Raw Cortex Code session files (`~/.snowflake/cortex/conversations/...`), copied unmodified to `ai-sessions/`.
- Models and spend in `notes/AI_USAGE.md` (claude-opus-5-5 via Cortex Code).
- The "few days" plan below.

**A few days with unlimited compute.**
1. Translation validation: an SMT encoding of MiniVM under the constraints (Alive2-style) to prove each rewrite.
2. Bounded-exhaustive checks of tiny databases.
3. An equality-saturation (e-graph) optimizer with a calibrated cost model, plus cost-based join ordering.
4. A coverage-guided program and data fuzzer, with delta-debugging reduction.
5. Held-out red-team agents writing mutants the builders never see.
6. Large-scale parallel evaluation in the cloud.
