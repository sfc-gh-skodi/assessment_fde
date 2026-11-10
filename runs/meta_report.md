# ./evaluate vs fake optimizers (tools/meta_eval.py)

buggy: caught 34/35, missed 1 | honest: ok 16/17, false alarms 1 | seeds 1 | quick | meta wall 336s

| Fake | Expected | Result | Defects (per seed) | Checks | Eval wall s | What it does |
|---|---|---|---|---|---|---|
| `h_identity` | pass | OK | 0 | 1027 | 18.7 | prints the input unchanged |
| `h_dce` | pass | OK | 0 | 1027 | 23.2 | removes instructions whose results are never used |
| `h_rename` | pass | OK | 0 | 1027 | 19.0 | renames every register to q0, q1, ... |
| `h_format` | pass | OK | 0 | 1027 | 18.3 | lower-case opcodes, tabs, CRLF, blank lines, comments |
| `h_join_swap` | pass | FALSE ALARM | 2 | 1027 | 30.1 | HJOIN <-> NLJOIN (same results by spec) |
| `h_tiny_drift` | pass | OK | 0 | 1027 | 27.6 | multiplies each GSUM by 1.0000000001 (1e-10 relative) |
| `h_scale` | pass | OK | 0 | 1027 | 27.9 | adds 0.000 to each GSUM (INT 3 prints as NUM '3.000') |
| `h_hand` | pass | OK | 0 | 1027 | 25.1 | the hand-optimized qNNNN.opt.mini programs |
| `h_case` | pass | OK | 0 | 1027 | 19.6 | mixed-case opcodes and keywords (asc -> Asc, NULL -> Null) |
| `h_ssa_hoist` | pass | OK | 0 | 1027 | 27.6 | SSA-renames registers and hoists every LOAD to the top |
| `h_cse_loads` | pass | OK | 0 | 1027 | 31.4 | SSA + merges repeated LOADs of one column, then DCE |
| `h_tie_reorder` | pass | OK | 0 | 1027 | 30.8 | reverses tied rows of a lone SORT/TOPK (ties may come in any order, Q1) |
| `h_sort_sorted` | pass | OK | 0 | 1027 | 21.7 | SORT on a prefix of a `sorted` table's columns ASC NF -> IOTA |
| `h_ge_gt_int` | pass | OK | 0 | 1027 | 21.2 | GE INTcol, k -> GT k-1 and LE k -> LT k+1 |
| `h_notnull` | pass | OK | 0 | 1027 | 21.4 | on key/not_null columns: EQ -> IS, NVL a, b -> NVL a, NULL |
| `h_topk` | pass | OK | 0 | 1027 | 21.5 | SORT ... SLICE n -> TOPK n when only the sliced rows are used |
| `h_unsorted_rev` | pass | OK | 0 | 1027 | 24.3 | reverses output rows of programs with no SORT/TOPK (order unspecified) |
| `b_strict` | flag | CAUGHT | 148 | 1027 | 27.7 | first GT/GE/LT/LE against a literal flips strictness |
| `b_no_nullife` | flag | CAUGHT | 16 | 1027 | 26.4 | NULLIFE becomes a no-op |
| `b_no_upper` | flag | CAUGHT | 92 | 1027 | 26.9 | UPPER becomes a no-op |
| `b_trim` | flag | CAUGHT | 41 | 1027 | 22.7 | RTRIM becomes TRIM |
| `b_nulleq` | flag | CAUGHT | 52 | 1027 | 27.2 | adds NULLEQ to every join |
| `b_left_short` | flag | CAUGHT | 32 | 1027 | 23.8 | LEFT n -> LEFT n-1 |
| `b_sort_flip` | flag | CAUGHT | 280 | 1027 | 33.5 | first SORT/TOPK key flips ASC <-> DESC |
| `b_no_tiebreak` | flag | CAUGHT | 69 | 1027 | 28.5 | drops the last key of every multi-key SORT/TOPK |
| `b_reverse` | flag | CAUGHT | 348 | 1027 | 37.8 | reverses the output rows |
| `b_drift` | flag | CAUGHT | 112 | 1027 | 25.4 | multiplies each GSUM by 1.00001 (1e-5 relative) |
| `b_dead_div0` | flag | CAUGHT | 882 | 1027 | 30.8 | adds an unused DIV by zero |
| `b_drop_nvl` | flag | CAUGHT | 38 | 1027 | 23.7 | NVL a, b -> NVL a, a (default lost) |
| `b_ge_gt` | flag | CAUGHT | 80 | 1027 | 22.9 | every GE -> GT |
| `b_drop_notnull` | flag | MISSED | 0 | 1027 | 20.5 | NOT(ISNULL x) filter becomes always TRUE |
| `b_join_keys` | flag | CAUGHT | 359 | 1027 | 30.1 | swaps the key operands of joins (left positions index the right side) |
| `b_topk_n1` | flag | CAUGHT | 100 | 1027 | 26.7 | TOPK/SLICE n -> n-1 |
| `b_unguard_div` | flag | CAUGHT | 27 | 1027 | 23.6 | removes the filters a DIV/IDIV/MOD divisor depends on (adds errors) |
| `b_dedup_nokey` | flag | CAUGHT | 56 | 1027 | 29.2 | dedups rows of tables that have no key |
| `b_slice_late` | flag | CAUGHT | 1 | 1027 | 23.6 | moves the SLICE cut to just before OUT (filter pushed above a SLICE) |
| `b_gsum_gcount` | flag | CAUGHT | 172 | 1027 | 26.7 | GSUM -> GCOUNT |
| `b_lit_case` | flag | CAUGHT | 129 | 1027 | 27.8 | swaps the case of string literals |
| `b_invalid` | flag | CAUGHT | 154 | 1027 | 23.2 | emits an invalid program (no OUT / unknown opcode) for some programs |
| `b_sleep` | flag | CAUGHT | 7 | 1027 | 34.5 | sleeps 1.5 s on some programs (> 1 s limit) |
| `b_empty` | flag | CAUGHT | 9 | 901 | 20.5 | prints nothing for some programs |
| `b_is_eq` | flag | CAUGHT | 16 | 1027 | 22.1 | IS -> EQ (NULL handling lost) |
| `b_gall_group` | flag | CAUGHT | 25 | 1027 | 16.8 | GALL g, s -> GROUP on a constant (0 groups instead of 1 on empty input) |
| `b_nf_nl` | flag | CAUGHT | 81 | 1027 | 28.8 | first SORT/TOPK key flips NF <-> NL |
| `b_date_shift` | flag | CAUGHT | 7 | 1027 | 20.9 | every date literal + 1 day |
| `b_dedup_out` | flag | CAUGHT | 154 | 1027 | 38.9 | removes duplicate output rows |
| `b_cap_rows` | flag | CAUGHT | 79 | 1027 | 38.7 | keeps at most 300 output rows |
| `b_cat_swap` | flag | CAUGHT | 71 | 1027 | 25.9 | CAT a, b -> CAT b, a |
| `b_stats` | flag | CAUGHT | 14 | 1027 | 23.0 | drops range predicates that hold on the stats min..max (stats used as constraints) |
| `b_group_null` | flag | CAUGHT | 11 | 1027 | 19.4 | GROUP on one key merges NULL with ''/0 |
| `b_drop_nulleq` | flag | CAUGHT | 15 | 1027 | 17.6 | removes NULLEQ from joins |
| `b_hjoin_dedup` | flag | CAUGHT | 62 | 1027 | 17.8 | self-join on a key keeps only the first match per left row (assumes unique keys) |

## Evidence

- `h_join_swap` FALSE ALARM: repros saved under /var/folders/9w/j7h7gw4x5fd39zh2bfj2krlw0000gn/T/minivm_meta_jogjn6g8/keep_h_join_swap_1
  - `DEFECT  tests/cases/complex/c05_four_join_topk.mini  large_0.json  optimized program errors: error: line 28: NLJOIN: the program takes more than 300000000 cycles`
  - `DEFECT  tests/cases/complex/c05_four_join_topk.mini  large_1.json  optimized program errors: error: line 28: NLJOIN: the program takes more than 300000000 cycles`
- `b_drop_notnull` MISSED: programs=74 datasets=14 checked=1027 skipped=9 warns=2 defects=0 max_opt=0.24s time=20.3s geomean_speedup=1.00x
