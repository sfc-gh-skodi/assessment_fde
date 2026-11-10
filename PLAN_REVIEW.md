# Plan Review

## Findings

### 1. Tie handling is still a correctness gap in the evaluator

The current plan still treats the evaluator as close to production-ready while tie handling is explicitly unfinished. `BUILD_PLAN.md:121` says tied rows should be compared as a multiset using an instrumented original, but `prototype_code/evaluator_agent/eval-proto.py:30` still compares ties in order. That means a correct optimizer that preserves the sort keys but reorders tied rows can be flagged as defective.

Impact:
- False alarms during evaluation.
- Overstated confidence in the current meta-eval results, since all example programs happen to be order-specified and the current fake optimizers do not exercise legal tie reordering.

Fix applied to the plan:
- Reframed tie-aware comparison as a blocking production requirement, not a nice-to-have.
- Downgraded claims that the current evaluator fully proves order correctness.

### 2. Numeric-looking strings are still an unresolved type ambiguity

The current prototype intentionally compares printed numeric-looking strings numerically because the VM output JSON omits type information. This is documented in `BUILD_PLAN.md:196` and exercised in `prototype_code/evaluator_agent/tricky_checks.py:52-54`. The issue is that a string bug can hide behind numeric equivalence if the evaluator does not recover output types.

Impact:
- False negatives for string-preservation bugs.
- The current evidence for comparator correctness is weaker than the plan implies.

Fix applied to the plan:
- Marked output-type recovery or typed comparison as required before treating the evaluator as a final correctness gate.
- Tightened the plan language so the current prototype is described as a useful draft, not a finished oracle.

### 3. Output-order detection is heuristic and should not be treated as a proven semantic analysis

`prototype_code/evaluator_agent/eval-proto.py:104-141` infers whether output order is specified using a custom data-flow pass. The logic is thoughtful, but it is still a heuristic model of the language, especially across joins, `GROUP`, `GFIRST`, `GATHER`, and monotone index propagation.

Impact:
- A mistake in order inference can create either false alarms or misses.
- Several plan sections treat this analysis as settled when it is still a prototype.

Fix applied to the plan:
- Narrowed the claim from “the evaluator compares in order when the original specifies it” to “the production evaluator must prove or conservatively detect when order is specified.”
- Added explicit validation of the order-analysis logic as part of the evaluator build-out.

### 4. The runtime budget is optimistic once the missing evaluator features are added

The plan cites `1.7 s` for 320 checks (`BUILD_PLAN.md:123`) and uses that as a comfortable basis for the 2-minute budget. That number comes from the current prototype over 8 example programs and 40 datasets. It does not include:
- held-out generated programs,
- tie-aware instrumentation,
- repro capture,
- shrinking,
- multi-seed runs,
- datasets that intentionally force original-program errors.

Impact:
- Underestimates total evaluator wall-clock cost.
- Risks building a plan that cannot meet the stated 2-minute SLA once the missing work is implemented.

Fix applied to the plan:
- Separated prototype timing from production timing.
- Added phased corpus and budget controls so the evaluator can stay within SLA by prioritizing regressions, examples, and a bounded held-out sample.

### 5. Scaling coverage is too far from the documented MiniVM limits

MiniVM allows up to 20,000 instructions, 10,000 rows per table, 4,000,000 values in one register, and 64,000,000 total register values (`minivm-takehome/docs/running.md:13-21`). The current generator sizes in `prototype_code/optimizer_agent/gen_data.py:28` top out at 600-2500 rows, and the plan does not yet define concrete near-limit stress cases.

Impact:
- Optimizer SLA risk is under-tested.
- Rewrites that appear safe on medium data may still trigger VM limits or large intermediate explosions near the real boundaries.

Fix applied to the plan:
- Added explicit near-limit stress testing for program size, row counts, register pressure, and worst-case join/group fan-out.
- Added a requirement to keep evaluator corpora separate from dedicated scale stress tests.

### 6. The global “no intermediate growth” guard is not operationally defined

`BUILD_PLAN.md:95` says the optimizer should fall back if “an intermediate result would grow,” but the plan does not define a general way to prove that across arbitrary rewrites. For some rewrites this is straightforward; for others it is not.

Impact:
- The guard sounds stronger than the implementation can realistically guarantee.
- It risks becoming hand-wavy instead of enforceable.

Fix applied to the plan:
- Replaced the blanket wording with rewrite-specific cardinality and ordering preconditions.
- Kept the conservative fallback, but only where the optimizer can actually justify it from syntax and constraints.

### 7. The plan overstates what the current prototype corpus proves

The current prototype coverage is strong for the 8 examples plus generated datasets, but `prototype_code/README.md:68-72` already states the major missing areas: no generated program corpus yet, no original-error datasets yet, and no tie-tolerant comparison yet.

Impact:
- The current plan’s confidence level is higher than the evidence supports.

Fix applied to the plan:
- Adjusted the wording to separate “prototype evidence” from “production gate requirements.”

## Plan Changes Made

### Correctness and evaluator changes

- Marked tie-aware comparison as a required evaluator milestone before production use.
- Marked typed output disambiguation as required to close the numeric-string ambiguity.
- Changed the order-analysis claim from definitive to conservative/validated.

### Time and scaling changes

- Split prototype timing from projected production timing.
- Added phased evaluation budgets and corpus caps.
- Added explicit stress tests near MiniVM instruction, row-count, and register limits.

### Rewrite-safety changes

- Replaced the vague intermediate-growth guard with rewrite-specific preconditions.
- Clarified that constraints can justify correctness, while stats can justify cost only.

## Net Assessment

The plan is strong on semantic traps and on using adversarial differential testing as the main evaluator strategy. The main weaknesses were not conceptual; they were around overstating prototype maturity, under-specifying scale testing, and leaving a few evaluator correctness gaps as “still to build” even though the rest of the plan treated them as nearly done.

After the edits, the plan is more defensible: it makes fewer claims than the current prototype can actually support, and it adds the missing checkpoints needed to keep correctness and runtime requirements honest.

## Prioritized Prototype Fix List

### P0: Required before trusting the evaluator as the main gate

1. Implement tie-aware comparison in `prototype_code/evaluator_agent/eval-proto.py:243-246`.

Why:
- Right now the evaluator first checks multiset equality and then, when `ordered` is true, requires exact row order.
- That incorrectly rejects legal reorderings among rows tied on the final sort keys.

Concrete fix:
- Instrument the original program to emit the effective output sort keys, or otherwise recover the key groups at `OUT`.
- Compare rows group-by-group: exact key-group order, multiset equality within each tied group.

2. Stop treating all numeric-looking strings as numbers in `prototype_code/evaluator_agent/eval-proto.py:148-177` and `prototype_code/optimizer_agent/cmp.py:32-63`.

Why:
- This is the main typed-output ambiguity.
- The prototype explicitly allows `'1.0'` and `'1.00'` to compare equal even when they may be strings.

Concrete fix:
- Add output-type inference from the producing instructions, or record operand provenance in an instrumented run.
- Keep the current numeric comparison only where the output column is known to be INT/NUM.

3. Save full repro artifacts on evaluator failure instead of only printing summary lines in `prototype_code/evaluator_agent/eval-proto.py:299-308`.

Why:
- The plan says defects should save program, optimized program, dataset, and diff, but the prototype currently only prints a defect summary.
- That slows down debugging and weakens regression capture.

Concrete fix:
- Write a per-defect directory containing original program, optimized program, dataset path or copy, raw outputs, and comparison reason.

### P1: High-value correctness and maintainability fixes

4. Replace the heuristic order analysis in `prototype_code/evaluator_agent/eval-proto.py:104-141` with a more conservative model.

Why:
- The current logic is smart but brittle. A false positive here becomes a false evaluator defect.

Concrete fix:
- Prefer “unordered unless proven ordered” over trying to propagate too much monotonicity.
- Add targeted tests for every propagation rule through `HJOIN`, `GROUP`, `GFIRST`, `GATHER`, `IDX`, and overwritten registers.

5. Unify comparator behavior between `eval-proto.py` and `cmp.py`.

Why:
- `eval-proto.py` and `cmp.py` do not implement the same comparator. `cmp.py` uses `Decimal(v)` for any string parseable as decimal, while `eval-proto.py` restricts to MiniVM-printed numeric forms via `NUM_TEXT`.
- This can create inconsistent local results between the helper scripts and the evaluator.

Concrete fix:
- Extract one shared comparator module and use it from both scripts.

6. Fix the CLI parsing bug around `--data` in `prototype_code/evaluator_agent/eval-proto.py:261-264`.

Why:
- The docstring advertises `--data DIR_OR_FILE ...`, but the implementation just strips the literal token `--data` and treats the rest positionally.
- That is fragile and can silently accept malformed invocation.

Concrete fix:
- Use `argparse` and model `--data` as a repeatable argument.

7. Add explicit tests for original-error datasets and the skip path.

Why:
- The current plan and README both admit this path is untested.
- `eval-proto.py:235-237` relies on it for the rubric.

Concrete fix:
- Add datasets that trigger mixed-type comparisons, divide-by-zero on actually used rows, and overflow paths in originals.

### P2: Scale, runtime, and tooling fixes

8. Add near-limit stress generators beyond `prototype_code/optimizer_agent/gen_data.py:28`.

Why:
- Current sizes do not approach the MiniVM limits.
- This leaves optimizer SLA and evaluator throughput under-tested.

Concrete fix:
- Add dedicated generators for:
  - 20k-instruction programs
  - near-10k-row tables
  - high-fanout joins
  - wide/long-string register pressure

9. Remove side-effecting baseline capture from `prototype_code/optimizer_agent/check.py:74-83`.

Why:
- On first failure it silently copies the current bad candidate to `qNNNN.naive.mini`.
- That is convenient during prototyping, but dangerous for repeatable evaluation and easy to misuse.

Concrete fix:
- Make baseline capture opt-in with a flag, or write to a separate quarantine path.

10. Make `run_all.sh` less lossy as a verification harness.

Why:
- `prototype_code/run_all.sh:7-17` pipes several steps through `tail -1` and masks failures for some cases with `|| true`.
- That is fine for a dashboard-style summary, but bad for root-cause debugging.

Concrete fix:
- Keep the summary output, but also preserve full logs per step.

### Clarification added during review

- The plan text about relative tolerance on integers has been clarified. `1e-6` is `0.000001`, but the comparator uses `abs(a - b) <= 1e-6 * max(abs(a), abs(b))`, so a pair like `10000000` vs `10000001` passes because the allowed error at that magnitude is about `10`, not `0.000001`.

### Recommended execution order

1. `eval-proto.py`: tie handling, typed comparison, repro saving, `argparse`.
2. Shared comparator extraction used by both `eval-proto.py` and `cmp.py`.
3. Order-analysis tightening plus targeted tests in `tricky_checks.py`.
4. Error-path datasets and scale-stress generators.
5. `check.py` and `run_all.sh` cleanup so the workflow is repeatable and easier to debug.
