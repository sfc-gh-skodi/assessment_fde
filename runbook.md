# Runbook: running the tests

Everything is Python 3 (3.8+, standard library only) plus the MiniVM binary in
`minivm-takehome/bin/`. Run every command from the repo root.

`OPTIMIZER` below is any executable with the CLI `OPTIMIZER program.mini schema.json`
that prints a MiniVM program. There are two reference optimizers:

| Optimizer | Path | Use |
|---|---|---|
| identity | `minivm-takehome/optimize` | sanity check: must give 1.00x and 0 defects |
| hand-optimized examples | `prototype_code/optimizer_agent/hand_opt.sh` | known-good speedups on the 8 examples |

## Quick reference

| Goal | Command | Time |
|---|---|---|
| Is my optimizer correct? (fast) | `./evaluate OPTIMIZER --quick` | ~10 s |
| Is my optimizer correct? (full) | `./evaluate OPTIMIZER` | < 2 min |
| How fast is it, per tier, against the baselines? | `python3 tools/bench.py OPTIMIZER -q` | 5-20 s |
| Rebuild the generated test data | `python3 tools/make_testdata.py` | ~1 s |
| Check the test data is unchanged | `python3 tools/make_testdata.py --check` | ~1 s |
| Refresh `tests/baselines.json` | `python3 tools/bench.py --baselines` | 5-30 s |
| Near-limit stress cases | `python3 tools/make_stress.py --run` | ~10 s |
| Does the evaluator catch known bugs? | `python3 tools/meta_eval.py` | minutes |

Exit status: `./evaluate`, `bench.py` and `make_testdata.py --check` exit 0 when clean
and 1 on defects (or on stale data). Usage errors exit 2.

## 1. First-time setup

```sh
python3 --version                                   # 3.8 or newer
minivm-takehome/bin/minivm minivm-takehome/examples/programs/q0001.mini minivm-takehome/examples/data.json
python3 tools/make_testdata.py                      # writes tests/data/ (git-ignored)
```

The second command should print `{"ncols":4,...,"cycles":13766}`. On macOS a freshly
unzipped binary may be quarantined; `evaluator/vm.py` clears that automatically, or
run `xattr -d com.apple.quarantine minivm-takehome/bin/minivm-macos-*` once.

`tests/data/` and `tests/stress/` are not committed. Their generators use fixed
seeds, so a rebuild gives the same files byte for byte (`--check` confirms it).
`tools/bench.py` builds `tests/data/` by itself if it is missing.

## 2. Correctness: `./evaluate`

```sh
./evaluate OPTIMIZER --quick          # smaller corpus
./evaluate OPTIMIZER                  # full corpus, verdict in under 2 minutes
./evaluate OPTIMIZER --seed 7 -v      # another random corpus, show warnings
./evaluate OPTIMIZER --json out.json  # machine-readable report
```

It runs the examples, every `tests/cases/**/*.mini`, `tests/regressions/*.mini`, and
generated programs and schemas on generated datasets. For each (program, dataset) pair:

- **SKIP**: the original program errors there, so any output is acceptable.
- **DEFECT**: the optimizer fails, prints nothing, or takes more than 1 s; or the
  optimized program errors; or the results differ. Rows are compared as a multiset,
  and in order too when the original's output is ordered. Numbers must match within
  1e-6 relative; reordering tied rows is allowed.

Repros of the first defects go to `eval_out/<program>__<dataset>/` (change it with
`--keep DIR`), each with `orig.mini`, `opt.mini`, `data.json`, `schema.json` and
`defect.txt`. To replay one:

```sh
d=eval_out/<case>
minivm-takehome/bin/minivm $d/orig.mini $d/data.json
minivm-takehome/bin/minivm $d/opt.mini  $d/data.json
cat $d/defect.txt
```

Once a defect is fixed, copy its `orig.mini` into `tests/regressions/` so it stays
covered.

## 3. Performance: `tools/bench.py`

```sh
python3 tools/bench.py OPTIMIZER              # per-program table + tier summary
python3 tools/bench.py OPTIMIZER -q           # tier summary only
python3 tools/bench.py OPTIMIZER --out r.json # also write a JSON report
```

This runs a fixed corpus with no randomness: 61 programs in 5 tiers, each run on its
schema's hand-written `data.json` plus 8 generated datasets.

| Tier | Programs | Schema |
|---|---|---|
| examples | `minivm-takehome/examples/programs/*.mini` (8) | example |
| easy / medium / complex | `tests/cases/<tier>/*.mini` (15 / 15 / 12) | example |
| schema2 | `tests/schemas/hr/programs/*.mini` (11) | hr |

Columns in the tier summary:

- `geomean`: speedup (original cycles / optimized cycles), geomean over datasets, then over programs.
- `gm(hw)`: the same, on the hand-written `data.json` only.
- `defects`, `checked`, `skipped`: pair counts, judged by the same rules as `./evaluate`.
- `orig_cycles`, `opt_cycles`: totals over non-defective pairs.
- `max_opt_s`: the slowest optimizer call.

Defective pairs count as defects and are left out of the speedups.

Compare against the committed baselines in `tests/baselines.json`:

| Tier | identity | hand-opt |
|---|---|---|
| examples | 1.00x | 3.06x |
| easy / medium / complex / schema2 | 1.00x | 1.00x |
| all | 1.00x | 1.16x |

Total original cycles: 249,374,165. All baselines have 0 defects.
`tests/baselines.json["original_cycles"][program]["cycles"][dataset]` holds the
original cost of every pair, which is the number an optimizer has to beat.

Re-run `python3 tools/bench.py --baselines` after adding programs or changing
`tools/make_testdata.py`.

## 4. Adding a test program

1. Write the program in a temp location. It must start with a header comment such as
   `; easy: <rewrite it targets>` or `; medium TRAP: <what a wrong rewrite breaks>`.
2. Check that it runs and gives non-empty output on at least one dataset:
   ```sh
   minivm-takehome/bin/minivm /tmp/new.mini minivm-takehome/examples/data.json
   for d in tests/data/example/*.json; do minivm-takehome/bin/minivm /tmp/new.mini $d | cut -c1-80; done
   ```
3. Move it into place in one step, since `./evaluate` picks up `tests/cases/**` immediately:
   `mv /tmp/new.mini tests/cases/<tier>/<name>.mini`. Programs for the hr schema go in
   `tests/schemas/hr/programs/`.
4. Rebuild the data so the new program's literals are planted in it, then refresh the
   baselines:
   ```sh
   python3 tools/make_testdata.py && python3 tools/bench.py --baselines
   ```

Common errors:

- `NF`, `NL`, `ASC`, `DESC`, `NULL`, `TRUE`, `FALSE` and `NULLEQ` are keywords and
  can't be used as register names.
- The last line must be the only `OUT`.
- Every sort key needs all three parts, e.g. `x DESC NL`.

To add a whole new schema, create `tests/schemas/<name>/data.json`, then save the
output of `minivm-takehome/bin/minivm --schema tests/schemas/<name>/data.json` as
`tests/schemas/<name>/schema.json`, and add programs under `programs/`. Both
`make_testdata.py` and `bench.py` find new schemas automatically.

## 5. Stress cases (separate from the corpus)

```sh
python3 tools/make_stress.py          # write tests/stress/
python3 tools/make_stress.py --run    # also run them and print cycles / time / error
```

| File | Limit it probes | Expected |
|---|---|---|
| `example/prog_20k.mini` | 20,000 instructions | runs (~200M cycles on `data_10k.json`) |
| `example/data_10k.json` | 10,000 rows per table | valid; 7 corpus programs hit the 4M join limit on it |
| `example/regpressure.mini` | 64M values across all registers | runs (~60M values) |
| `fanout/fanout_ok.mini` | 4M values per register | runs (3,996,001 join pairs) |
| `fanout/fanout_over.mini` | 4M values per register | the original errors (4,004,001 pairs) |

To test an optimizer on one case:

```sh
OPTIMIZER tests/stress/example/prog_20k.mini tests/stress/example/schema.json > /tmp/o.mini
minivm-takehome/bin/minivm tests/stress/example/prog_20k.mini tests/stress/example/data_10k.json | tail -c 60
minivm-takehome/bin/minivm /tmp/o.mini tests/stress/example/data_10k.json | tail -c 60
```

The optimizer must still finish within 1 s, and its output must not grow any
intermediate result beyond the original's.

## 6. Evaluator self-test

`python3 tools/meta_eval.py` runs `./evaluate` against the fake optimizers in
`tools/fakes.py`. Each buggy fake must be caught and no honest fake may be flagged.
It writes `runs/meta_report.md` and exits 0 only if nothing is missed and there are
no false alarms. Run it after changing anything in `evaluator/`.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `bench.py` or `evaluate` slower than usual | another process is using the VM (the times above are for an idle machine); `-j N` sets bench parallelism |
| `make_testdata.py --check` prints `DIFFERS` | a test program's literals changed: re-run `python3 tools/make_testdata.py` and then `bench.py --baselines` |
| `INVALID ...` from `make_testdata.py` | the generated data broke a constraint; the file is not written. Report it with the seed shown |
| `error: ... is a keyword, not a register` | rename the register (see section 4) |
| Original program errors on a dataset | expected on some generated data; the pair is SKIPPED, not a defect |
