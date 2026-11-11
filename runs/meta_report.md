# ./evaluate vs fake optimizers (tools/meta_eval.py)

buggy: caught 44/44, missed 0 | honest: ok 17/17, false alarms 0 | seeds 1 | quick | meta wall 448s

| Fake | Expected | Result | Defects (per seed) | Checks | Eval wall s | What it does |
|---|---|---|---|---|---|---|
| `h_identity` | pass | OK | 0 | 1182 | 32.2 | prints the input unchanged |
| `h_dce` | pass | OK | 0 | 1182 | 42.8 | removes instructions whose results are never used |
| `h_rename` | pass | OK | 0 | 1182 | 31.7 | renames every register to q0, q1, ... |
| `h_format` | pass | OK | 0 | 1182 | 32.3 | lower-case opcodes, tabs, CRLF, blank lines, comments |
| `h_join_swap` | pass | OK | 0 | 1182 | 33.8 | NLJOIN -> HJOIN (same results by spec, never slower to the limit) |
| `h_tiny_drift` | pass | OK | 0 | 1182 | 33.6 | multiplies each GSUM by 1.0000000001 (1e-10 relative) |
| `h_scale` | pass | OK | 0 | 1182 | 38.1 | adds 0.000 to each GSUM (INT 3 prints as NUM '3.000') |
| `h_hand` | pass | OK | 0 | 1182 | 34.5 | the hand-optimized qNNNN.opt.mini programs |
| `h_case` | pass | OK | 0 | 1182 | 32.8 | mixed-case opcodes and keywords (asc -> Asc, NULL -> Null) |
| `h_ssa_hoist` | pass | OK | 0 | 1182 | 42.7 | SSA-renames registers and hoists every LOAD to the top |
| `h_cse_loads` | pass | OK | 0 | 1182 | 47.8 | SSA + merges repeated LOADs of one column, then DCE |
| `h_tie_reorder` | pass | OK | 0 | 1182 | 44.2 | reverses tied rows of a lone SORT/TOPK (ties may come in any order, Q1) |
| `h_sort_sorted` | pass | OK | 0 | 1182 | 32.6 | SORT on a prefix of a `sorted` table's columns ASC NF -> IOTA |
| `h_ge_gt_int` | pass | OK | 0 | 1182 | 35.3 | GE INTcol, k -> GT k-1 and LE k -> LT k+1 |
| `h_notnull` | pass | OK | 0 | 1182 | 32.1 | on key/not_null columns: EQ -> IS, NVL a, b -> NVL a, NULL |
| `h_topk` | pass | OK | 0 | 1182 | 30.2 | SORT ... SLICE n -> TOPK n when only the sliced rows are used |
| `h_unsorted_rev` | pass | OK | 0 | 1182 | 43.3 | reverses output rows of programs with no SORT/TOPK (order unspecified) |
| `b_strict` | flag | CAUGHT | 159 | 1182 | 47.0 | first GT/GE/LT/LE against a literal flips strictness |
| `b_no_nullife` | flag | CAUGHT | 14 | 1182 | 39.1 | NULLIFE becomes a no-op |
| `b_no_upper` | flag | CAUGHT | 113 | 1182 | 41.8 | UPPER becomes a no-op |
| `b_trim` | flag | CAUGHT | 47 | 1182 | 39.0 | RTRIM becomes TRIM |
| `b_nulleq` | flag | CAUGHT | 72 | 1182 | 49.1 | adds NULLEQ to every join |
| `b_left_short` | flag | CAUGHT | 58 | 1182 | 42.0 | LEFT n -> LEFT n-1 |
| `b_sort_flip` | flag | CAUGHT | 291 | 1182 | 60.2 | first SORT/TOPK key flips ASC <-> DESC |
| `b_no_tiebreak` | flag | CAUGHT | 93 | 1182 | 50.4 | drops the last key of every multi-key SORT/TOPK |
| `b_reverse` | flag | CAUGHT | 349 | 1182 | 77.9 | reverses the output rows |
| `b_drift` | flag | CAUGHT | 125 | 1182 | 47.2 | multiplies each GSUM by 1.00001 (1e-5 relative) |
| `b_dead_div0` | flag | CAUGHT | 946 | 1182 | 66.2 | adds an unused DIV by zero |
| `b_drop_nvl` | flag | CAUGHT | 43 | 1182 | 49.3 | NVL a, b -> NVL a, a (default lost) |
| `b_ge_gt` | flag | CAUGHT | 96 | 1182 | 44.1 | every GE -> GT |
| `b_drop_notnull` | flag | CAUGHT | 21 | 1182 | 39.6 | NOT(ISNULL x) filter becomes always TRUE |
| `b_join_keys` | flag | CAUGHT | 339 | 1182 | 53.5 | swaps the key operands of joins (left positions index the right side) |
| `b_topk_n1` | flag | CAUGHT | 117 | 1182 | 48.3 | TOPK/SLICE n -> n-1 |
| `b_unguard_div` | flag | CAUGHT | 27 | 1182 | 38.1 | removes the filters a DIV/IDIV/MOD divisor depends on (adds errors) |
| `b_dedup_nokey` | flag | CAUGHT | 62 | 1182 | 51.7 | dedups rows of tables that have no key |
| `b_slice_late` | flag | CAUGHT | 12 | 1182 | 43.8 | moves the SLICE cut to just before OUT (filter pushed above a SLICE) |
| `b_gsum_gcount` | flag | CAUGHT | 191 | 1182 | 49.5 | GSUM -> GCOUNT |
| `b_lit_case` | flag | CAUGHT | 106 | 1182 | 45.0 | swaps the case of string literals |
| `b_invalid` | flag | CAUGHT | 168 | 1182 | 38.9 | emits an invalid program (no OUT / unknown opcode) for some programs |
| `b_sleep` | flag | CAUGHT | 9 | 1182 | 54.9 | sleeps 1.5 s on some programs (> 1 s limit) |
| `b_empty` | flag | CAUGHT | 11 | 1028 | 37.0 | prints nothing for some programs |
| `b_is_eq` | flag | CAUGHT | 65 | 1182 | 43.1 | IS -> EQ (NULL handling lost) |
| `b_gall_group` | flag | CAUGHT | 32 | 1182 | 37.1 | GALL g, s -> GROUP on a constant (0 groups instead of 1 on empty input) |
| `b_nf_nl` | flag | CAUGHT | 94 | 1182 | 54.2 | first SORT/TOPK key flips NF <-> NL |
| `b_date_shift` | flag | CAUGHT | 8 | 1182 | 35.6 | every date literal + 1 day |
| `b_dedup_out` | flag | CAUGHT | 142 | 1182 | 64.2 | removes duplicate output rows |
| `b_cap_rows` | flag | CAUGHT | 92 | 1182 | 66.1 | keeps at most 300 output rows |
| `b_cat_swap` | flag | CAUGHT | 97 | 1182 | 47.8 | CAT a, b -> CAT b, a |
| `b_stats` | flag | CAUGHT | 16 | 1182 | 43.4 | drops range predicates that hold on the stats min..max (stats used as constraints) |
| `b_group_null` | flag | CAUGHT | 19 | 1182 | 50.4 | GROUP on one key merges NULL with ''/0 |
| `b_drop_nulleq` | flag | CAUGHT | 25 | 1182 | 37.7 | removes NULLEQ from joins |
| `b_nljoin` | flag | CAUGHT | 2 | 1182 | 50.4 | HJOIN -> NLJOIN (same pairs, but |L|*|R| work can exceed the VM limit) |
| `b_countv` | flag | CAUGHT | 8 | 1182 | 37.4 | GCOUNTV g, s -> GCOUNT g (NULLs counted) |
| `b_and_3vl` | flag | CAUGHT | 7 | 1182 | 45.4 | AND a, b -> IF a, b, FALSE (NULL AND TRUE becomes FALSE; visible under NOT / in output) |
| `b_or_3vl` | flag | CAUGHT | 8 | 1182 | 41.0 | OR a, b -> IF a, TRUE, b (NULL OR FALSE becomes FALSE; visible under NOT / in output) |
| `b_gsum_nvl0` | flag | CAUGHT | 60 | 1182 | 43.3 | GSUM of a group with no non-NULL values gives 0 instead of NULL |
| `b_hjoin_dedup` | flag | CAUGHT | 75 | 1182 | 46.5 | self-join on a key keeps only the first match per left row (assumes unique keys) |
| `b_or_not_true` | flag | CAUGHT | 8 | 1182 | 34.4 | OR(x, NOT x) -> TRUE (NULL x was dropped by IDX) |
| `b_check_nullable` | flag | CAUGHT | 14 | 1182 | 30.2 | folds a comparison its check bounds decide, even on a nullable column |
| `b_selfjoin_keep_null` | flag | CAUGHT | 137 | 1182 | 26.8 | self-join + GROUP over left rows -> GROUP the key on all rows (keeps NULL keys) |
| `b_isnull_two_ops` | flag | CAUGHT | 9 | 1182 | 23.1 | ISNULL(E(a, b)) -> ISNULL(a) (forgets b's NULLs) |
