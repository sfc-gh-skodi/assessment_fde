# Test suite runbook

This folder holds the fixed test suite for the MiniVM optimizer: hand-written programs,
a second schema, generated datasets, scale-stress cases, and the baseline cycle counts
an optimizer has to beat. Run every command below from the **repo root**. You need
Python 3.8+ (standard library only) and the VM binary in `minivm-takehome/bin/`.

`OPTIMIZER` is any executable called as `OPTIMIZER program.mini schema.json` that
prints a MiniVM program. There are two reference optimizers:
- `tools/identity_opt.sh` (identity): must score 1.00x with 0 defects.
- `Pre_Build_inputs/prototype_code/optimizer_agent/hand_opt.sh` (hand-optimized examples): known-good
  speedups on the 8 example programs.

## Quick start

```sh
python3 tools/make_testdata.py                         # 1. build tests/data/ (~1 s)
python3 tools/bench.py tools/identity_opt.sh -q     # 2. sanity: 1.00x, 0 defects
python3 tools/bench.py OPTIMIZER -q                    # 3. your optimizer, per tier
./evaluate OPTIMIZER --quick                           # 4. broader randomized check
```

## What's in `tests/`

| Path | Committed | Contents |
|---|---|---|
| `cases/easy/` | yes | 15 programs on the example schema, one rewrite or trap each |
| `cases/medium/` | yes | 15 programs: TOPK, pushdown through one join, lookups, ties, NULLEQ |
| `cases/complex/` | yes | 12 programs: 3-4-join star schemas, self-join idioms, semi-joins |
| `schemas/hr/` | yes | second schema: `data.json` (hand-written), `schema.json` (`--schema` output), `programs/` (11 programs, h01-h11) |
| `baselines.json` | yes | original cycles per program per dataset, plus identity and hand-opt results |
| `data/<schema>/` | no (git-ignored) | generated datasets `small_{0,1,2}`, `medium_{0,1,2}`, `large_{0,1}` per schema |
| `stress/` | no (git-ignored) | near-limit cases, kept out of the normal corpus |
| `regressions/` | yes | repros of past defects (owned by the evaluator/optimizer agents) |

Every program starts with a header comment such as `; easy: <rewrite it targets>`
or `; medium TRAP: <what a wrong rewrite breaks>`. The S1-S10 ids in headers refer to
the safety rules in `BUILD_PLAN.md` §5. Every program runs without error on its schema's
hand-written `data.json`, and gives non-empty output there or on generated data.

`./evaluate` reads `tests/cases/**` and `tests/regressions/`, but not `tests/schemas/`.
`tools/bench.py` reads examples + `tests/cases/` + `tests/schemas/*/programs/`.

## 1. Test data

```sh
python3 tools/make_testdata.py           # (re)write tests/data/
python3 tools/make_testdata.py --check   # exit 1 if any file differs from a fresh build
```

- `evaluator/datagen.py` generates 8 datasets per schema from fixed seeds.
  - The `example` datasets use literals harvested from the example programs and `tests/cases/`.
  - The `hr` datasets use literals from `tests/schemas/hr/programs/`.
- Each file is validated with `bin/minivm --schema`; an invalid one is reported and not written.
- A rebuild gives the same files byte for byte, whatever the `PYTHONHASHSEED`.
- Rows (example): about 7-17 small, 1.1-1.4k medium, 18-26k large across all tables.

Rebuild after adding or editing a program, since its literals are planted in the data.

## 2. Benchmark and defects: `tools/bench.py`

```sh
python3 tools/bench.py OPTIMIZER              # per-program table + tier summary
python3 tools/bench.py OPTIMIZER -q           # tier summary only
python3 tools/bench.py OPTIMIZER --out r.json # JSON report (includes original cycles)
python3 tools/bench.py OPTIMIZER -j 8         # limit parallelism
```

- **Corpus:** 61 programs, each run on its schema's `data.json` plus the 8 generated datasets.
- **Run time:** about 5 s on an idle machine, 15-20 s when another agent is running the VM.
- **Exit status:** 1 if there are any defects.
- **Per pair:** each (program, dataset) pair gets one of these verdicts:
  - **SKIP**: the original errors on that dataset, so any output is acceptable.
  - **DEFECT**: the optimizer fails, or its program errors, or the results differ.
  - Results are compared as a multiset of rows. Order also counts when the original's
    output is ordered (SORT/TOPK); reordering tied rows is allowed. Numbers must match
    within 1e-6 relative. The rules are in `evaluator/compare.py`.
- **Speedup:** original cycles / optimized cycles. The geomean is taken over a program's
  datasets, then over the programs in a tier.

Summary columns: `geomean`, `gm(hw)` (hand-written `data.json` only), `defects`,
`checked`, `skipped`, `orig_cycles`, `opt_cycles` (non-defective pairs), `max_opt_s`.

In the per-program table, each defect is printed under its program as `DEFECT <dataset>: <reason>`.
To reproduce one:

```sh
OPTIMIZER tests/cases/<tier>/<prog>.mini minivm-takehome/examples/schema.json > /tmp/o.mini
minivm-takehome/bin/minivm tests/cases/<tier>/<prog>.mini tests/data/example/<dataset>.json
minivm-takehome/bin/minivm /tmp/o.mini                     tests/data/example/<dataset>.json
```

For hr programs, use `tests/schemas/hr/schema.json` and `tests/data/hr/`. To get
saved repro folders, run `./evaluate OPTIMIZER`, which writes them to `eval_out/`.

## 3. Baselines: `tests/baselines.json`

| Tier | Programs | identity | hand-opt | Original cycles |
|---|---|---|---|---|
| examples | 8 | 1.00x | 3.06x | 140,838,695 |
| easy | 15 | 1.00x | 1.00x | 35,870,147 |
| medium | 15 | 1.00x | 1.00x | 7,576,875 |
| complex | 12 | 1.00x | 1.00x | 58,744,762 |
| schema2 (hr) | 11 | 1.00x | 1.00x | 6,343,686 |
| all | 61 | 1.00x | 1.16x | 249,374,165 |

Both baselines have 0 defects (547 pairs checked, 2 skipped: c05 errors on `large_1`).
Hand-opt only rewrites the 8 examples, so it scores 1.00x everywhere else.

- `original_cycles[<program>]["cycles"][<dataset>]` gives the original cost of each pair
  (`null` means the original errors there).
- `runs.identity` and `runs["hand-opt"]` hold the full per-tier and per-program reports.

Regenerate after any change to programs or test data:

```sh
python3 tools/make_testdata.py && python3 tools/bench.py --baselines
```

## 4. Adding a program

1. Write it **outside** `tests/cases/` first. `./evaluate` picks up `tests/cases/**`
   immediately, and other agents run it all the time.
2. Start it with a header: `; <tier>: <rewrite>` or `; <tier> TRAP: <what breaks>`.
3. Check it runs and gives non-empty output somewhere:
   ```sh
   for d in minivm-takehome/examples/data.json tests/data/example/*.json; do
     minivm-takehome/bin/minivm /tmp/new.mini $d | cut -c1-80; done
   ```
4. Move it into place in one step: `mv /tmp/new.mini tests/cases/<tier>/<name>.mini`
   (hr programs: `tests/schemas/hr/programs/`).
5. Rebuild the data and baselines (section 3), then commit the program and `baselines.json`.

Common errors:
- `NF NL ASC DESC NULL TRUE FALSE NULLEQ` are keywords and can't be register names.
- Every sort key needs all three parts (`x DESC NL`).
- The last line must be the program's only `OUT`.
- An element-wise op needs at least one register operand.

**New schema:**
1. Write `tests/schemas/<name>/data.json`.
2. Save `minivm-takehome/bin/minivm --schema tests/schemas/<name>/data.json` as
   `tests/schemas/<name>/schema.json`.
3. Add `programs/*.mini`.

Both tools find a new schema automatically. bench counts its programs in the `schema2` tier.

## 5. Stress cases: `tests/stress/`

```sh
python3 tools/make_stress.py          # write tests/stress/ (3.8 MB, reproducible)
python3 tools/make_stress.py --run    # also run them, and all corpus programs on data_10k
```

| File | Limit probed | Expected |
|---|---|---|
| `example/prog_20k.mini` | 20,000 instructions | runs: ~680k cycles on the example data, ~200M on `data_10k.json` (work limit ~300M) |
| `example/data_10k.json` (+ `schema.json`) | 10,000 rows per table | valid; 7 corpus programs exceed the 4M join limit on it |
| `example/regpressure.mini` | 64M values across all registers | runs, ~60M values live |
| `fanout/fanout_ok.mini` | 4M values per register | runs, 3,996,001 join pairs |
| `fanout/fanout_over.mini` | 4M values per register | the original errors (4,004,001 pairs): any output is fine |

Use them to check that the optimizer stays under 1 s and never grows an intermediate result:

```sh
OPTIMIZER tests/stress/example/prog_20k.mini tests/stress/example/schema.json > /tmp/o.mini
minivm-takehome/bin/minivm /tmp/o.mini tests/stress/example/data_10k.json | tail -c 60
```

## 6. Program catalogue

Each entry gives the rewrite the program targets, or for TRAP entries the wrong rewrite it catches.

**easy** (`cases/easy/`)

| Program | Targets / guards |
|---|---|
| e01_dead_loads | dead loads and a dead computation |
| e02_cse | same column loaded twice, same predicate twice |
| e03_sort_on_sorted | SORT on the `sorted` lines table is the identity |
| e04_always_true | `GE l_qty, 1` always TRUE (not_null + check) |
| e05_check_nullable_trap | TRAP: check without not_null; the filter drops NULLs and must stay |
| e06_nljoin | NLJOIN -> HJOIN |
| e07_compute_then_filter | label built for every row, then filtered |
| e08_empty_gall | GALL keeps one row on empty input |
| e09_overwrite | heavily overwritten registers (SSA renaming) |
| e10_div_guarded_trap | TRAP: DIV only after a filter; hoisting it adds errors |
| e11_dead_sort | SORT feeding only GALL aggregates is dead |
| e12_unsorted_output | dead gathers after a filter, unordered output |
| e13_num_scale_gmin | TRAP: `ADD x, 0.000` rescales; GMIN first-of-equals (1.0 vs 1.00) |
| e14_unicode_upper_left | TRAP: UPPER changes length (ß), so it doesn't commute with LEFT |
| e15_empty_group_vs_gall | TRAP: GROUP on a constant key gives 0 rows on empty input, GALL gives 1 |

**medium** (`cases/medium/`)

| Program | Targets / guards |
|---|---|
| m01_sort_slice_topk | SORT + SLICE -> TOPK |
| m02_sort_then_filter | filter before sort |
| m03_pushdown_one_join | filter pushdown through one join |
| m04_lookup_label | exactly-one lookup join; label before the filter |
| m05_group_sorted | dead loads and a dead sort before GROUP |
| m06_customers_nokey | TRAP: customers has no key, so the join can fan out |
| m07_nullable_fk | nullable ref (at most one match) |
| m08_payments_lookup | not_null ref lookup; filter after the join |
| m09_topk_after_filter | sort, filter, slice -> filter, TOPK |
| m10_mixed_ties | stable sort with many ties |
| m11_topk_ties | TRAP: TOPK with ties keeps input order |
| m12_nulleq_join | TRAP: NULLEQ join; NULLs pair up |
| m13_sorted_filtered | SORT after IDX on a sorted table is the identity; the DESC sort is not |
| m14_sort_desc_ties | TRAP: DESC with NL/NF, stable ties |
| m15_label_before_join | label built before a lookup join and a late filter |

**complex** (`cases/complex/`)

| Program | Targets / guards |
|---|---|
| c01_star_group | star join, filters at the end, GROUP |
| c02_rank_per_group | "count of better rows" -> sort + rank |
| c03_semijoin_dedup | semi-join de-dup via SORT + GROUP |
| c04_group_broadcast | correlated self-join + GMIN |
| c05_four_join_topk | 4 joins + TOPK + label |
| c06_self_count_fewer | self-join count per group |
| c07_selfjoin_gmax_nullkeys | TRAP: self-join -> GROUP must drop NULL keys; no-key table |
| c08_category_parent | self-ref categories, 3 joins, late filter |
| c09_star_four_join | TRAP: 4-join star through no-key customers (fan-out) |
| c10_paid_ratio_div | TRAP: DIV guarded by `o_amt > 0`; top 5 via SORT + SLICE |
| c11_top2_lines_per_order | NLJOIN "count of better rows" with ties, late filter |
| c12_semijoin_nokey_label | TRAP: de-dup by row, not by c_id (no key) |

**hr schema** (`schemas/hr/programs/`): depts (self-ref parent), emps (self-ref manager,
nullable salary with check), shifts (composite key, sorted), deals (nullable ref),
events (no key)

| Program | Targets / guards |
|---|---|
| h01_dead_cse | dead loads + CSE |
| h02_sorted_composite | SORT on a composite sorted key is the identity; always-TRUE check |
| h03_nullable_check_trap | TRAP: nullable column with check; the filter must stay |
| h04_lookup_label | exactly-one lookup; label before a late OR filter |
| h05_topk_num_ties | TRAP: TOPK with ties at different NUM scales |
| h06_nokey_semijoin | TRAP: no-key table semi-join, de-dup by row |
| h07_selfref_manager | nullable self-ref lookup, late filter |
| h08_parent_rollup | 3 joins incl. a self-ref, string cleanup, late filter |
| h09_top_earner_per_dept | "count of better rows" with NULLs and ties |
| h10_shift_avg_topk | GROUP on a sorted table, safe DIV, top 4 |
| h11_nullife_selfjoin_gmax | TRAP: NULLIFE + self-join -> GROUP must drop NULLs; GMAX first-of-equals |

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `make_testdata.py --check` prints `DIFFERS` | a program's literals changed: rebuild data, then baselines |
| `INVALID ...` from `make_testdata.py` | the generated data broke a constraint and was not written; report the seed |
| bench much slower than ~5 s | another process is running the VM; use `-j N` or retry |
| `... is a keyword, not a register` | rename the register (section 4) |
| `SKIP` on some pairs | expected: the original errors on that dataset |
| identity bench shows defects | a test program or the comparator is broken: fix it before trusting any optimizer result |
