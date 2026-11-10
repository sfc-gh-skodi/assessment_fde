#!/usr/bin/env python3
"""Test the tester: run eval-proto.py against every fake optimizer in fake_opt.py.

  meta_eval.py [MODE ...]       default: all modes

Buggy fake + eval exit 1  -> CAUGHT        Buggy fake + eval exit 0  -> MISSED
Honest fake + eval exit 0 -> OK            Honest fake + eval exit 1 -> FALSE ALARM

For every MISSED / FALSE ALARM it gathers evidence by re-running the original and the
fake program on every dataset: how many programs the fake changed, on how many
datasets the output differed in order only (same multiset), and on how many it was
identical. The report is printed and written to meta_report.md.
"""
import glob, importlib.util, os, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ev", os.path.join(HERE, "eval-proto.py"))
ev = importlib.util.module_from_spec(spec); spec.loader.exec_module(ev)
import fake_opt as F

PROGS = sorted(glob.glob(os.path.join(ev.PROGS, "*.mini")))
DATA = ev.datasets(ev.DEFAULT_DATA)


def wrapper(tmp, mode):
    p = os.path.join(tmp, mode + ".sh")
    with open(p, "w") as f:
        f.write(f'#!/bin/sh\nexec python3 "{os.path.join(HERE, "fake_opt.py")}" {mode} "$@"\n')
    os.chmod(p, 0o755)
    return p


def evidence(opt_cmd, tmp, mode):
    """Per program: changed?, and counts of identical / order-only / differs / opt-error datasets."""
    rows = []
    for prog in PROGS:
        out = os.path.join(tmp, f"{mode}_{os.path.basename(prog)}")
        open(out, "w").write(subprocess.run([opt_cmd, prog, ev.SCHEMA], capture_output=True, text=True).stdout)
        changed = F.emit(F.parse(prog)) != F.emit(F.parse(out))

        def one(d):
            a, _ = ev.vm(prog, d)
            if a is None:
                return "skip"
            b, _ = ev.vm(out, d)
            if b is None:
                return "opt_error"
            if a["rows"] == b["rows"]:
                return "identical"
            ordered = len(a["rows"]) == len(b["rows"]) and all(ev.row_close(x, y) for x, y in zip(a["rows"], b["rows"]))
            if ordered:
                return "within_tolerance"
            return "order_only" if ev.same_multiset(a["rows"], b["rows"]) else "differs"
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 8) as ex:
            res = list(ex.map(one, DATA))
        rows.append((os.path.basename(prog), changed, {k: res.count(k) for k in set(res)}))
    return rows


def main(argv):
    modes = argv or list(F.MODES)
    t0 = time.monotonic()
    report, tally = [], {"CAUGHT": 0, "MISSED": 0, "OK": 0, "FALSE ALARM": 0}
    with tempfile.TemporaryDirectory() as tmp:
        for mode in modes:
            kind, desc, _ = F.MODES[mode]
            cmd = wrapper(tmp, mode)
            r = subprocess.run([sys.executable, os.path.join(HERE, "eval-proto.py"), cmd, "--quiet"],
                               capture_output=True, text=True)
            summary = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()
            flagged = r.returncode != 0
            verdict = ("CAUGHT" if flagged else "MISSED") if kind == "buggy" else ("FALSE ALARM" if flagged else "OK")
            tally[verdict] += 1
            line = f"{verdict:<12} {mode:<14} {kind:<6} {desc}\n             eval: {summary}"
            if verdict in ("MISSED", "FALSE ALARM"):
                if verdict == "FALSE ALARM":
                    line += "\n             first defects: " + " | ".join(r.stdout.strip().splitlines()[:3])
                for name, changed, counts in evidence(cmd, tmp, mode):
                    line += f"\n             {name}: {'changed' if changed else 'unchanged'}  " + \
                            "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            print(line, flush=True)
            report.append(line)
    total = f"buggy: caught {tally['CAUGHT']}, missed {tally['MISSED']} | honest: ok {tally['OK']}, " \
            f"false alarms {tally['FALSE ALARM']} | time {time.monotonic() - t0:.0f}s"
    print("\n" + total)
    with open(os.path.join(HERE, "meta_report.md"), "w") as f:
        f.write("# eval-proto.py vs fake optimizers\n\n```\n" + "\n".join(report) + "\n\n" + total + "\n```\n")
    return 0 if tally["MISSED"] == tally["FALSE ALARM"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
