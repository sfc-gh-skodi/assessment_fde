# ./evaluate vs fake optimizers (tools/meta_eval.py)

buggy: caught 34/36, missed 2 | honest: ok 17/17, false alarms 0 | seeds 1,2,3 | quick | meta wall 1048s

| Fake | Expected | Result | Defects (per seed) | Checks | Eval wall s | What it does |
|---|---|---|---|---|---|---|
| `h_identity` | pass | OK | 0/0/0 | 1027/1036/1030 | 18.9/19.0/19.1 | prints the input unchanged |
| `h_dce` | pass | OK | 0/0/0 | 1027/1036/1030 | 20.9/22.3/25.1 | removes instructions whose results are never used |
| `h_rename` | pass | OK | 0/0/0 | 1027/1036/1030 | 16.8/17.7/16.0 | renames every register to q0, q1, ... |
| `h_format` | pass | OK | 0/0/0 | 1027/1036/1030 | 15.9/16.2/17.3 | lower-case opcodes, tabs, CRLF, blank lines, comments |
| `h_join_swap` | pass | OK | 0/0/0 | 1027/1036/1030 | 18.4/18.3/20.1 | NLJOIN -> HJOIN (same results by spec, never slower to the limit) |
| `h_tiny_drift` | pass | OK | 0/0/0 | 1027/1036/1030 | 22.2/24.5/26.6 | multiplies each GSUM by 1.0000000001 (1e-10 relative) |
| `h_scale` | pass | OK | 0/0/0 | 1027/1036/1030 | 24.3/25.9/27.9 | adds 0.000 to each GSUM (INT 3 prints as NUM '3.000') |
| `h_hand` | pass | OK | 0/0/0 | 1027/1036/1030 | 24.4/23.6/23.5 | the hand-optimized qNNNN.opt.mini programs |
| `h_case` | pass | OK | 0/0/0 | 1027/1036/1030 | 22.0/21.5/21.9 | mixed-case opcodes and keywords (asc -> Asc, NULL -> Null) |
| `h_ssa_hoist` | pass | OK | 0/0/0 | 1027/1036/1030 | 27.7/27.9/28.2 | SSA-renames registers and hoists every LOAD to the top |
| `h_cse_loads` | pass | OK | 0/0/0 | 1027/1036/1030 | 29.6/30.2/32.1 | SSA + merges repeated LOADs of one column, then DCE |
| `h_tie_reorder` | pass | OK | 0/0/0 | 1027/1036/1030 | 31.2/29.3/27.7 | reverses tied rows of a lone SORT/TOPK (ties may come in any order, Q1) |
| `h_sort_sorted` | pass | OK | 0/0/0 | 1027/1036/1030 | 22.2/22.2/22.2 | SORT on a prefix of a `sorted` table's columns ASC NF -> IOTA |
| `h_ge_gt_int` | pass | OK | 0/0/0 | 1027/1036/1030 | 22.9/23.7/25.5 | GE INTcol, k -> GT k-1 and LE k -> LT k+1 |
| `h_notnull` | pass | OK | 0/0/0 | 1027/1036/1030 | 23.4/17.9/21.6 | on key/not_null columns: EQ -> IS, NVL a, b -> NVL a, NULL |
| `h_topk` | pass | OK | 0/0/0 | 1027/1036/1030 | 22.4/21.8/20.0 | SORT ... SLICE n -> TOPK n when only the sliced rows are used |
| `h_unsorted_rev` | pass | OK | 0/0/0 | 1027/1036/1030 | 26.6/26.3/26.3 | reverses output rows of programs with no SORT/TOPK (order unspecified) |
| `b_strict` | flag | CAUGHT | 150/157/152 | 1027/1036/1030 | 31.5/30.5/35.1 | first GT/GE/LT/LE against a literal flips strictness |
| `b_no_nullife` | flag | CAUGHT | 16/20/23 | 1027/1036/1030 | 27.9/28.7/29.4 | NULLIFE becomes a no-op |
| `b_no_upper` | flag | CAUGHT | 104/110/107 | 1027/1036/1030 | 30.2/30.5/28.0 | UPPER becomes a no-op |
| `b_trim` | flag | CAUGHT | 44/43/53 | 1027/1036/1030 | 22.6/22.4/24.6 | RTRIM becomes TRIM |
| `b_nulleq` | flag | CAUGHT | 54/82/71 | 1027/1036/1030 | 31.9/31.9/32.5 | adds NULLEQ to every join |
| `b_left_short` | flag | CAUGHT | 34/42/41 | 1027/1036/1030 | 27.1/25.7/27.5 | LEFT n -> LEFT n-1 |
| `b_sort_flip` | flag | CAUGHT | 311/304/241 | 1027/1036/1030 | 38.4/36.5/36.1 | first SORT/TOPK key flips ASC <-> DESC |
| `b_no_tiebreak` | flag | CAUGHT | 79/84/55 | 1027/1036/1030 | 29.2/30.3/29.4 | drops the last key of every multi-key SORT/TOPK |
| `b_reverse` | flag | CAUGHT | 348/371/311 | 1027/1036/1030 | 42.6/43.2/42.8 | reverses the output rows |
| `b_drift` | flag | CAUGHT | 113/174/157 | 1027/1036/1030 | 28.5/25.8/28.9 | multiplies each GSUM by 1.00001 (1e-5 relative) |
| `b_dead_div0` | flag | CAUGHT | 882/928/787 | 1027/1036/1030 | 35.5/34.7/36.5 | adds an unused DIV by zero |
| `b_drop_nvl` | flag | CAUGHT | 38/42/33 | 1027/1036/1030 | 25.1/23.9/24.6 | NVL a, b -> NVL a, a (default lost) |
| `b_ge_gt` | flag | CAUGHT | 81/79/84 | 1027/1036/1030 | 26.1/24.8/25.9 | every GE -> GT |
| `b_drop_notnull` | flag | MISSED | 2/9/0 | 1027/1036/1030 | 19.7/23.0/21.6 | NOT(ISNULL x) filter becomes always TRUE |
| `b_join_keys` | flag | CAUGHT | 362/333/310 | 1027/1036/1030 | 28.5/26.7/28.2 | swaps the key operands of joins (left positions index the right side) |
| `b_topk_n1` | flag | CAUGHT | 100/86/71 | 1027/1036/1030 | 27.4/24.3/24.4 | TOPK/SLICE n -> n-1 |
| `b_unguard_div` | flag | CAUGHT | 27/24/26 | 1027/1036/1030 | 21.6/22.6/21.4 | removes the filters a DIV/IDIV/MOD divisor depends on (adds errors) |
| `b_dedup_nokey` | flag | CAUGHT | 56/65/54 | 1027/1036/1030 | 28.9/29.0/29.1 | dedups rows of tables that have no key |
| `b_slice_late` | flag | MISSED | 1/16/0 | 1027/1036/1030 | 23.7/21.9/23.4 | moves the SLICE cut to just before OUT (filter pushed above a SLICE) |
| `b_gsum_gcount` | flag | CAUGHT | 173/248/265 | 1027/1036/1030 | 27.8/27.8/29.8 | GSUM -> GCOUNT |
| `b_lit_case` | flag | CAUGHT | 132/113/92 | 1027/1036/1030 | 25.7/27.7/25.8 | swaps the case of string literals |
| `b_invalid` | flag | CAUGHT | 154/140/154 | 1027/1036/1030 | 22.0/23.4/27.7 | emits an invalid program (no OUT / unknown opcode) for some programs |
| `b_sleep` | flag | CAUGHT | 7/9/9 | 1027/1036/1030 | 38.8/39.8/36.7 | sleeps 1.5 s on some programs (> 1 s limit) |
| `b_empty` | flag | CAUGHT | 9/9/9 | 901/910/904 | 10.2/9.2/10.7 | prints nothing for some programs |
| `b_is_eq` | flag | CAUGHT | 16/48/18 | 1027/1036/1030 | 19.5/25.0/25.5 | IS -> EQ (NULL handling lost) |
| `b_gall_group` | flag | CAUGHT | 25/44/79 | 1027/1036/1030 | 23.0/18.3/25.6 | GALL g, s -> GROUP on a constant (0 groups instead of 1 on empty input) |
| `b_nf_nl` | flag | CAUGHT | 93/118/77 | 1027/1036/1030 | 35.3/35.2/32.2 | first SORT/TOPK key flips NF <-> NL |
| `b_date_shift` | flag | CAUGHT | 7/13/11 | 1027/1036/1030 | 20.5/21.1/22.2 | every date literal + 1 day |
| `b_dedup_out` | flag | CAUGHT | 154/154/142 | 1027/1036/1030 | 36.6/36.3/38.8 | removes duplicate output rows |
| `b_cap_rows` | flag | CAUGHT | 79/75/79 | 1027/1036/1030 | 37.9/36.7/37.3 | keeps at most 300 output rows |
| `b_cat_swap` | flag | CAUGHT | 75/78/57 | 1027/1036/1030 | 28.6/28.6/26.1 | CAT a, b -> CAT b, a |
| `b_stats` | flag | CAUGHT | 14/12/11 | 1027/1036/1030 | 22.0/22.2/21.9 | drops range predicates that hold on the stats min..max (stats used as constraints) |
| `b_group_null` | flag | CAUGHT | 11/13/17 | 1027/1036/1030 | 25.9/25.6/28.0 | GROUP on one key merges NULL with ''/0 |
| `b_drop_nulleq` | flag | CAUGHT | 15/7/12 | 1027/1036/1030 | 23.2/19.9/22.3 | removes NULLEQ from joins |
| `b_nljoin` | flag | CAUGHT | 2/1/1 | 1027/1036/1030 | 30.6/29.7/29.2 | HJOIN -> NLJOIN (same pairs, but |L|*|R| work can exceed the VM limit) |
| `b_hjoin_dedup` | flag | CAUGHT | 62/72/72 | 1027/1036/1030 | 24.2/20.3/18.1 | self-join on a key keeps only the first match per left row (assumes unique keys) |

## Evidence

- `b_drop_notnull` MISSED: repros saved under /var/folders/9w/j7h7gw4x5fd39zh2bfj2krlw0000gn/T/minivm_meta_vneai0gy/keep_b_drop_notnull_1 / repros saved under /var/folders/9w/j7h7gw4x5fd39zh2bfj2krlw0000gn/T/minivm_meta_vneai0gy/keep_b_drop_notnull_2 / programs=74 datasets=14 checked=1030 skipped=6 warns=0 defects=0 max_opt=0.10s time=21.4s geomean_speedup=1.00x
  - `DEFECT  gen_example_011.mini  medium_3.json  rows differ (1 vs 1 rows)`
  - `DEFECT  gen_example_011.mini  medium_4.json  rows differ (1 vs 1 rows)`
  - `DEFECT  gen_example_010.mini  large_0.json  rows differ (764 vs 916 rows)`
  - `DEFECT  gen_example_010.mini  large_1.json  rows differ (1092 vs 1275 rows)`
  - `DEFECT  gen_example_010.mini  medium_0.json  rows differ (24 vs 26 rows)`
- `b_slice_late` MISSED: repros saved under /var/folders/9w/j7h7gw4x5fd39zh2bfj2krlw0000gn/T/minivm_meta_vneai0gy/keep_b_slice_late_1 / repros saved under /var/folders/9w/j7h7gw4x5fd39zh2bfj2krlw0000gn/T/minivm_meta_vneai0gy/keep_b_slice_late_2 / programs=74 datasets=14 checked=1030 skipped=6 warns=0 defects=0 max_opt=0.09s time=23.3s geomean_speedup=1.00x
  - `DEFECT  gen_example_004.mini  large_0.json  rows differ (0 vs 1 rows)`
  - `DEFECT  gen_example_004.mini  large_0.json  rows differ (15 vs 20 rows)`
  - `DEFECT  gen_example_004.mini  large_1.json  rows differ (19 vs 20 rows)`
  - `DEFECT  gen_example_004.mini  medium_0.json  rows differ (17 vs 20 rows)`
