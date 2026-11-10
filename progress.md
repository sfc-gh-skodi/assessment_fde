# progress.md: build log (one row per iteration)

ELI5 = "explain like I'm 5". Metrics: **defects** (wrong answers found by `./evaluate`), **speedup** (geomean original/optimized cycles), **cost** (wall time of the run; cycles saved), **eval** (meta-eval: buggy fakes caught / honest fakes falsely flagged).

## Timeline

| # | Time (UTC) | Who | Approach (ELI5) | Defects | Speedup | Cost / time | Eval quality | Takeaway (< 5 sentences) |
|---|---|---|---|---|---|---|---|---|
| 0 | 2026-11-10 | orchestrator | Re-ran the prototypes to get starting numbers: "do nothing", "hand-made fast versions", "known-wrong fast versions". | identity 0 · hand 0 · naive 138 (all caught) | 1.00× · 2.39× · 2.16× | `run_all.sh` 62 s | 11/11 buggy caught, 0/8 false alarms | Hand-optimizing shows ~2.4× is reachable on example data; naive shortcuts are fast but wrong, so the checker matters as much as the optimizer. |
| 1 | 2026-11-10 | orchestrator | Built the real checker (`./evaluate`): makes many random-but-legal tables and legacy-style programs, runs old vs new, compares answers (order-aware, tie-aware, typed). Wrote 28 new easy/medium/complex test programs. | identity 0 (777 checks quick, 3768 full) | 1.00× | quick 5 s · full 23 s | naive optimizer: 69 defects caught on full run | Generated programs and random schemas push coverage well beyond the 8 examples while staying inside the 2-minute budget. Writing helper files next to the inputs polluted the corpus (fixed: temp dir only). |

## Iteration detail logs
- Optimizer iterations: `runs/optimizer_iterations.md`
- Evaluator iterations: `runs/evaluator_iterations.md`
- Test suite and baselines: `runs/testsuite_iterations.md`
