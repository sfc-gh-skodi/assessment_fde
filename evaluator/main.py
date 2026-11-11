#!/usr/bin/env python3
"""./evaluate OPTIMIZER [--seed S] [--quick] [--json OUT] [--keep DIR] [-v]

Tests any optimizer with the CLI `OPTIMIZER program.mini schema.json`. Exit 0 if it
finds no defects, 1 if it finds any (2 on usage errors).

Corpus (deterministic per seed):
  programs: examples/programs, tests/cases/** and tests/regressions (if present), and
            generated legacy-style programs over the example schema and (full run) over
            2 random schemas; a generated program is kept only if its original gives
            rows on at least one dataset
  data:     examples/data.json + constraint-respecting tricky datasets per schema
            (small / medium / large), literals harvested from the programs
A (program, dataset) pair is SKIPPED if the original errors (anything goes);
otherwise it is a DEFECT if the optimizer fails / prints nothing / takes > 1 s, the
optimized program errors, or results differ (rules in evaluator/compare.py).
Fast path: an optimized program that is the original up to register names and
opcode/keyword case is the same program, so its VM runs are skipped.
Watchdogs stop new optimizer calls at 60 s and new checks at 100 s, so the verdict
lands within 2 minutes. Writes only to a temp dir, plus defect repros under --keep.
"""
import argparse
import glob
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from evaluator import compare as C          # noqa: E402
from evaluator import datagen, progen, vm   # noqa: E402

REPO = vm.REPO
EX = os.path.join(vm.BUNDLE, "examples")
OPT_LIMIT_S = 1.0
OPT_KILL_S = 2.5
OPT_WATCHDOG_S = 60.0
WATCHDOG_S = 100.0
WORKERS = min(16, max(4, os.cpu_count() or 8))


def pmap(fn, items, workers=WORKERS):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def build_corpus(work, seed, quick):
    """-> list of (name, schema_path, schema, [fixed program paths], [generated paths], [data paths])"""
    rng = random.Random(seed)
    ex_schema = json.load(open(os.path.join(EX, "schema.json")))
    fixed = sorted(glob.glob(os.path.join(EX, "programs", "*.mini")))
    fixed += sorted(glob.glob(os.path.join(REPO, "tests", "cases", "**", "*.mini"), recursive=True))
    fixed += sorted(glob.glob(os.path.join(REPO, "tests", "regressions", "*.mini")))
    n_gen = 24 if quick else 60
    sizes = (6, 5, 2, 0) if quick else (14, 7, 3, 1)
    schemas = [("example", ex_schema, fixed, [os.path.join(EX, "data.json")])]
    for k in range(0 if quick else 2):
        sch = progen.random_schema(random.Random(seed * 100 + k), name=f"g{k}")
        schemas.append((f"rand{k}", sch, [], []))
    groups = []
    for name, sch, progs, data in schemas:
        d = os.path.join(work, name)
        os.makedirs(d, exist_ok=True)
        if name != "example":          # give the random schema stats: one medium dataset -> --schema
            p = os.path.join(d, "seed.json")
            json.dump(datagen.generate(sch, "medium", seed), open(p, "w"), ensure_ascii=False)
            s2, err = vm.schema_of(p)
            if s2 is None:
                print(f"note: random schema {name} rejected by bin/minivm: {err}", file=sys.stderr)
                continue
            sch = s2
            data = [p]
        sp = os.path.join(d, "schema.json")
        json.dump(sch, open(sp, "w"), ensure_ascii=False)
        gen = []
        count = n_gen if name == "example" else n_gen // 3
        for i in range(int(count * 1.5)):          # spares replace programs that never give rows
            text = progen.gen_program(sch, random.Random(rng.random()), progen.IDIOMS[i % len(progen.IDIOMS)])
            p = os.path.join(d, f"gen_{name}_{i:03d}.mini")
            open(p, "w").write(text)
            gen.append(p)
        lits = datagen.harvest(open(p).read() for p in progs + gen)
        for size, n in zip(("small", "medium", "large", "xlarge"), sizes):
            for i in range(n):
                p = os.path.join(d, f"{size}_{i}.json")
                json.dump(datagen.generate(sch, size, seed * 1000 + i + {"small": 0, "medium": 100, "large": 200, "xlarge": 300}[size],
                                           lits), open(p, "w"), ensure_ascii=False)
                data.append(p)
        groups.append((name, sp, sch, progs, gen[:], data, count))
    return groups


def run_optimizer(optimizer, prog, schema, outdir):
    t = time.monotonic()
    try:
        r = subprocess.run([optimizer, prog, schema], capture_output=True, text=True, timeout=OPT_KILL_S)
    except subprocess.TimeoutExpired:
        return None, f"optimizer took > {OPT_KILL_S} s (killed)", time.monotonic() - t
    except Exception as e:  # not executable, ...
        return None, f"optimizer failed: {e}", time.monotonic() - t
    dt = time.monotonic() - t
    if r.returncode != 0 or not r.stdout.strip():
        return None, f"optimizer failed (exit {r.returncode}{', empty output' if not r.stdout.strip() else ''}): " \
                     f"{r.stderr.strip()[:200]}", dt
    out = os.path.join(outdir, os.path.basename(prog))
    with open(out, "w") as f:
        f.write(r.stdout)
    return out, None, dt


class Program:
    def __init__(self, path, schema_path, schema, work, generated):
        self.path, self.schema_path, self.generated = path, schema_path, generated
        self.name = os.path.relpath(path, REPO) if path.startswith(REPO + os.sep) else os.path.basename(path)
        self.text = open(path).read()
        self.prog = C.parse(self.text)
        self.canon = C.canon_text(self.prog)
        self.ordered = C.output_ordered(self.prog)
        self.types = C.out_types(self.prog, schema)
        self.cutoff = any(op in ("TOPK", "SLICE") for op, _ in self.prog)
        self.inst = None
        self.inst_full = None
        self.work = work
        self.orig = {}          # dataset -> (result, error)

    def _inst(self, no_cut):
        text = C.instrument(self.prog, no_cut=no_cut)
        if not text:
            return ""
        path = os.path.join(self.work, f"keys{'_full' if no_cut else ''}_{len(os.listdir(self.work))}_"
                                       f"{os.path.basename(self.path)}")
        with open(path, "w") as f:
            f.write(text)
        return path

    def inst_path(self, no_cut=False):
        """instrumented original (output + sort keys); no_cut: with TOPK/SLICE cut-offs removed."""
        if not self.ordered:
            return None
        if no_cut:
            if self.inst_full is None:
                self.inst_full = self._inst(True)
            return self.inst_full or None
        if self.inst is None:
            self.inst = self._inst(False)
        return self.inst or None


def check(p, opt, data):
    a, ea = p.orig[data]
    if a is None:
        return "SKIP", ea, None
    b, eb = vm.run(opt, data)
    if b is None:
        return "DEFECT", "optimized program errors: " + eb, (a["cycles"], None)
    st, detail = C.compare(a, b, p.ordered, p.types, None, p.cutoff)
    if st == "DEFECT" and p.ordered and p.inst_path():
        k, _ = vm.run(p.inst_path(), data)
        full = None
        if p.cutoff and len(a["rows"]) == len(b["rows"]) and p.inst_path(True):
            f, _ = vm.run(p.inst_path(True), data)
            full = f["rows"] if f is not None else None
        if k is not None:
            st, detail = C.compare(a, b, p.ordered, p.types, k["rows"], p.cutoff, full)
    return st, detail, (a["cycles"], b["cycles"])


def save_repro(keep, p, opt, data, detail):
    d = os.path.join(keep, f"{os.path.basename(p.path)}__{os.path.basename(data) if data else 'opt'}".replace(".", "_"))
    os.makedirs(d, exist_ok=True)
    shutil.copy(p.path, os.path.join(d, "orig.mini"))
    if opt:
        shutil.copy(opt, os.path.join(d, "opt.mini"))
    if data:
        shutil.copy(data, os.path.join(d, "data.json"))
    shutil.copy(p.schema_path, os.path.join(d, "schema.json"))
    with open(os.path.join(d, "defect.txt"), "w") as f:
        f.write(detail + "\n")


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("optimizer")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--quick", action="store_true", help="smaller corpus (~5 s)")
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
        return evaluate(a, optimizer, work, t0)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def evaluate(a, optimizer, work, t0):
    groups = build_corpus(work, a.seed, a.quick)
    instdir = os.path.join(work, "inst")
    os.makedirs(instdir, exist_ok=True)

    # 1. run every original once per dataset; keep generated programs that give rows somewhere
    progs = []          # (Program, data)
    dropped = 0
    for name, sp, sch, fixed, gen, data, want in groups:
        cands = [(Program(x, sp, sch, instdir, False), data) for x in fixed]
        cands += [(Program(x, sp, sch, instdir, True), data) for x in gen]
        runs = pmap(lambda j: (j[0], j[1], vm.run(j[0].path, j[1])), [(p, d) for p, data_ in cands for d in data_])
        for p, d, r in runs:
            p.orig[d] = r
        kept = 0
        for p, data_ in cands:
            if p.generated:
                useful = any(r is not None and r["rows"] for r, _ in p.orig.values())
                if not useful or kept >= want:
                    dropped += not useful
                    continue
                kept += 1
            progs.append((p, data_))

    # 2. optimizer calls, at most 4 at a time so machine load can't cause a false "> 1 s"
    optdir = os.path.join(work, "opt")
    os.makedirs(optdir, exist_ok=True)

    def call(k):
        if time.monotonic() - t0 > OPT_WATCHDOG_S:
            return None, "NOT RUN", 0.0
        d = os.path.join(optdir, str(k))
        os.makedirs(d, exist_ok=True)
        p = progs[k][0]
        return run_optimizer(optimizer, p.path, p.schema_path, d)

    opts = pmap(call, range(len(progs)), workers=4)
    # anything over the limit is re-timed once, serially, on an otherwise idle evaluator
    for k, (out, err, dt) in enumerate(opts):
        if err is None and dt > OPT_LIMIT_S:
            p = progs[k][0]
            out2, err2, dt2 = run_optimizer(optimizer, p.path, p.schema_path, os.path.dirname(out))
            dt = min(dt, dt2) if err2 is None else dt
            opts[k] = (out, f"optimizer took {dt:.2f} s (> {OPT_LIMIT_S} s)" if dt > OPT_LIMIT_S else None, dt)

    defects, warns = [], []
    checked = skipped = fast = not_run = 0
    per_prog = {}
    jobs = []
    max_opt = 0.0
    for (p, data), (opt, err, dt) in zip(progs, opts):
        pp = per_prog[p.name] = {"opt_s": round(dt or 0, 3), "orig": 0, "opt": 0, "checked": 0, "defects": 0}
        if err == "NOT RUN":
            not_run += 1
            continue
        max_opt = max(max_opt, dt or 0)
        if err:
            defects.append((p, None, err, opt))
            pp["defects"] += 1
        if opt is None:
            continue
        same = C.canon_text(C.parse(open(opt).read())) == p.canon
        for d in data:
            r, _ = p.orig[d]
            if r is None:
                skipped += 1
            elif same:
                fast += 1
                checked += 1
                pp["checked"] += 1
                pp["orig"] += r["cycles"]
                pp["opt"] += r["cycles"]
            else:
                jobs.append((p, opt, d))
    stopped = [False]

    def job(j):
        if time.monotonic() - t0 > WATCHDOG_S:
            return j, ("TIMEOUT", "watchdog", None)
        return j, check(*j)

    for (p, opt, d), (st, detail, cyc) in pmap(job, jobs):
        if st == "TIMEOUT":
            stopped[0] = True
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
    order = {id(p): i for i, (p, _) in enumerate(progs)}
    defects.sort(key=lambda x: (order[id(x[0])], os.path.basename(x[1]) if x[1] else ""))
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
    sp = [v["orig"] / v["opt"] for v in per_prog.values() if v["opt"] and v["orig"]]
    geo = math.exp(sum(map(math.log, sp)) / len(sp)) if sp else 1.0
    n_data = sum(len(g[5]) for g in groups)
    note = (" (watchdog stopped early)" if stopped[0] else "") + (f" (optimizer not run on {not_run} programs: watchdog)" if not_run else "")
    print(f"programs={len(progs)} datasets={n_data} checked={checked} skipped={skipped} warns={len(warns)} "
          f"defects={len(defects)} max_opt={max_opt:.2f}s time={elapsed:.1f}s geomean_speedup={geo:.2f}x" + note)
    if a.v:
        print(f"  generated programs dropped (never give rows): {dropped}; fast-path (unchanged) checks: {fast}")
    if defects:
        print(f"repros saved under {a.keep}")
    if a.json:
        with open(a.json, "w") as f:
            json.dump({"v": 2, "seed": a.seed, "quick": a.quick, "programs": len(progs), "datasets": n_data,
                       "checked": checked, "skipped": skipped, "fast_path": fast, "dropped_generated": dropped,
                       "warns": len(warns), "defects": len(defects), "wall_s": round(elapsed, 1),
                       "max_opt_s": round(max_opt, 3), "geomean_speedup": round(geo, 3),
                       "watchdog": stopped[0] or bool(not_run), "per_program": per_prog,
                       "defect_list": [[p.name, os.path.basename(d) if d else "-", det] for p, d, det, _ in defects]},
                      f, indent=1)
    return 1 if defects else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
