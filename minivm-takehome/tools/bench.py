#!/usr/bin/env python3
"""Benchmark an optimizer on the fixed test corpus.

  tools/bench.py OPTIMIZER [--out FILE] [-j N] [-q]
  tools/bench.py --baselines [--out tests/baselines.json]

OPTIMIZER is called as `OPTIMIZER program.mini schema.json` and must print a program.
Corpus (no randomness; rebuild data with tools/make_testdata.py, done automatically if missing):
  tiers     examples (examples/programs), easy / medium / complex
            (tests/cases/<tier>), schema2 (tests/schemas/<name>/programs)
  datasets  the schema's hand-written data.json + tests/data/<schema>/*.json
Per (program, dataset): SKIP if the original errors; DEFECT if the optimizer fails, the
optimized program errors, or results differ (multiset of rows, order too when the
original specifies it; numbers within 1e-6 relative; rules in evaluator/compare.py).
Speedup = original cycles / optimized cycles. A program's speedup is the geomean over its
datasets; a tier's is the geomean over its programs. Defective pairs are excluded from
speedups but counted. --baselines benchmarks the identity optimizer and the hand-optimized
prototype and writes both, with ORIGINAL cycles per program per dataset, to the JSON file.
"""
import argparse
import glob
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from evaluator import compare as C  # noqa: E402
from evaluator import vm  # noqa: E402

EX = os.path.join(REPO, "examples")
TIERS = ("examples", "easy", "medium", "complex", "schema2")
IDENTITY = os.path.join(REPO, "tools", "identity_opt.sh")
HAND = os.path.join(REPO, "Pre_Build_inputs", "prototype_code", "optimizer_agent", "hand_opt.sh")
OPT_TIMEOUT_S = 10.0


def rel(p):
    return os.path.relpath(p, REPO)


def geomean(xs):
    xs = [x for x in xs if x and x > 0]
    return math.exp(sum(map(math.log, xs)) / len(xs)) if xs else None


def corpus():
    """-> list of dicts: name, tier, path, schema_path, data (list of paths)."""
    ex_data = [os.path.join(EX, "data.json")] + sorted(glob.glob(os.path.join(REPO, "tests", "data", "example", "*.json")))
    ex_schema = os.path.join(EX, "schema.json")
    out = []
    for p in sorted(glob.glob(os.path.join(EX, "programs", "*.mini"))):
        out.append(("examples", p, ex_schema, ex_data))
    for tier in ("easy", "medium", "complex"):
        for p in sorted(glob.glob(os.path.join(REPO, "tests", "cases", tier, "*.mini"))):
            out.append((tier, p, ex_schema, ex_data))
    for d in sorted(glob.glob(os.path.join(REPO, "tests", "schemas", "*", ""))):
        name = os.path.basename(os.path.dirname(d))
        sp = os.path.join(d, "schema.json")
        data = [os.path.join(d, "data.json")] + sorted(glob.glob(os.path.join(REPO, "tests", "data", name, "*.json")))
        for p in sorted(glob.glob(os.path.join(d, "programs", "*.mini"))):
            out.append(("schema2", p, sp, data))
    return [{"name": rel(p), "tier": t, "path": p, "schema_path": sp, "data": ds} for t, p, sp, ds in out]


def ensure_data():
    if not glob.glob(os.path.join(REPO, "tests", "data", "example", "*.json")):
        subprocess.run([sys.executable, os.path.join(HERE, "make_testdata.py")], check=True,
                       stdout=subprocess.DEVNULL)


class Bench:
    def __init__(self, jobs, work):
        self.jobs, self.work = jobs, work
        self.progs = corpus()
        self.schemas = {}
        self.orig = {}  # (prog, data) -> (result or None, err)
        self.keyed = {}
        self.cache = {}  # (sha1 of program text, data) -> vm.run result; the VM is deterministic
        for p in self.progs:
            if p["schema_path"] not in self.schemas:
                self.schemas[p["schema_path"]] = json.load(open(p["schema_path"], encoding="utf-8"))
            ir = C.parse(open(p["path"], encoding="utf-8").read())
            p["ordered"] = C.output_ordered(ir)
            p["types"] = C.out_types(ir, self.schemas[p["schema_path"]])
            p["cutoff"] = any(op in ("TOPK", "SLICE") for op, _ in ir)
            p["inst"] = None
            if p["ordered"]:
                text = C.instrument(ir)
                if text:
                    p["inst"] = os.path.join(work, "inst_" + p["name"].replace(os.sep, "_"))
                    open(p["inst"], "w", encoding="utf-8").write(text)

    def run(self, prog, data):
        key = (hashlib.sha1(open(prog, "rb").read()).hexdigest(), data)
        if key not in self.cache:
            self.cache[key] = vm.run(prog, data)
        return self.cache[key]

    def run_originals(self):
        pairs = [(p["path"], d) for p in self.progs for d in p["data"]]
        # slowest (largest data) first so the pool's tail is short
        pairs.sort(key=lambda pd: -os.path.getsize(pd[1]))
        with ThreadPoolExecutor(self.jobs) as ex:
            for k, r in zip(pairs, ex.map(lambda pd: self.run(*pd), pairs)):
                self.orig[k] = r

    def optimize(self, optimizer, p, outdir):
        t = time.monotonic()
        try:
            r = subprocess.run([optimizer, p["path"], p["schema_path"]], capture_output=True, text=True,
                               timeout=OPT_TIMEOUT_S)
        except Exception as e:
            return None, f"optimizer failed: {e}", time.monotonic() - t
        dt = time.monotonic() - t
        if r.returncode != 0 or not r.stdout.strip():
            return None, f"optimizer failed (exit {r.returncode}): {r.stderr.strip()[:200]}", dt
        out = os.path.join(outdir, p["name"].replace(os.sep, "_"))
        open(out, "w", encoding="utf-8").write(r.stdout)
        return out, None, dt

    def check(self, p, opt, data):
        a, ea = self.orig[(p["path"], data)]
        if a is None:
            return "SKIP", ea, None
        b, eb = self.run(opt, data)
        if b is None:
            return "DEFECT", "optimized program errors: " + eb, (a["cycles"], None)
        st, detail = C.compare(a, b, p["ordered"], p["types"], None, p["cutoff"])
        if st == "DEFECT" and p["ordered"] and p["inst"]:
            key = (p["inst"], data)
            if key not in self.keyed:
                self.keyed[key] = vm.run(p["inst"], data)[0]
            k = self.keyed[key]
            if k is not None:
                st, detail = C.compare(a, b, p["ordered"], p["types"], k["rows"], p["cutoff"])
        return st, detail, (a["cycles"], b["cycles"])

    def bench(self, optimizer, label):
        t0 = time.monotonic()
        outdir = tempfile.mkdtemp(dir=self.work, prefix="opt_")
        with ThreadPoolExecutor(min(4, self.jobs)) as ex:  # like ./evaluate: keep optimizer timing honest
            opts = list(ex.map(lambda p: self.optimize(optimizer, p, outdir), self.progs))
        jobs = [(i, d) for i, (p, o) in enumerate(zip(self.progs, opts)) if o[0] for d in p["data"]]
        jobs.sort(key=lambda j: -os.path.getsize(j[1]))
        with ThreadPoolExecutor(self.jobs) as ex:
            res = list(ex.map(lambda j: self.check(self.progs[j[0]], opts[j[0]][0], j[1]), jobs))
        per = {}
        for p, (opt, err, dt) in zip(self.progs, opts):
            per[p["name"]] = {"tier": p["tier"], "opt_s": round(dt, 3), "speedup": None, "defects": 0,
                              "skipped": 0, "orig_cycles": 0, "opt_cycles": 0, "datasets": {}, "problems": []}
            if err:
                per[p["name"]]["defects"] += 1
                per[p["name"]]["problems"].append(["-", err])
        for (i, d), (st, detail, cyc) in zip(jobs, res):
            e = per[self.progs[i]["name"]]
            dn = rel(d)
            if st == "SKIP":
                e["skipped"] += 1
                e["datasets"][dn] = {"orig": None, "opt": None, "status": "SKIP"}
                continue
            e["datasets"][dn] = {"orig": cyc[0], "opt": cyc[1], "status": st}
            if st == "DEFECT":
                e["defects"] += 1
                e["problems"].append([dn, detail])
            else:
                e["orig_cycles"] += cyc[0]
                e["opt_cycles"] += cyc[1]
        for e in per.values():
            e["speedup"] = geomean([v["orig"] / v["opt"] for v in e["datasets"].values()
                                    if v["status"] in ("OK", "WARN") and v["opt"]])
        tiers = {}
        for t in TIERS + ("all",):
            es = [e for e in per.values() if t == "all" or e["tier"] == t]
            if not es:
                continue
            ex_sp = []  # speedup on each program's hand-written data.json only
            for e in es:
                hw = [v for k, v in e["datasets"].items() if not k.startswith(os.path.join("tests", "data"))]
                ex_sp += [v["orig"] / v["opt"] for v in hw if v["status"] in ("OK", "WARN") and v["opt"]]
            g = geomean([e["speedup"] for e in es])
            tiers[t] = {"programs": len(es), "geomean": round(g, 4) if g else None,
                        "geomean_handwritten_data": round(geomean(ex_sp), 4) if geomean(ex_sp) else None,
                        "defects": sum(e["defects"] for e in es),
                        "pairs_checked": sum(len(e["datasets"]) - e["skipped"] for e in es),
                        "pairs_skipped": sum(e["skipped"] for e in es),
                        "orig_cycles": sum(e["orig_cycles"] for e in es),
                        "opt_cycles": sum(e["opt_cycles"] for e in es),
                        "max_opt_s": round(max(e["opt_s"] for e in es), 3)}
        for e in per.values():
            if e["speedup"]:
                e["speedup"] = round(e["speedup"], 4)
        return {"optimizer": rel(optimizer) if optimizer.startswith(REPO) else optimizer, "label": label,
                "wall_s": round(time.monotonic() - t0, 2), "tiers": tiers, "programs": per}


def report(r, quiet=False):
    print(f"== {r['label']}: {r['optimizer']}  ({r['wall_s']} s)")
    if not quiet:
        print(f"{'program':58} {'tier':8} {'speedup':>8} {'def':>4} {'skip':>4} {'orig':>11} {'opt':>11} {'opt_s':>6}")
        for n, e in r["programs"].items():
            sp = f"{e['speedup']:.2f}x" if e["speedup"] else "-"
            print(f"{n:58} {e['tier']:8} {sp:>8} {e['defects']:>4} {e['skipped']:>4} "
                  f"{e['orig_cycles']:>11} {e['opt_cycles']:>11} {e['opt_s']:>6.2f}")
            for d, det in e["problems"][:3]:
                print(f"    DEFECT {d}: {det}")
    print(f"{'tier':9} {'progs':>5} {'geomean':>8} {'gm(hw)':>7} {'defects':>7} {'checked':>7} {'skipped':>7} "
          f"{'orig_cycles':>12} {'opt_cycles':>12} {'max_opt_s':>9}")
    for t, v in r["tiers"].items():
        g = f"{v['geomean']:.2f}x" if v["geomean"] else "-"
        h = f"{v['geomean_handwritten_data']:.2f}x" if v["geomean_handwritten_data"] else "-"
        print(f"{t:9} {v['programs']:>5} {g:>8} {h:>7} {v['defects']:>7} {v['pairs_checked']:>7} "
              f"{v['pairs_skipped']:>7} {v['orig_cycles']:>12} {v['opt_cycles']:>12} {v['max_opt_s']:>9.2f}")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("optimizer", nargs="?")
    ap.add_argument("--baselines", action="store_true", help="identity + hand-opt -> tests/baselines.json")
    ap.add_argument("--out", help="write the JSON report here")
    ap.add_argument("-j", type=int, default=max(4, (os.cpu_count() or 4)))
    ap.add_argument("-q", action="store_true", help="tier summary only")
    a = ap.parse_args(argv)
    if not a.optimizer and not a.baselines:
        ap.print_help(sys.stderr)
        return 2
    t0 = time.monotonic()
    ensure_data()
    work = tempfile.mkdtemp(prefix="minivm_bench_")
    try:
        b = Bench(a.j, work)
        b.run_originals()
        if a.baselines:
            runs = [b.bench(IDENTITY, "identity"), b.bench(HAND, "hand-opt")]
        else:
            opt = a.optimizer if os.sep not in a.optimizer else os.path.abspath(a.optimizer)
            runs = [b.bench(opt, "optimizer")]
        for r in runs:
            report(r, a.q)
        wall = round(time.monotonic() - t0, 2)
        print(f"bench wall time {wall} s")
        out = a.out or (os.path.join(REPO, "tests", "baselines.json") if a.baselines else None)
        if out:
            orig = {p["name"]: {"tier": p["tier"],
                                "cycles": {rel(d): (b.orig[(p["path"], d)][0] or {}).get("cycles")
                                           for d in p["data"]}} for p in b.progs}
            doc = {"v": 1, "note": "orig = ORIGINAL program cycles per dataset (null = original errors on it); "
                                   "speedup = orig/opt, geomean over datasets then programs",
                   "original_cycles": orig, "runs": {r["label"]: r for r in runs}, "wall_s": wall}
            if not a.baselines:
                doc = runs[0]
                doc["original_cycles"] = orig
            with open(out, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=1, sort_keys=False, ensure_ascii=False)
                f.write("\n")
            print(f"wrote {out}")
        return 1 if any(r["tiers"]["all"]["defects"] for r in runs) else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
