#!/usr/bin/env python3
"""./evaluate OPTIMIZER [--seed S] [--quick] [--json OUT] [--keep DIR] [-v]

Tests any optimizer with the CLI `OPTIMIZER program.mini schema.json`. Exit 0 if it
finds no defects, 1 if it finds any (2 on usage errors).

Corpus (deterministic per seed):
  programs: examples/programs, tests/cases/** (if present), and generated legacy-style
            programs over the example schema and over 2 random schemas
  data:     examples/data.json + constraint-respecting tricky datasets per schema
            (small / medium / large), literals harvested from the programs
A (program, dataset) pair is SKIPPED if the original errors (anything goes);
otherwise it is a DEFECT if the optimizer fails / prints nothing / takes > 1 s, the
optimized program errors, or results differ (rules in evaluator/compare.py).
A watchdog stops starting new checks at 100 s so the verdict lands within 2 minutes.
"""
import argparse
import glob
import json
import os
import random
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from evaluator import compare as C          # noqa: E402
from evaluator import datagen, progen, vm   # noqa: E402

REPO = vm.REPO
EX = os.path.join(vm.BUNDLE, "examples")
OPT_LIMIT_S = 1.0
WATCHDOG_S = 100.0


def build_corpus(work, seed, quick):
    """-> list of (schema_path, [program paths], [data paths])"""
    rng = random.Random(seed)
    groups = []
    ex_schema = json.load(open(os.path.join(EX, "schema.json")))
    fixed = sorted(glob.glob(os.path.join(EX, "programs", "*.mini")))
    fixed += sorted(glob.glob(os.path.join(REPO, "tests", "cases", "**", "*.mini"), recursive=True))
    fixed += sorted(glob.glob(os.path.join(REPO, "tests", "regressions", "*.mini")))
    n_gen = 20 if quick else 60
    sizes = (8, 4, 1) if quick else (14, 7, 2)
    schemas = [("example", ex_schema, fixed, [os.path.join(EX, "data.json")])]
    for k in range(0 if quick else 2):
        sch = progen.random_schema(random.Random(seed * 100 + k), name=f"g{k}")
        schemas.append((f"rand{k}", sch, [], []))
    for name, sch, progs, data in schemas:
        d = os.path.join(work, name)
        os.makedirs(d, exist_ok=True)
        if name != "example":          # give the random schema stats: one medium dataset -> --schema
            p = os.path.join(d, "seed.json")
            json.dump(datagen.generate(sch, "medium", seed), open(p, "w"), ensure_ascii=False)
            s2, err = vm.schema_of(p)
            if s2 is None:
                continue
            sch = s2
            data = [p]
        sp = os.path.join(d, "schema.json")
        json.dump(sch, open(sp, "w"), ensure_ascii=False)
        gen = []
        count = n_gen if name == "example" else n_gen // 3
        for i in range(count):
            text = progen.gen_program(sch, random.Random(rng.random()))
            p = os.path.join(d, f"gen_{name}_{i:03d}.mini")
            open(p, "w").write(text)
            gen.append(p)
        lits = datagen.harvest(open(p).read() for p in progs + gen)
        for size, n in zip(("small", "medium", "large"), sizes):
            for i in range(n):
                p = os.path.join(d, f"{size}_{i}.json")
                json.dump(datagen.generate(sch, size, seed * 1000 + i + {"small": 0, "medium": 100, "large": 200}[size],
                                           lits), open(p, "w"), ensure_ascii=False)
                data.append(p)
        groups.append((sp, progs + gen, data))
    return groups


def run_optimizer(optimizer, prog, schema, outdir):
    t = time.monotonic()
    try:
        r = __import__("subprocess").run([optimizer, prog, schema], capture_output=True, text=True,
                                         timeout=10 * OPT_LIMIT_S)
    except Exception as e:  # timeout or not executable
        return None, f"optimizer failed: {e}", time.monotonic() - t
    dt = time.monotonic() - t
    if r.returncode != 0 or not r.stdout.strip():
        return None, f"optimizer failed (exit {r.returncode}): {r.stderr.strip()[:200]}", dt
    out = os.path.join(outdir, os.path.basename(prog))
    open(out, "w").write(r.stdout)
    if dt > OPT_LIMIT_S:
        return out, f"optimizer took {dt:.2f} s (> {OPT_LIMIT_S} s)", dt
    return out, None, dt


class Program:
    def __init__(self, path, schema_path, schema, work):
        self.path, self.schema_path = path, schema_path
        self.name = os.path.relpath(path, REPO) if path.startswith(REPO) else os.path.basename(path)
        self.prog = C.parse(open(path).read())
        self.ordered = C.output_ordered(self.prog)
        self.types = C.out_types(self.prog, schema)
        self.cutoff = any(op in ("TOPK", "SLICE") for op, _ in self.prog)
        self.inst = None
        if self.ordered:
            text = C.instrument(self.prog)
            if text:
                self.inst = os.path.join(work, f"keys_{len(os.listdir(work))}_{os.path.basename(path)}")
                open(self.inst, "w").write(text)


def check(p, opt, data):
    a, ea = vm.run(p.path, data)
    if a is None:
        return "SKIP", ea, None
    b, eb = vm.run(opt, data)
    if b is None:
        return "DEFECT", "optimized program errors: " + eb, (a["cycles"], None)
    keyed = None
    st, detail = C.compare(a, b, p.ordered, p.types, None, p.cutoff)
    if st == "DEFECT" and p.ordered and p.inst:
        k, _ = vm.run(p.inst, data)
        if k is not None:
            keyed = k["rows"]
            st, detail = C.compare(a, b, p.ordered, p.types, keyed, p.cutoff)
    return st, detail, (a["cycles"], b["cycles"])


def save_repro(keep, p, opt, data, detail):
    d = os.path.join(keep, f"{os.path.basename(p.path)}__{os.path.basename(data)}".replace(".", "_"))
    os.makedirs(d, exist_ok=True)
    shutil.copy(p.path, os.path.join(d, "orig.mini"))
    if opt:
        shutil.copy(opt, os.path.join(d, "opt.mini"))
    if data:
        shutil.copy(data, os.path.join(d, "data.json"))
    shutil.copy(p.schema_path, os.path.join(d, "schema.json"))
    open(os.path.join(d, "defect.txt"), "w").write(detail + "\n")


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("optimizer")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--quick", action="store_true", help="smaller corpus (~10 s)")
    ap.add_argument("--json", help="write a machine-readable report here")
    ap.add_argument("--keep", default=os.path.join(os.getcwd(), "eval_out"), help="defect repro directory")
    ap.add_argument("-v", action="store_true")
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    a = ap.parse_args(argv)
    optimizer = a.optimizer if os.sep not in a.optimizer else os.path.abspath(a.optimizer)
    t0 = time.monotonic()
    work = tempfile.mkdtemp(prefix="minivm_eval_")
    try:
        groups = build_corpus(work, a.seed, a.quick)
        progs = []
        instdir = os.path.join(work, "inst")
        os.makedirs(instdir, exist_ok=True)
        for sp, paths, data in groups:
            sch = json.load(open(sp))
            for pth in paths:
                progs.append((Program(pth, sp, sch, instdir), data))
        optdir = os.path.join(work, "opt")
        os.makedirs(optdir, exist_ok=True)
        # optimizer calls first, at most 4 at a time, so machine load can't cause a false "> 1 s"
        def call(k):
            d = os.path.join(optdir, str(k))
            os.makedirs(d, exist_ok=True)
            p = progs[k][0]
            return run_optimizer(optimizer, p.path, p.schema_path, d)

        with ThreadPoolExecutor(max_workers=4) as ex:
            opts = list(ex.map(call, range(len(progs))))
        defects, warns = [], []
        checked = skipped = 0
        per_prog = {}
        jobs = []
        max_opt = 0.0
        for (p, data), (opt, err, dt) in zip(progs, opts):
            max_opt = max(max_opt, dt or 0)
            per_prog[p.name] = {"opt_s": round(dt or 0, 3), "orig": 0, "opt": 0, "checked": 0, "defects": 0}
            if err:
                defects.append((p, None, err, opt))
                per_prog[p.name]["defects"] += 1
            if opt is None:
                continue
            jobs += [(p, opt, d) for d in data]
        stopped = False

        def job(j):
            if time.monotonic() - t0 > WATCHDOG_S:
                return j, ("TIMEOUT", "watchdog", None)
            return j, check(*j)

        with ThreadPoolExecutor(max_workers=os.cpu_count() or 8) as ex:
            results = list(ex.map(job, jobs))
        for (p, opt, d), (st, detail, cyc) in results:
            if st == "TIMEOUT":
                stopped = True
                continue
            if st == "SKIP":
                skipped += 1
                continue
            checked += 1
            pp = per_prog[p.name]
            pp["checked"] += 1
            if cyc and cyc[1] is not None:
                pp["orig"] += cyc[0]
                pp["opt"] += cyc[1]
            if st == "DEFECT":
                defects.append((p, d, detail, opt))
                pp["defects"] += 1
            elif st == "WARN":
                warns.append((p, d, detail))
        for p, d, detail, opt in defects[:50]:
            save_repro(a.keep, p, opt, d, detail)
        elapsed = time.monotonic() - t0
        for p, d, detail, _ in defects[:20]:
            print(f"DEFECT  {p.name}  {os.path.basename(d) if d else '-'}  {detail}")
        if len(defects) > 20:
            print(f"... {len(defects) - 20} more defects")
        if a.v:
            for p, d, detail in warns[:10]:
                print(f"WARN    {p.name}  {os.path.basename(d)}  {detail}")
        import math
        sp = [v["orig"] / v["opt"] for v in per_prog.values() if v["opt"] and v["orig"]]
        geo = math.exp(sum(map(math.log, sp)) / len(sp)) if sp else 1.0
        n_data = sum(len(g[2]) for g in groups)
        print(f"programs={len(progs)} datasets={n_data} checked={checked} skipped={skipped} warns={len(warns)} "
              f"defects={len(defects)} max_opt={max_opt:.2f}s time={elapsed:.1f}s geomean_speedup={geo:.2f}x"
              + (" (watchdog stopped early)" if stopped else ""))
        if defects:
            print(f"repros saved under {a.keep}")
        if a.json:
            json.dump({"v": 1, "seed": a.seed, "programs": len(progs), "checked": checked, "skipped": skipped,
                       "warns": len(warns), "defects": len(defects), "wall_s": round(elapsed, 1),
                       "max_opt_s": round(max_opt, 3), "geomean_speedup": round(geo, 3),
                       "per_program": per_prog,
                       "defect_list": [[p.name, os.path.basename(d) if d else "-", det] for p, d, det, _ in defects]},
                      open(a.json, "w"), indent=1)
        return 1 if defects else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
