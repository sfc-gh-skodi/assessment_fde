#!/usr/bin/env python3
"""Run two MiniVM programs on the same data; report cycles and whether results match.

  cmp.py ORIG.mini OPT.mini [DATA.json ...]   compare one pair (default data: examples/data.json)
  cmp.py --all [DATA.json ...]                compare every examples/programs/qNNNN.mini
                                              with qNNNN.opt.mini next to this script

Match rules (one-pager): same ncols; numbers within 1e-6 relative; NULL == NULL;
other values exact. Row order is compared unless --unordered. A pair where the
original errors is SKIP (anything goes). Exit 1 if any pair MISMATCHes or the
optimized program errors where the original didn't.

Paths are relative to this file; set MINIVM to override the VM binary.
"""
import json, os, subprocess, sys
from decimal import Decimal, InvalidOperation

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "minivm-takehome"))
VM = os.environ.get("MINIVM", os.path.join(ROOT, "bin", "minivm"))
DEFAULT_DATA = os.path.join(ROOT, "examples", "data.json")
REL_TOL = Decimal("1e-6")


def run(prog, data):
    r = subprocess.run([VM, prog, data], capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr.strip()
    return json.loads(r.stdout), None


def as_num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, str):
        try:
            return Decimal(v)
        except InvalidOperation:
            return None
    return None


def same_value(a, b):
    if a == b:
        return True
    na, nb = as_num(a), as_num(b)
    if na is None or nb is None:
        return False
    if na == nb:
        return True
    return abs(na - nb) <= REL_TOL * max(abs(na), abs(nb))


def same_rows(ra, rb, ordered):
    if len(ra) != len(rb):
        return False
    if not ordered:
        # canonical sort; numeric strings normalized so "2.0" and "2.00" line up
        key = lambda row: json.dumps([str(as_num(v).normalize()) if as_num(v) is not None else v for v in row])
        ra, rb = sorted(ra, key=key), sorted(rb, key=key)
    return all(len(x) == len(y) and all(same_value(p, q) for p, q in zip(x, y)) for x, y in zip(ra, rb))


def compare(orig, opt, data, ordered=True):
    """Return (status, orig_cycles, opt_cycles, detail). status: MATCH|MISMATCH|SKIP|OPT_ERROR."""
    a, ea = run(orig, data)
    if a is None:
        return "SKIP", None, None, "original errors: " + ea
    b, eb = run(opt, data)
    if b is None:
        return "OPT_ERROR", a["cycles"], None, eb
    if a["ncols"] != b["ncols"]:
        return "MISMATCH", a["cycles"], b["cycles"], f"ncols {a['ncols']} vs {b['ncols']}"
    if not same_rows(a["rows"], b["rows"], ordered):
        return "MISMATCH", a["cycles"], b["cycles"], f"rows differ ({len(a['rows'])} vs {len(b['rows'])} rows)"
    return "MATCH", a["cycles"], b["cycles"], ""


def main(argv):
    ordered = "--unordered" not in argv
    argv = [x for x in argv if x != "--unordered"]
    if argv and argv[0] == "--all":
        datas = argv[1:] or [DEFAULT_DATA]
        progs = sorted(f for f in os.listdir(os.path.join(ROOT, "examples", "programs")) if f.endswith(".mini"))
        pairs = [(os.path.join(ROOT, "examples", "programs", f), os.path.join(HERE, f[:-5] + ".opt.mini")) for f in progs]
    elif len(argv) >= 2:
        pairs, datas = [(argv[0], argv[1])], argv[2:] or [DEFAULT_DATA]
    else:
        print(__doc__, file=sys.stderr)
        return 2

    bad, speedups = 0, []
    print(f"{'program':<16} {'data':<20} {'status':<10} {'orig':>8} {'opt':>8} {'speedup':>8}")
    for orig, opt in pairs:
        name = os.path.basename(orig)
        if not os.path.exists(opt):
            print(f"{name:<16} {'-':<20} {'NO_OPT':<10}")
            continue
        for data in datas:
            st, ca, cb, detail = compare(orig, opt, data, ordered)
            sp = f"{ca / cb:.2f}x" if ca and cb else "-"
            if ca and cb:
                speedups.append(ca / cb)
            print(f"{name:<16} {os.path.basename(data):<20} {st:<10} {ca or '-':>8} {cb or '-':>8} {sp:>8} {detail}")
            bad += st in ("MISMATCH", "OPT_ERROR")
    if speedups:
        g = 1.0
        for s in speedups:
            g *= s
        print(f"\npairs={len(speedups)} defects={bad} geomean_speedup={g ** (1 / len(speedups)):.2f}x")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
