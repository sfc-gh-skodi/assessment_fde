# Research: evaluating a MiniVM optimizer

Scratch experiments: `/tmp/research_eval/`. "Verified" = I ran it on `bin/minivm`.

## Findings

**Industry practice (what maps to this problem)**
- **Differential testing** (McKeeman '98; Csmith, PLDI'11): run the same input through two implementations and compare. For us: original vs optimized on the same VM. Csmith's lesson: generated programs must avoid UB (for us, programs that error) and print enough output for differences to show up. Programs that error or give empty output tell us nothing.
- **Translation validation** (Pnueli '98; CompCert validates register allocation after the fact; Alive2 checks that LLVM IR rewrites are refinements, using SMT). Validate each optimizer *output*, never trust the optimizer. A full SMT check is out of scope in 2 min. Our version is a test-based check per program.
- **STOKE** (superoptimizer): cheap tests filter candidates, then a formal check runs, and each counterexample becomes a new test (CEGIS loop). Takeaway: keep a growing set of "killer" datasets and run them first.
- **Metamorphic testing**: EMI (PLDI'14) changes dead code under fixed inputs. SQLancer: **TLP** (a query's result = union of its results under `p`, `NOT p`, `p IS NULL`), **NoREC** (compare against a form the optimizer can't optimize), **PQS** (pick a row and check it appears in the result). For us: the original program *is* the non-optimizing reference. TLP-style 3-way NULL partitions are a good model for adversarial data.
- **Test-case reduction**: C-Reduce / delta debugging, guided by an "interestingness" predicate. Shrink the dataset rows (children before parents, to keep `refs` valid) and then the program lines, while the diff still reproduces.
- **Mutation testing of the oracle**: plant known faults in the optimizer and measure the kill rate. Also confirm that correct rewrites are *not* killed, so false positives are measured too.

**Verified VM facts that matter for the evaluator**
- The `bin/minivm` wrapper runs `xattr` on every call: **43 ms serial, about 86 runs/s on 16 workers**. Calling `bin/minivm-macos-aarch64` directly takes **8.8 ms, about 420 runs/s**. The parallel speedup is only about 5x, likely due to process-spawn overhead.
- Output is deterministic: md5 matched over 3 runs. A 10k×10k `NLJOIN` producing a 2M-row output takes 425 ms and prints 13 MB of JSON (`HJOIN`: 188 ms).
- `--schema` rejects data that breaks a constraint (duplicate key, out-of-order `sorted`, INT outside 32 bits) with exit 1. Use it as the data-generator gate. `sorted` is checked as `ASC NF`, so NULLs come first.
- NUM keeps its scale: `GMIN` over `1.0`/`1.00` returns whichever comes first. `GSUM` scale = the largest scale among its inputs (`"2.00"`). `ADD x, 0.000` keeps `"1.0"`. `DIV 3,1` prints `"3"`, a NUM string with no point, so the type is not visible in the output.
- An error gives exit 1 and nothing on stdout. Errors depend on the data: `DIV` by zero only on rows that are actually used.
- Empty table: `GALL`+`GCOUNT` gives 1 row `[0,null,null]`. `GROUP` gives 0 rows. `UPPER('straße')`→`STRASSE`, so `LEFT∘UPPER ≠ UPPER∘LEFT`. `DATEADD 9999-12-31,1` is an error.
- The schema's `stats` describe one dataset only. The optimizer must be correct for **any** data that meets the constraints.

## Risks

- **False alarm on order.** A program "specifies order" only if its OUT rows come, through GATHER, IDX or SLICE, from a `SORT`/`TOPK`. Rows tied on the sort keys keep their *input* order, and a correct join reorder can legally change that order. Comparing tied rows strictly would flag correct optimizers.
- **Ties at a cut-off** (`SORT`+`SLICE`, `TOPK`, or `GFIRST` after a non-total sort for de-dup): a correct optimizer can return a different tied row. This is ambiguous in the spec. Choose lenient handling and document it.
- **Type is not visible in output.** STR `"2.00"` and NUM `"2.00"` print the same. Numeric tolerance on strings that look like numbers can hide a real STR change. INT `3` vs NUM `"3"` must count as equal.
- **Relative-only tolerance near zero.** `0` vs `1e-28`, e.g. a DIV-rounding residue, fails a strict `|a-b| ≤ 1e-6·max`. This is a spec-conformant flag, but it may look harsh.
- **Optimizer timing under load.** Running 16 VMs in parallel inflates the optimizer's wall time, which can produce a false ">1 s" failure.
- **Missed bugs (the evaluator wrongly passes a bad optimizer):**
  - The data generator only produces data that looks like the stats.
  - No NULLs in nullable `refs`/`check` columns.
  - No duplicates in non-key join columns.
  - No empty or 1-row tables.
  - Programs whose output is always empty.
- **Budget:** a slow optimizer (up to 1 s × N programs) dominates the run time, not the VM. Large join outputs make JSON parsing in Python the bottleneck.

## Recommendations

**Proving it WRONG within 2 min**
- Resolve the native binary the same way the wrapper does, with a fallback to `bin/minivm`. That gives about 420 runs/s, so 90 s ≈ 35k VM runs. Timeouts: 5 s per VM run, 2 s per optimizer call (flag at more than 1 s).
- **Corpus:** the 8 examples, their mutants, and type-inferred generated programs. Keep a program only if the original succeeds on at least 1 dataset and gives non-empty output on at least 1. Order the work as: killer datasets first, then examples, then generated programs (STOKE-style).
- **Data:** run `--schema` on every generated dataset and require its columns and constraints to equal the target schema, ignoring stats. Give the optimizer the schema of dataset D0, then test it on D1..Dk, whose stats deliberately differ (nulls where D0 had none, values beyond D0's min/max, duplicates where D0 was distinct).
- **Adversarial values:**
  - NULL in every nullable column, including nullable FKs and `check` columns.
  - Ties in sort keys; duplicate join keys.
  - `''` vs NULL; `'Open '`/`'OPEN'`/`'open'`; `ß`/multibyte strings.
  - `1.0`/`1.00`; zeros in divisor-like columns.
  - Values exactly on the `check` bounds; dates `0001-01-01`, `9999-12-31`, Feb 29.
  - Empty, 1-row and max-fan-out tables.
- Call the optimizer once per program, all calls in parallel, and cache the output. Fan out VM runs on 16 workers. **Exit early** on the first confirmed defect: re-run once to rule out flakiness, save the repro to `eval_out/`, exit 1. A watchdog at about 100 s stops new work and exits with the verdict so far.
- If time remains, shrink the repro with delta debugging (≤10 s cap).

**Not flagging a CORRECT optimizer**
- Skip a (program, dataset) pair when the original errors or hits a VM limit. It is a defect when the original succeeds and the optimized program errors, fails to parse, times out, or `ncols` differs.
- **Order:** do a static dataflow check for whether order is specified.
  - If order is unspecified, compare as multisets: sort both sides by a canonical key.
  - If order is specified, compare row by row, but canonical-sort *inside* runs of rows tied on the sort keys. If the keys are not in OUT, recover them by running an instrumented original with the sort keys appended to OUT.
  - Treat a diff at a TOPK/SLICE tie boundary as ambiguous: warn, don't fail.
- **Values:**
  - Exact match first.
  - Both values numeric (JSON int, or a string matching `^-?\d+(\.\d+)?$`): compare as `Decimal` with `|a−b| ≤ 1e-6·max(|a|,|b|)`, so `2.0`=`2.00` and `3`=`"3"`.
  - NULL only equals NULL. STR, DATE and BOOL must match exactly.
  - Better: infer OUT column types statically so numeric tolerance is never applied to STR.
- **Determinism:** fixed seed, sorted work lists, no wall-clock dependence in the verdict, only the deadline. Time the optimizer outside the VM fan-out, or re-time it alone before flagging ">1 s".
- **Meta-eval:** `cat` (identity) and known-correct rewrites must give 0 alarms. Correct rewrites to test:
  - reorder unsorted output
  - change NUM scale
  - TOPK ↔ SORT+SLICE
  - INT→NUM with the same value
  - swap the HJOIN/NLJOIN sides with a re-sort

  Bad mutants must give 100% kill:
  - drop a filter
  - ASC↔DESC, NF↔NL
  - drop NULLEQ; IS→EQ
  - `NOT GT` → `LE` (wrong under NULL)
  - move DIV before the filter
  - swap LEFT and UPPER
  - remove an inner join on a nullable FK
  - GALL→GROUP (wrong on an empty table)
  - TOPK n±1
  - assume stats are constraints (drop an ISNULL check because nulls=0)
