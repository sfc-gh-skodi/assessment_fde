#!/usr/bin/env python3
"""Meta-evaluation: test ./evaluate against every fake optimizer in tools/fakes.py.

  meta_eval.py [MODE ...] [--seed S] [--full] [-j N] [--seeds 1,2,3] [--out tests/runs/meta_report.md]

  buggy fake + evaluate exit != 0 -> CAUGHT      buggy fake + exit 0 -> MISSED
  honest fake + evaluate exit 0   -> OK          honest fake + exit != 0 -> FALSE ALARM

--seeds runs every fake under each seed (a buggy fake counts as CAUGHT only if caught
under every seed; an honest fake is a FALSE ALARM if flagged under any seed).
Writes a markdown report (default tests/runs/meta_report.md). Exit 0 iff 0 missed and 0 false alarms.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fakes  # noqa: E402


def wrapper(tmp, mode):
    p = os.path.join(tmp, mode + ".sh")
    with open(p, "w") as f:
        f.write(f'#!/bin/sh\nexec "{sys.executable}" "{os.path.join(HERE, "fakes.py")}" {mode} "$@"\n')
    os.chmod(p, 0o755)
    return p


def run_one(tmp, mode, seed, full):
    js = os.path.join(tmp, f"{mode}_{seed}.json")
    cmd = [os.path.join(REPO, "evaluate"), wrapper(tmp, mode), "--seed", str(seed),
           "--json", js, "--keep", os.path.join(tmp, f"keep_{mode}_{seed}")]
    if not full:
        cmd.append("--quick")
    t = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp)
    rep = json.load(open(js)) if os.path.exists(js) else {}
    lines = r.stdout.strip().splitlines()
    return {"rc": r.returncode, "summary": lines[-1] if lines else r.stderr.strip()[-300:],
            "first": [x for x in lines if x.startswith("DEFECT")][:3], "defects": rep.get("defects"),
            "checked": rep.get("checked"), "wall": round(time.monotonic() - t, 1)}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("modes", nargs="*")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--seeds")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("-j", type=int, default=3)
    ap.add_argument("--out", default=os.path.join(REPO, "tests", "runs", "meta_report.md"))
    a = ap.parse_args(argv)
    modes = a.modes or list(fakes.MODES)
    seeds = [int(x) for x in a.seeds.split(",")] if a.seeds else [a.seed]
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="minivm_meta_") as tmp:
        jobs = [(m, s) for m in modes for s in seeds]
        with ThreadPoolExecutor(max_workers=a.j) as ex:
            res = dict(zip(jobs, ex.map(lambda j: run_one(tmp, j[0], j[1], a.full), jobs)))
    tally = {"CAUGHT": 0, "MISSED": 0, "OK": 0, "FALSE ALARM": 0}
    rows = []
    for m in modes:
        kind, desc, _ = fakes.MODES[m]
        rs = [res[(m, s)] for s in seeds]
        flagged = [r["rc"] != 0 for r in rs]
        if kind == "buggy":
            v = "CAUGHT" if all(flagged) else "MISSED"
        else:
            v = "FALSE ALARM" if any(flagged) else "OK"
        tally[v] += 1
        rows.append((m, kind, v, "/".join(str(r["defects"]) for r in rs), desc, rs))
        print(f"{v:<12} {m:<16} {kind:<6} defects={rows[-1][3]:<10} {desc}", flush=True)
        if v in ("MISSED", "FALSE ALARM"):
            for r in rs:
                print("             " + r["summary"])
                for x in r["first"]:
                    print("             " + x)
    wall = time.monotonic() - t0
    nb = sum(1 for r in rows if r[1] == "buggy")
    nh = len(rows) - nb
    total = (f"buggy: caught {tally['CAUGHT']}/{nb}, missed {tally['MISSED']} | honest: ok {tally['OK']}/{nh}, "
             f"false alarms {tally['FALSE ALARM']} | seeds {','.join(map(str, seeds))} | "
             f"{'full' if a.full else 'quick'} | meta wall {wall:.0f}s")
    print("\n" + total)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        f.write("# ./evaluate vs fake optimizers (tools/meta_eval.py)\n\n")
        f.write(total + "\n\n")
        f.write("| Fake | Expected | Result | Defects (per seed) | Checks | Eval wall s | What it does |\n|---|---|---|---|---|---|---|\n")
        for m, kind, v, d, desc, rs in rows:
            f.write(f"| `{m}` | {'flag' if kind == 'buggy' else 'pass'} | {v} | {d} | "
                    f"{'/'.join(str(r['checked']) for r in rs)} | {'/'.join(str(r['wall']) for r in rs)} | {desc} |\n")
        bad = [r for r in rows if r[2] in ("MISSED", "FALSE ALARM")]
        if bad:
            f.write("\n## Evidence\n\n")
            for m, kind, v, d, desc, rs in bad:
                f.write(f"- `{m}` {v}: " + " / ".join(r["summary"] for r in rs) + "\n")
                for r in rs:
                    for x in r["first"]:
                        f.write(f"  - `{x}`\n")
    return 0 if tally["MISSED"] == tally["FALSE ALARM"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
