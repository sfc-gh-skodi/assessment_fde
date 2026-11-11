# What I would do with a few days and unlimited compute and tokens

## Where things stand

- **Optimizer** (`optimizer/`): parse → SSA → annotate → passes to a fixpoint → cost check → emit, falling back to the input on any doubt. Passes: DCE, normalised CSE, GATHER composition, filter-first, sorted-SORT → IOTA, order-free SORT removal, NLJOIN → HJOIN. Suite speedup 1.30×, `./evaluate` speedup 1.75×, 0 defects (`progress.md`).
- **Evaluator** (`evaluator/`, `./evaluate`): differential testing on generated legal data and generated legacy-style programs, compared by type, order and ties. Meta-eval: 36/36 seeded bugs caught, 0/17 false alarms (`runs/meta_report.md`).
- **Held-out check** (a 10-case trap set built outside the build session; not in this package): 10/10 correct, geomean cycles ratio 0.730. Three cases were left untouched (ratio 1.000): self-join → GROUP with NULL keys, check-constraint folding on a nullable column, and `x OR NOT x` under three-valued logic. All three have known legal rewrites.

The pattern so far: correctness is solid, and the remaining speed is in **NULL-aware algebraic rewrites** and **multi-instruction idioms**. The approach is to keep the evaluator as the hard gate and widen the optimizer, without letting it learn the test set.

## Plan

### 1. Make correctness evidence stronger before adding speed
- **Spend compute on the evaluator.** Use many more seeds, larger and adversarial datasets (all-NULL columns, empty tables, duplicate keys, `''` vs `'  '`, values at check bounds, Unicode), and minimise every failure automatically to the smallest program and data that still fails.
- **Grow the trap corpus continuously.** An agent writes plausible-but-wrong rewrites (like `trap.mini`) and plausible-and-legal ones (like `legal.mini`) for each opcode family. Each trap becomes a seeded-bug fake in `tools/meta_eval.py`, and the evaluator must keep 100% recall and 0 false alarms.
- **Add a symbolic check on the side.** Encode the per-row semantics of the element-wise and filter ops (three-valued logic, NULL propagation, typed comparisons) in an SMT solver and prove small rewrites equivalent. Random testing stays the gate; proofs cover the corners random data misses.

### 2. Widen the optimizer with general rules, not cases
- **A NULL-aware predicate simplifier.** It tracks, for each boolean register, which values it can take (TRUE/FALSE/NULL) and which columns its NULL comes from. That covers `x OR NOT x` → `NOT ISNULL`, folding comparisons that `not_null` + `check` guarantee, AND/OR identities, and redundant IS NULL tests, in one pass.
- **Idiom rewrites with explicit guards:**
  - self-join + GROUP → filter NULL keys + GROUP/GMAX/GID
  - SORT+SLICE → TOPK
  - join elimination when keys, refs and not_null say it is safe
  - pushing projections through joins

  Each guard is written from the docs, and gets one legal test and one trap test before it lands.
- **Cost-model calibration.** Fit `optimizer/cost.py` against measured `bin/minivm` cycles on thousands of generated programs, so the "only if cheaper" check stops refusing good rewrites and stops accepting marginal ones.
- **Search instead of a fixed pass order.** Use equality saturation (e-graphs) or beam search over rewrite orders, extracting the cheapest program under the calibrated cost model, with a time limit and the existing fallback.

### 3. Use agents in parallel, with roles kept apart
- **Builder agents** each own one rule family in a branch, and never see the held-out set.
- **Red-team agents** write traps and adversarial data against the builders' rules.
- **Reviewer agents** (fresh context) check each rule's guard against the docs before merge.
- A **held-out set that keeps rotating.** Freeze a new hidden set every round. When a case gets studied, move it into the public suite and write a replacement, so the headline number keeps measuring generalisation.

### 4. Gates for every merge
- 0 defects on `./evaluate` (full, multiple seeds), the suite, and every trap.
- Meta-eval recall 100%, false alarms 0.
- Speedup is not worse on any suite category; optimizer time stays under its deadline.
- One commit per rule, with an ELI5 row in `progress.md`.

## What I would not do
- Hard-code outputs for known programs, or replay stored answers. That would improve the held-out number while proving nothing about unseen programs.
- Use table statistics for anything except cost. Stats come from friendly data, and the traps show that rules relying on them break on legal data.
