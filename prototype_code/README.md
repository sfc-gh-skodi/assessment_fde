# prototype_code: quick experiments before the real build

Throwaway-quality prototypes. They test the ideas in `../BUILD_PLAN.md` against real
`bin/minivm` runs before we build `./optimize` and `./evaluate`. Python 3 standard library
only. All paths are relative to each script, so they run from any directory.

```sh
prototype_code/run_all.sh        # regenerate data + run every check (~1 min)
```

Generated data (`optimizer_agent/data/`) is git-ignored. It is rebuilt byte-for-byte from
fixed seeds by `run_all.sh`, or by the two generator scripts below.

## Files

### `optimizer_agent/`: hand-optimized programs and the data that tests them
| File | What it does | Run |
|---|---|---|
| `qNNNN.opt.mini` | Hand-optimized version of each of the 8 example programs. A header comment says which constraint or semantic rule each rewrite relies on. | input to `cmp.py`, `check.py`, `hand_opt.sh` |
| `qNNNN.naive.mini` | **Known-bad** fast version of each example: the mistake a naive optimizer would plausibly make, e.g. dropping NVL on a nullable column, de-duplicating a table with no key, or running TOPK before the filter. Used as baselines that the tests must catch. | input to `check.py`, `naive_opt.sh` |
| `cmp.py` | Runs two programs on the same data. Prints cycles, speedup and MATCH / MISMATCH / SKIP / OPT_ERROR; exits 1 on a defect. | `cmp.py ORIG OPT [DATA...]` or `cmp.py --all [DATA...]` |
| `check.py` | Runs every `qNNNN.opt.mini` against every dataset in parallel and reports matches and speedup by data size. On a failure it saves the program as `qNNNN.naive.mini` and writes `failures/qNNNN.txt`. It re-checks every naive baseline and fails if one stops being caught. | `check.py [qNNNN ...]` |
| `gen_data.py` | Schema-driven generator for **small / medium / large** datasets (20 / 10 / 3 by default). It respects key, not_null, refs, check and sorted. It mixes in NULLs, duplicates and ties, empty and 1-row tables, odd strings (`ß`, `ﬁ`, emoji, accent marks, long strings), case and space variants, `1.0` vs `1.00`, and boundary dates. Literals taken from the programs (`'CARD'`, `750.00`, `#2023-01-01#`, ...) are planted with ±1 neighbours. Every file is validated with `bin/minivm --schema`. | `gen_data.py [--small N --medium N --large N --seed S]` |
| `make_adv_data.py` | Six small variants of `examples/data.json`: case and space variants, NULLs, duplicate customer ids. | `make_adv_data.py [N] [OUTDIR]` |
| `hand_opt.sh` / `naive_opt.sh` | Optimizers with the same command line as `./optimize`. They print the stored `.opt.mini` / `.naive.mini`, or the input if there is none. | `hand_opt.sh prog.mini schema.json` |

### `evaluator_agent/`: prototype evaluator, and tests of the evaluator itself
| File | What it does | Run |
|---|---|---|
| `eval-proto.py` | **Prototype evaluator.** It calls `OPTIMIZER prog.mini schema.json` for each example, then runs the original and the optimized program on all 40 datasets. A pair is SKIPPED if the original errors. It is a DEFECT if the optimizer fails or takes more than 1 s, if the optimized program errors, if ncols differ, or if the rows differ. Rows are compared in order when the original specifies order (SORT/TOPK reaching OUT), otherwise as a multiset. Numbers match within 1e-6 relative. Prints checked / skipped / defects / time; exits 1 on any defect. | `eval-proto.py OPTIMIZER [DATA...] [--quiet]` |
| `fake_opt.py` | 19 fake optimizers as generic program transforms. **8 honest** (identity, dead-code removal, register renaming, reformatting, HJOIN↔NLJOIN, ±1e-10 drift, INT→NUM scale) must not be flagged. **11 buggy** (GT↔GE, no NULLIFE, no UPPER, RTRIM→TRIM, NULLEQ, LEFT n-1, sort flip, dropped tie-break, reversed rows, 1e-5 drift, dead DIV by 0) must be caught. | `fake_opt.py MODE prog.mini schema.json` |
| `meta_eval.py` | Tests the tester: runs `eval-proto.py` on every fake. Reports CAUGHT / MISSED / OK / FALSE ALARM, with evidence for each miss: whether the fake changed the program, and on how many datasets the output was identical, order-only different, or different. Writes `meta_report.md`. | `meta_eval.py [MODE ...]` |
| `meta_report.md` | Output of the last `meta_eval.py` run. | — |
| `tricky_checks.py` | 56 checks covering comparator rules, order detection and VM facts. Details in `../notes/tricky_rules.md`. | `tricky_checks.py` |

## Results (measured with `bin/minivm`)
- **Hand-optimized speedups:** 3.14× geomean cycle reduction on `examples/data.json`. Larger datasets speed up much more, because the originals' quadratic self-joins grow with the data.

  | Program | q0001 | q0002 | q0003 | q0004 | q0005 | q0006 | q0007 | q0008 |
  |---|---|---|---|---|---|---|---|---|
  | Speedup on example data | 8.1× | 1.8× | 3.0× | 8.5× | 1.7× | 3.0× | 4.1× | 1.2× |
  | Speedup on large data | 4.5× | 1.8× | 37× | 47× | 2.2× | 20× | 8.3× | 1.3× |

- **Correctness:** all 8 hand-optimized programs match the originals on all 40 datasets, and all 8 naive baselines are caught.
- **Evaluator:** catches 11 of 11 buggy fakes with 0 false alarms on 8 honest ones. A full run takes 1.7 s.

## What we learned
1. **The biggest wins are generic, not clever.** Filter before joining and before building strings. Gather only the columns that reach `OUT`. Delete dead code. Use TOPK instead of SORT followed by a slice. These gave most of q0001, q0004 and q0007 (4–8.5×). Replacing a self-join with GROUP is the only big structural rewrite (q0003, q0006), and it is also the riskiest.
2. **Rewrites must rely on constraints, never on stats.**
   - Exactly one match is safe for `not_null` + `refs` to a key.
   - A SORT is a no-op on a `sorted` table.
   - `customers` has no key, so a join to it can multiply rows. The naive q0004, which assumes unique `c_id`, is wrong on data where `c_id` repeats.
3. **NULL semantics are the main trap.** HJOIN never matches NULL keys, but GROUP puts NULLs together. NULLIFE turns `''` into NULL. IS is never NULL. Every self-join→GROUP rewrite needs an explicit NULL-key filter.
4. **Safety rule for rewrites:** an operation may only run on a *subset* of the rows it originally ran on. Removing work can only remove errors, which is allowed because "if the input program errors, anything goes".
5. **Weak data hides bugs.**
   - Two broken q0007 variants (TOPK 4 instead of 5, flipped tie-break) passed the example data. It has only 3 July-2023 orders and no tied amounts.
   - The q0004 naive baseline went uncaught until the generator planted the programs' own literals: no category was ever `'KITCHEN'`, so every result was empty.
   - Fix: harvest literals and their ±1 neighbours, and generate more rows than every TOPK limit, plus ties.
6. **Multiset comparison alone is too lenient.** It missed a reversed-rows bug and barely caught sort-key bugs (4 and 2 defects). The order rule raised these to 172, 134 and 19 defects with no new false alarms.
7. **The output JSON has no types.**
   - STR `"2.00"` prints like a NUM.
   - Only text minivm actually prints as a number (`-?\d+(\.\d+)?`) may be compared numerically; otherwise a TRIM bug on `'1.0 '` would hide.
   - JSON `true` must never equal `1`.
   - Remaining ambiguity: STR `'1.0'` vs `'1.00'`.
8. **Test the tester, and test it with evidence.** An evaluator that reports 0 defects proves nothing until it has caught seeded bugs and passed honest-but-different optimizers. Honest examples include renaming registers, INT→NUM scale changes, and 1e-10 drift.
9. **Calling the platform binary directly is 4.6× faster than the `bin/minivm` wrapper** (8.3 ms vs 38.6 ms per run, identical output). This leaves the 2-minute evaluator budget roomy: about 14k VM runs fit in 2 minutes even sequentially, and many more in parallel on 16 cores.

## Known gaps (next steps for the real build)
- **Programs:** only the 8 example programs are tested. There is no random program generator yet, and only the example schema is used.
- **Error paths:** no generated dataset makes an original program error, so the "anything goes" path is untested.
- **Ties:** rows that tie on the sort keys are still compared in order, so an optimizer that legally reorders ties would be flagged (open question Q1).
- **Tolerance:** the 1e-6 relative tolerance also applies to INTs, so `10000000` vs `10000001` passes.
