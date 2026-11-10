# eval-proto.py vs fake optimizers

```
OK           h_identity     honest prints the input unchanged
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=0 time=1.9s geomean_speedup=1.00x
OK           h_dce          honest removes instructions whose results are never used
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=0 time=1.9s geomean_speedup=1.18x
OK           h_rename       honest renames every register to v0, v1, ...
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=0 time=1.9s geomean_speedup=1.00x
OK           h_format       honest lower-case opcodes, tabs, extra spaces, comments, blank lines
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=0 time=1.9s geomean_speedup=1.00x
OK           h_join_swap    honest HJOIN <-> NLJOIN (same results by spec)
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=0 time=1.9s geomean_speedup=0.84x
OK           h_tiny_drift   honest multiplies each GSUM by 1.0000000001 (1e-10 relative, within 1e-6)
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=0 time=1.9s geomean_speedup=0.99x
OK           h_scale        honest adds 0.000 to each GSUM (INT 3 prints as NUM '3.000'; same number)
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=0 time=1.9s geomean_speedup=0.99x
OK           h_hand         honest the hand-optimized qNNNN.opt.mini programs
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=0 time=1.9s geomean_speedup=2.39x
CAUGHT       b_strict       buggy  first GT/GE/LT/LE against a literal flips strictness (boundary bug)
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=69 time=1.9s geomean_speedup=0.99x
CAUGHT       b_no_nullife   buggy  NULLIFE becomes a no-op ('' no longer treated as NULL)
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=46 time=1.9s geomean_speedup=1.00x
CAUGHT       b_no_upper     buggy  UPPER becomes a no-op (case-sensitive matching)
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=79 time=1.9s geomean_speedup=1.04x
CAUGHT       b_trim         buggy  RTRIM becomes TRIM (leading spaces stripped too)
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=39 time=1.9s geomean_speedup=1.00x
CAUGHT       b_nulleq       buggy  adds NULLEQ to every join (NULL keys start matching)
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=56 time=1.9s geomean_speedup=0.99x
CAUGHT       b_left_short   buggy  LEFT n becomes LEFT n-1 (off by one)
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=4 time=1.9s geomean_speedup=1.00x
CAUGHT       b_sort_flip    buggy  first SORT/TOPK key flips ASC <-> DESC
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=134 time=1.9s geomean_speedup=1.00x
CAUGHT       b_no_tiebreak  buggy  drops the last key of every multi-key SORT/TOPK
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=19 time=1.9s geomean_speedup=1.00x
CAUGHT       b_reverse      buggy  reverses the output rows (order is specified: every example SORTs)
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=172 time=1.9s geomean_speedup=0.95x
CAUGHT       b_drift        buggy  multiplies each GSUM by 1.00001 (1e-5 relative, beyond 1e-6)
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=77 time=1.9s geomean_speedup=0.99x
CAUGHT       b_dead_div0    buggy  adds an unused DIV by zero (errors where the original didn't)
             eval: programs=8 (order-specified 8) datasets=40 checked=320 skipped=0 defects=272 time=1.9s geomean_speedup=0.98x

buggy: caught 11, missed 0 | honest: ok 8, false alarms 0 | time 37s
```
