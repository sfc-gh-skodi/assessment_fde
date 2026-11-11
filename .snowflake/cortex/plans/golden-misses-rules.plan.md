# Plan: cover golden cases 06, 03, 01 quickly and safely

## Why this is faster than the earlier estimate (2.5–4 h → about 1.5–2 h)

1. **Smaller, general rules instead of three bespoke ones.** Two facts from the docs remove most of the risk I'd flagged:
   - `IDX` keeps only TRUE positions and drops FALSE and NULL alike (`instructions/columns.md#idx`). So in front of `IDX`, any BOOL `x` gives `OR(x, NOT x)` ≡ `NOT ISNULL(x)`: TRUE→TRUE, FALSE→TRUE, NULL→dropped either way. This needs no comparison or literal analysis.
   - Case 01 keeps row order. `HJOIN` pairs come "ordered by `i` then `j`" (`joins.md`), and groups are numbered "in order of first appearance" (`grouping.md`). So the groups over `a` are the non-NULL-key rows in ascending order, which is exactly what `IDX(NOT ISNULL k)` gives. The "multiset only" guard isn't needed, and neither is the riskiest condition from the old estimate.
2. **Reuse what's already there.** `analyze.py` already tracks `nullable`, `column`/`table`, `type` and `ordered` per register. `passes.py` already has `_uses`, `_defs`, `_fresh`, `FLIP`, DCE and CSE, so each rule only rewrites. DCE deletes the leftovers, and the cost guard in `main.py` rejects anything not cheaper.
3. **Tests already exist.** Each burnt golden case already has the original, a `legal.mini` (target), a `trap.mini` (buggy twin) and expected outputs for d0–d3. We move the three burnt cases into the public tests (as `FUTURE_PLAN.md` loop 3 says) instead of writing new ones.

## Facts confirmed from the docs

| Fact | Source |
|---|---|
| Comparisons, `NOT`, `AND`/`OR` give NULL on a NULL operand (except `FALSE AND NULL`=FALSE, `TRUE OR NULL`=TRUE). `ISNULL` is never NULL. | `instructions/logic.md` |
| `IDX` drops FALSE and NULL | `instructions/columns.md#idx` |
| Cost: `GT`/`NOT`/`OR`/`ISNULL` are each 1 per element (+4 base); comparisons add the bytes of the shorter string | `cycles.md` |
| `check` bounds only non-NULL values, inclusive; `null` leaves a side open; INT/NUM/DATE only. `key` and `not_null` mean never NULL. | `running.md#constraints` |
| `HJOIN`: a NULL key matches nothing (no NULLEQ); keys are compared as in Ordering; pairs are ordered by i then j | `instructions/joins.md` |
| `GROUP`: NULL equals NULL; keys are compared as in Ordering (INT/NUM mix); unequal types error, like HJOIN | `instructions/grouping.md` |
| `GMAX`/`GMIN` return the first of equals, so the row order inside each group must be kept (it is: ascending in both forms) | `grouping.md#gmin-gmax` |
| Output order matters only when a SORT/TOPK reaches OUT | `evaluator/compare.py` O2; `analyze.py` `ordered` |

## Rules (one function each in `optimizer/passes.py`, added to `PASSES` before `cse, dce`)

### R5 `idx_bool`: boolean simplification where only `IDX` reads the result (case 06)
Applies only when every use of the BOOL register is `IDX` (check via `_uses`).
- `OR(x, NOT x)` (either order) → `NOT ISNULL(x)`
- `AND(x, NOT x)` → stays (rare, skip)

### R6 `isnull_push` (case 06, second half)
`ISNULL(E(a, lit...))`, where `E` is a default-NULL element-wise op (comparisons, arithmetic, string ops; **not** `IS`, `ISNULL`, `NVL`, `IF`, `NULLIF`, `NULLIFE`, `AND`, `OR`) with exactly one register operand and only non-NULL literals → `ISNULL(a)`. The dropped `E` could only add errors (e.g. a type mismatch), and dropping errors is allowed. Together with R5 this turns the case 06 program into `legal.mini`.

### R7 `constraint_fold` (case 03)
Fold `GE/GT/LE/LT col, lit` (and the flipped forms via `FLIP`) to TRUE when **both** of these hold:
- `info[col]` is a column: `column` set, still the column's values (LOAD/GATHER/SLICE), and in `key ∪ not_null`.
- The check bounds `[lo, hi]` imply it: `GE c`: lo ≥ c; `GT c`: lo > c; `LE c`: hi ≤ c; `LT c`: hi < c. An open bound (`null`) can't prove its side.

Literal handling: compare INT and NUM as `Decimal`. A DATE literal `#YYYY-MM-DD#` against an ISO bound string is compared as a date. If the types don't match, or the literal is a STR, don't fold.

Folding means replacing the register with `TRUE` in its users, and then:
- `AND(TRUE, x)` / `AND(x, TRUE)` → x
- `OR(FALSE, x)` → x
- `OR(TRUE, x)` → keep (rare)

If a folded register would end up as the direct input of `IDX` or `OUT`, leave the original instruction (there is no cheap "all positions" op to swap in).

### R8 `selfjoin_group` (case 01)
Match:
```
HJOIN a, b, k, k            ; same register both sides, no NULLEQ, a != b
GATHER s_b, s, b            ; every use of b is GATHER(_, b) (any number)
GROUP g, a                  ; a's only uses: this GROUP and GATHER(_, a, f)
AGG  m, g, s_b              ; g's only uses: GFIRST f + aggregates over b-gathered columns
GFIRST f, g                 ;   AGG in {GMAX, GMIN, GSUM, GCOUNT, GCOUNTV}
GATHER r, a, f              ; r = the representative row i
```
Emit:
```
ISNULL kn, k ; NOT kk, kn ; IDX j, kk ; GATHER kj, k, j ; GROUP g2, kj ; GID gi, g2
for each AGG over GATHER(s, b):  GATHER sj, s, j ; AGG m2, g2, sj ; GATHER m, m2, gi
r := j                      ; replace every use of r with j
```
Why it's equal: the output rows are the non-NULL-key rows in ascending order in both forms. Each aggregate covers the same rows (same key, non-NULL) in the same ascending order, so the "first of equals" result is the same too. GROUP and HJOIN raise the same comparison errors.

Refuse the rewrite on any other use of `a`, `b`, `g` or `f`, or when NULLEQ is given (then NULL keys would match).

## Buggy twins (go into `tools/fakes.py`; the evaluator must catch each one)
- `b_or_not_true`: `OR(x, NOT x)` → TRUE (the case 06 trap)
- `b_check_nullable`: fold the check on a nullable column (the case 03 trap)
- `b_selfjoin_keep_null`: self-join → `GROUP k` without the NULL filter (the case 01 trap)
- `b_isnull_drop_operand`: R6 applied to a two-register op (forgets the second operand's NULLs)

## Steps
1. **Move the burnt cases into the public tests.** Copy cases 01, 03 and 06 (program, schema, data d0–d3, expected) into `tests/regressions/`, which `./evaluate` already reads. Note in `golden_heldout/README.md` that they are burnt.
2. **R5 + R6** (case 06). After the change, check that `./optimize` on the case 06 program produces the `legal.mini` shape, and that `bin/minivm` output matches expected on d0–d3.
3. **R7** (case 03), with small checks on INT, NUM and DATE bounds, open bounds and flipped operands.
4. **R8** (case 01). Check the output matches expected on d0–d3, including row order (the expected files are ordered).
5. **Buggy twins.** Add the 4 fakes and run `tools/meta_eval.py`. Every new fake must be caught, with no false alarms on the honest fakes. If one slips through, fix the evaluator before moving on.
6. **Full gate.** Run `python3 tools/bench.py ./optimize -q` (0 defects, no tier slower) and `./evaluate ./optimize` on 3 seeds (0 defects). Then run the stress cases to confirm the optimizer stays under its deadline.
7. **Log and commit.** One commit per rule, a plain-English row per rule in `progress.md`, and a re-run of `run_golden.py`. Report the score with 01, 03 and 06 marked as burnt, so the headline doesn't overclaim.

## Expected result
- Held-out geomean ≈ 0.730 → ≈ 0.63, if our output costs what `legal.mini` costs. Cases 01, 03 and 06 no longer count as unseen.
- No new defects anywhere. Every rule is guarded, and the cost guard plus the "print the input unchanged" fallback remain.

## Risks and how we handle them
- **R8 matches too much.** The use-checks are strict, any extra use refuses the rewrite, and the twin and evaluator back it up.
- **The cost model mis-scores a rewrite.** `main.py` rejects it, and we compare cycles from `bin/minivm` with the estimate during step 4.
- **The R7 literal parse is wrong for some type.** We don't fold on a type mismatch or when unsure.
