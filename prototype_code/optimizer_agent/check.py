#!/usr/bin/env python3
"""Check every faster program against every dataset, in parallel.

  check.py [PROGRAM ...]          default: all examples/programs/qNNNN.mini

For each qNNNN it compares examples/programs/qNNNN.mini (the original) with
qNNNN.opt.mini (next to this script) on every data/**/*.json plus
examples/data.json, using cmp.compare (same rules as cmp.py).

On the first failure of an opt program:
  - the opt program is copied to qNNNN.naive.mini (only if no naive copy exists yet),
    so the wrong-but-fast version is kept as a known-bad baseline;
  - the failing dataset + detail is written to failures/qNNNN.txt.
Then fix qNNNN.opt.mini and rerun.

Every existing qNNNN.naive.mini is also re-checked: a baseline that is no longer
caught by any dataset means the data got weaker (reported as BASELINE_MISSED).

Prints a per-program, per-size report; exit 1 on any defect or missed baseline.
"""
import glob, os, shutil, sys
from concurrent.futures import ThreadPoolExecutor
from cmp import compare, ROOT, HERE

DATA = sorted(glob.glob(os.path.join(HERE, "data", "**", "*.json"), recursive=True)) + \
       [os.path.join(ROOT, "examples", "data.json")]
PROGS = os.path.join(ROOT, "examples", "programs")


def size_of(path):
    parts = os.path.relpath(path, HERE).split(os.sep)
    return parts[1] if parts[0] == "data" and len(parts) > 2 else "example"


def geomean(xs):
    if not xs:
        return None
    g = 1.0
    for x in xs:
        g *= x
    return g ** (1 / len(xs))


def run_all(orig, cand):
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 8) as ex:
        return list(zip(DATA, ex.map(lambda d: compare(orig, cand, d), DATA)))


def main(argv):
    names = argv or sorted(f[:-5] for f in os.listdir(PROGS) if f.endswith(".mini"))
    os.makedirs(os.path.join(HERE, "failures"), exist_ok=True)
    bad = 0
    sizes = ["example", "adv", "small", "medium", "large"]
    print(f"datasets: {len(DATA)}")
    print(f"{'program':<8} {'size':<8} {'match':>5} {'fail':>4} {'skip':>4} {'geomean':>8}  note")
    for q in names:
        orig = os.path.join(PROGS, q + ".mini")
        opt = os.path.join(HERE, q + ".opt.mini")
        naive = os.path.join(HERE, q + ".naive.mini")
        if not os.path.exists(opt):
            print(f"{q:<8} no opt program")
            continue
        res = run_all(orig, opt)
        fails = [(d, r) for d, r in res if r[0] in ("MISMATCH", "OPT_ERROR")]
        for sz in sizes:
            rs = [r for d, r in res if size_of(d) == sz]
            if not rs:
                continue
            sp = [r[1] / r[2] for r in rs if r[0] == "MATCH" and r[2]]
            g = geomean(sp)
            print(f"{q:<8} {sz:<8} {sum(r[0] == 'MATCH' for r in rs):>5} "
                  f"{sum(r[0] in ('MISMATCH', 'OPT_ERROR') for r in rs):>4} "
                  f"{sum(r[0] == 'SKIP' for r in rs):>4} {(f'{g:.2f}x' if g else '-'):>8}")
        if fails:
            bad += 1
            d, r = fails[0]
            note = f"{q}: {r[0]} on {os.path.relpath(d, HERE)}: {r[3]}"
            with open(os.path.join(HERE, "failures", q + ".txt"), "w") as f:
                f.write(note + "\n" + "\n".join(f"{r2[0]} {os.path.relpath(d2, HERE)} {r2[3]}" for d2, r2 in fails) + "\n")
            if not os.path.exists(naive):
                shutil.copy(opt, naive)
                note += f"  -> saved as {os.path.basename(naive)}"
            print(f"{q:<8} FAIL     {len(fails)} dataset(s). {note}")
        if os.path.exists(naive):
            caught = sum(r[0] in ("MISMATCH", "OPT_ERROR") for _, r in run_all(orig, naive))
            status = f"caught on {caught} dataset(s)" if caught else "BASELINE_MISSED"
            bad += caught == 0
            print(f"{q:<8} naive    {status}")
    print("\nRESULT:", "FAIL" if bad else "PASS")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
