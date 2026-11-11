#!/usr/bin/env python3
"""One orchestrator <-> evaluator round, as a single scripted command.

  tools/loop.py [--gate SEEDS] [--log N "approach (ELI5)" "takeaway"]

  default : bench (test suite tiers) + ./evaluate --quick       (~20 s)
  --gate  : bench + ./evaluate full on each seed, e.g. --gate 1,2,3
  --log   : append a row to progress.md with the measured metrics

Prints a compact digest (tier speedups, defects grouped by program with the first
detail and repro dir) so a round costs ~1k tokens to read. Appends the raw numbers
to tests/runs/loop.jsonl. Exit 1 if any defect.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPT = os.path.join(REPO, "optimize")


def sh(cmd):
    t = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    return r, time.monotonic() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", default="")
    ap.add_argument("--log", nargs=3, metavar=("ITER", "APPROACH", "TAKEAWAY"))
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tests", "runs"), exist_ok=True)

    r, bt = sh([sys.executable, "tools/bench.py", OPT, "--out", "tests/runs/bench_last.json", "-q"])
    bench = json.load(open(os.path.join(REPO, "tests/runs/bench_last.json")))
    tiers = {k: v for k, v in bench["tiers"].items()}
    bdef = defaultdict(list)
    for name, p in bench["programs"].items():
        for d, s in p.get("datasets", {}).items():
            if s.get("status") not in ("OK", "SKIP"):
                bdef[name].append((os.path.basename(d), s.get("status"), s.get("detail", "")))
        for prob in p.get("problems", []):
            bdef[name].append(("-", "PROBLEM", str(prob)[:150]))

    seeds = [int(s) for s in a.gate.split(",") if s] or [None]
    evals = []
    for sd in seeds:
        keep = os.path.join(REPO, "eval_out", f"seed{sd or 'q'}")
        shutil.rmtree(keep, ignore_errors=True)
        cmd = ["./evaluate", OPT, "--json", f"tests/runs/eval_last_{sd or 'q'}.json", "--keep", keep]
        cmd += ["--quick"] if sd is None else ["--seed", str(sd)]
        r, et = sh(cmd)
        try:
            ev = json.load(open(os.path.join(REPO, f"tests/runs/eval_last_{sd or 'q'}.json")))
        except Exception:
            print("EVALUATE FAILED:", r.stdout[-800:], r.stderr[-800:])
            return 2
        ev["_wall"] = et
        ev["_seed"] = sd or "quick"
        ev["_keep"] = keep
        evals.append(ev)

    # ---------- digest
    print("tier       progs  geomean   defects  orig_cyc -> opt_cyc   max_opt_s")
    for k, v in tiers.items():
        print(f"{k:<10} {v.get('programs', ''):>5}  {v.get('geomean', 0):>6.2f}x  {v.get('defects', 0):>7}  "
              f"{v.get('orig_cycles', 0):>10} -> {v.get('opt_cycles', 0):<10} {v.get('max_opt_s', 0)}")
    print(f"bench wall {bt:.1f}s")
    for name, ds in list(bdef.items())[:8]:
        print(f"  BENCH DEFECT {name}: {len(ds)}x  e.g. {ds[0]}")
    tot_def = sum(len(v) for v in bdef.values())
    for ev in evals:
        print(f"evaluate seed={ev['_seed']}: checked={ev['checked']} defects={ev['defects']} warns={ev['warns']} "
              f"geomean={ev['geomean_speedup']}x max_opt={ev['max_opt_s']}s wall={ev['_wall']:.1f}s")
        byp = defaultdict(list)
        for prog, data, det in ev.get("defect_list", []):
            byp[prog].append((data, det))
        for prog, ds in list(byp.items())[:8]:
            print(f"  DEFECT {prog}: {len(ds)}x  e.g. {ds[0][0]}: {ds[0][1][:140]}")
        if byp:
            print(f"  repros: {ev['_keep']}")
        tot_def += ev["defects"]

    ex = tiers.get("examples", {}).get("geomean", 0)
    allg = tiers.get("all", {}).get("geomean", 0)
    gen = [ev["geomean_speedup"] for ev in evals]
    rec = {"time": datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M"), "defects": tot_def, "tiers": {k: v.get("geomean") for k, v in tiers.items()},
           "eval": [{k: ev[k] for k in ("_seed", "checked", "defects", "geomean_speedup", "max_opt_s", "_wall")} for ev in evals]}
    open(os.path.join(REPO, "tests/runs/loop.jsonl"), "a").write(json.dumps(rec) + "\n")

    if a.log:
        it, approach, take = a.log
        tierstr = " · ".join(f"{k} {tiers[k]['geomean']:.2f}×" for k in ("examples", "easy", "medium", "complex", "schema2") if k in tiers)
        evstr = " · ".join(f"s{ev['_seed']} {ev['defects']}" for ev in evals)
        gens = " / ".join("%.2f×" % g for g in gen)
        walls = " / ".join("%.0fs" % ev["_wall"] for ev in evals)
        maxopt = max(ev["max_opt_s"] for ev in evals)
        nchk = sum(ev["checked"] for ev in evals)
        nb = sum(len(v) for v in bdef.values())
        row = (f"| {it} | {rec['time']} | optimizer loop | {approach} | bench {nb} · eval {evstr} "
               f"| suite {allg:.2f}× ({tierstr}); evaluate {gens} "
               f"| bench {bt:.0f}s · eval {walls} · max opt {maxopt:.2f}s "
               f"| {nchk} checks | {take} |\n")
        p = os.path.join(REPO, "progress.md")
        text = open(p).read()
        marker = "\n## Iteration detail logs"
        text = text.replace(marker, row.rstrip("\n") + "\n" + marker, 1) if marker in text else text + row
        open(p, "w").write(text)
        print("logged row", it)
    return 1 if tot_def else 0


if __name__ == "__main__":
    sys.exit(main())
