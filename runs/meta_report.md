# ./evaluate vs fake optimizers (tools/meta_eval.py)

buggy: caught 36/36, missed 0 | honest: ok 17/17, false alarms 0 | seeds 1 | quick | meta wall 346s

| Fake | Expected | Result | Defects (per seed) | Checks | Eval wall s | What it does |
|---|---|---|---|---|---|---|
| `h_identity` | pass | OK | 0 | 1028 | 27.3 | prints the input unchanged |
| `h_dce` | pass | OK | 0 | 1028 | 37.9 | removes instructions whose results are never used |
| `h_rename` | pass | OK | 0 | 1028 | 28.4 | renames every register to q0, q1, ... |
| `h_format` | pass | OK | 0 | 1028 | 27.3 | lower-case opcodes, tabs, CRLF, blank lines, comments |
| `h_join_swap` | pass | OK | 0 | 1028 | 30.2 | NLJOIN -> HJOIN (same results by spec, never slower to the limit) |
| `h_tiny_drift` | pass | OK | 0 | 1028 | 31.1 | multiplies each GSUM by 1.0000000001 (1e-10 relative) |
| `h_scale` | pass | OK | 0 | 1028 | 39.0 | adds 0.000 to each GSUM (INT 3 prints as NUM '3.000') |
| `h_hand` | pass | OK | 0 | 1028 | 33.4 | the hand-optimized qNNNN.opt.mini programs |
| `h_case` | pass | OK | 0 | 1028 | 30.4 | mixed-case opcodes and keywords (asc -> Asc, NULL -> Null) |
| `h_ssa_hoist` | pass | OK | 0 | 1028 | 41.3 | SSA-renames registers and hoists every LOAD to the top |
| `h_cse_loads` | pass | OK | 0 | 1028 | 44.8 | SSA + merges repeated LOADs of one column, then DCE |
| `h_tie_reorder` | pass | OK | 0 | 1028 | 47.0 | reverses tied rows of a lone SORT/TOPK (ties may come in any order, Q1) |
| `h_sort_sorted` | pass | OK | 0 | 1028 | 34.3 | SORT on a prefix of a `sorted` table's columns ASC NF -> IOTA |
| `h_ge_gt_int` | pass | OK | 0 | 1028 | 32.2 | GE INTcol, k -> GT k-1 and LE k -> LT k+1 |
| `h_notnull` | pass | OK | 0 | 1028 | 31.8 | on key/not_null columns: EQ -> IS, NVL a, b -> NVL a, NULL |
| `h_topk` | pass | OK | 0 | 1028 | 29.6 | SORT ... SLICE n -> TOPK n when only the sliced rows are used |
| `h_unsorted_rev` | pass | OK | 0 | 1028 | 37.9 | reverses output rows of programs with no SORT/TOPK (order unspecified) |
| `b_strict` | flag | CAUGHT | 151 | 1028 | 47.9 | first GT/GE/LT/LE against a literal flips strictness |
| `b_no_nullife` | flag | CAUGHT | 18 | 1028 | 36.4 | NULLIFE becomes a no-op |
| `b_no_upper` | flag | CAUGHT | 75 | 1028 | 41.5 | UPPER becomes a no-op |
| `b_trim` | flag | CAUGHT | 27 | 1028 | 38.2 | RTRIM becomes TRIM |
| `b_nulleq` | flag | CAUGHT | 47 | 1028 | 47.3 | adds NULLEQ to every join |
| `b_left_short` | flag | CAUGHT | 45 | 1028 | 36.6 | LEFT n -> LEFT n-1 |
| `b_sort_flip` | flag | CAUGHT | 292 | 1028 | 56.6 | first SORT/TOPK key flips ASC <-> DESC |
| `b_no_tiebreak` | flag | CAUGHT | 87 | 1028 | 46.1 | drops the last key of every multi-key SORT/TOPK |
| `b_reverse` | flag | CAUGHT | 320 | 1028 | 62.8 | reverses the output rows |
| `b_drift` | flag | CAUGHT | 149 | 1028 | 41.2 | multiplies each GSUM by 1.00001 (1e-5 relative) |
| `b_dead_div0` | flag | CAUGHT | 886 | 1028 | 52.1 | adds an unused DIV by zero |
| `b_drop_nvl` | flag | CAUGHT | 49 | 1028 | 38.0 | NVL a, b -> NVL a, a (default lost) |
| `b_ge_gt` | flag | CAUGHT | 89 | 1028 | 33.7 | every GE -> GT |
| `b_drop_notnull` | flag | CAUGHT | 17 | 1028 | 31.7 | NOT(ISNULL x) filter becomes always TRUE |
| `b_join_keys` | flag | CAUGHT | 362 | 1028 | 39.5 | swaps the key operands of joins (left positions index the right side) |
| `b_topk_n1` | flag | CAUGHT | 123 | 1028 | 37.8 | TOPK/SLICE n -> n-1 |
| `b_unguard_div` | flag | CAUGHT | 19 | 1028 | 34.1 | removes the filters a DIV/IDIV/MOD divisor depends on (adds errors) |
| `b_dedup_nokey` | flag | CAUGHT | 49 | 1028 | 42.7 | dedups rows of tables that have no key |
| `b_slice_late` | flag | CAUGHT | 9 | 1028 | 37.0 | moves the SLICE cut to just before OUT (filter pushed above a SLICE) |
| `b_gsum_gcount` | flag | CAUGHT | 219 | 1028 | 41.7 | GSUM -> GCOUNT |
| `b_lit_case` | flag | CAUGHT | 91 | 1028 | 38.4 | swaps the case of string literals |
| `b_invalid` | flag | CAUGHT | 154 | 1028 | 34.9 | emits an invalid program (no OUT / unknown opcode) for some programs |
| `b_sleep` | flag | CAUGHT | 7 | 1028 | 44.9 | sleeps 1.5 s on some programs (> 1 s limit) |
| `b_empty` | flag | CAUGHT | 9 | 902 | 29.2 | prints nothing for some programs |
| `b_is_eq` | flag | CAUGHT | 17 | 1028 | 32.1 | IS -> EQ (NULL handling lost) |
| `b_gall_group` | flag | CAUGHT | 36 | 1028 | 30.9 | GALL g, s -> GROUP on a constant (0 groups instead of 1 on empty input) |
| `b_nf_nl` | flag | CAUGHT | 94 | 1028 | 50.0 | first SORT/TOPK key flips NF <-> NL |
| `b_date_shift` | flag | CAUGHT | 10 | 1028 | 32.2 | every date literal + 1 day |
| `b_dedup_out` | flag | CAUGHT | 123 | 1028 | 55.8 | removes duplicate output rows |
| `b_cap_rows` | flag | CAUGHT | 61 | 1028 | 56.6 | keeps at most 300 output rows |
| `b_cat_swap` | flag | CAUGHT | 86 | 1028 | 41.7 | CAT a, b -> CAT b, a |
| `b_stats` | flag | CAUGHT | 15 | 1028 | 36.2 | drops range predicates that hold on the stats min..max (stats used as constraints) |
| `b_group_null` | flag | CAUGHT | 16 | 1028 | 38.9 | GROUP on one key merges NULL with ''/0 |
| `b_drop_nulleq` | flag | CAUGHT | 17 | 1028 | 28.0 | removes NULLEQ from joins |
| `b_nljoin` | flag | CAUGHT | 1 | 1028 | 25.3 | HJOIN -> NLJOIN (same pairs, but |L|*|R| work can exceed the VM limit) |
| `b_hjoin_dedup` | flag | CAUGHT | 66 | 1028 | 22.8 | self-join on a key keeps only the first match per left row (assumes unique keys) |

## Addendum (iteration 7): NULL-logic fakes, seeds 1,2,3, quick

| Fake | Expected | Result | Defects (per seed) | What it does |
|---|---|---|---|---|
| `b_countv` | flag | CAUGHT | 8/34/16 | GCOUNTV g, s -> GCOUNT g (NULLs counted) |
| `b_and_3vl` | flag | CAUGHT | 7/8/6 | AND a, b -> IF a, b, FALSE |
| `b_or_3vl` | flag | CAUGHT | 8/13/6 | OR a, b -> IF a, TRUE, b |
| `b_gsum_nvl0` | flag | CAUGHT | 60/60/70 | GSUM of an all-NULL group gives 0 instead of NULL |

The 17 honest fakes were not re-run after this iteration's generator change; the table above them predates it.
