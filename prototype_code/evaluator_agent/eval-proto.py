#!/usr/bin/env python3
"""Prototype evaluator.

  eval-proto.py OPTIMIZER [--data DIR_OR_FILE ...] [--quiet]

For each examples/programs/*.mini, runs `OPTIMIZER program.mini examples/schema.json`
once, then runs the original and the optimized program with bin/minivm on every
dataset (examples/data.json plus, by default, the generated table sets under
prototype_code/optimizer_agent/data/), and compares the results.

A (program, dataset) pair is:
  SKIPPED  the original errors on that dataset (anything goes)
  CHECKED  the original succeeds; then it is a DEFECT if
             - the optimizer fails, prints nothing, or takes > 1 s, or
             - the optimized program errors, or
             - ncols differ, or
             - the rows differ, where numbers (INT or NUM, compared exactly via
               Decimal) match within 1e-6 relative, NULL == NULL, and every other
               value must be equal. Rows are compared IN ORDER when the original
               program specifies its output order, else as a multiset.

Row-order rule: the original specifies order when a SORT/TOPK result reaches OUT.
A forward data-flow pass marks registers ORDERED (rows in program-specified order):
SORT/TOPK make one; GATHER keeps it through an ordered index, or through a
monotone index (IDX, IOTA, a join's left positions, GFIRST) applied to an ordered
column; joins keep the order of an ordered left key; GROUP/GALL over ordered keys
number groups in that order, so their aggregates are ordered; element-wise ops,
SLICE, FILL and IOTA keep their operand's order; LOAD is unordered (stored order
is the data's, not the program's). Output order matters if any OUT operand is ORDERED.
Known limit: ties on the sort keys are compared in order too (SORT is stable).

Prints checked, skipped, defects and wall time; exits 1 if any defect, else 0.
Independent of the optimizer code: only the CLI and bin/minivm cross the boundary.
"""
import glob, json, os, platform, re, subprocess, sys, tempfile, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
ROOT = os.path.join(REPO, "minivm-takehome")
VM_WRAPPER = os.path.join(ROOT, "bin", "minivm")


def native_vm():
    """The platform binary bin/minivm would exec (same output, ~4.6x faster: no shell + xattr per run)."""
    osn = {"darwin": "macos"}.get(platform.system().lower(), platform.system().lower())
    arch = {"arm64": "aarch64", "amd64": "x86_64"}.get(platform.machine().lower(), platform.machine().lower())
    ext = ".exe" if osn.startswith(("windows", "mingw", "msys", "cygwin")) else ""
    b = os.path.join(ROOT, "bin", f"minivm-{'windows' if ext else osn}-{arch}{ext}")
    if not os.access(b, os.X_OK):
        return VM_WRAPPER
    if osn == "macos":   # downloaded zips are quarantined; the wrapper clears this on every run
        subprocess.run(["xattr", "-d", "com.apple.quarantine", b], capture_output=True)
    return b


VM = os.environ.get("MINIVM") or native_vm()
PROGS = os.path.join(ROOT, "examples", "programs")
SCHEMA = os.path.join(ROOT, "examples", "schema.json")
DEFAULT_DATA = [os.path.join(ROOT, "examples", "data.json"),
                os.path.join(REPO, "prototype_code", "optimizer_agent", "data")]
OPT_LIMIT_S = 1.0
REL_TOL = Decimal("1e-6")
KEYWORDS = {"NULL", "TRUE", "FALSE", "ASC", "DESC", "NF", "NL", "NULLEQ"}


# ---------------- does the program specify its output order? ----------------
def parse_program(path):
    prog = []
    for line in open(path):
        code, q = "", False
        for ch in line:                      # strip ';' comments outside string literals
            if ch == "'":
                q = not q
            if ch == ";" and not q:
                break
            code += ch
        code = code.strip()
        if not code:
            continue
        parts = code.split(None, 1)
        ops, cur, q = [], "", False
        for ch in parts[1] if len(parts) > 1 else "":
            if ch == "'":
                q = not q
            if ch == "," and not q:
                ops.append(cur.strip()); cur = ""
            else:
                cur += ch
        if cur.strip():
            ops.append(cur.strip())
        prog.append((parts[0].upper(), ops))
    return prog


def reg(tok):
    t = tok.split()[0] if tok.split() else ""
    ok = t[:1].isalpha() or t[:1] == "_"
    return t if ok and all(c.isalnum() or c == "_" for c in t) and t.upper() not in KEYWORDS else None


def output_ordered(path):
    ordered, mono = set(), set()
    o = lambda t: reg(t) in ordered
    for op, a in parse_program(path):
        if op == "OUT":
            return any(o(t) for t in a)
        if op in ("HJOIN", "NLJOIN"):
            li, ri, lk = a[0], a[1], a[2]
            for d in (li, ri):
                ordered.discard(d); mono.discard(d)
            if o(lk):
                ordered.update({li, ri})
            if li != ri:
                mono.add(li)
            continue
        d, src = a[0], a[1:]
        if op in ("SORT", "TOPK"):
            is_o, is_m = True, False
        elif op == "GATHER":
            s, i = reg(src[0]), reg(src[1])
            is_o = i in ordered or (s in ordered and i in mono)
            is_m = s in mono and i in mono
        elif op == "LOAD":
            is_o, is_m = False, False
        elif op in ("IDX", "GFIRST"):
            is_o, is_m = (op == "GFIRST" and o(src[0])), True
        elif op == "IOTA":
            is_o, is_m = o(src[0]), True
        elif op == "SLICE":
            is_o, is_m = o(src[0]), reg(src[0]) in mono
        else:                                # element-wise, FILL, GROUP/GALL, aggregates, GID
            is_o, is_m = any(o(t) for t in src), False
        ordered.discard(d); mono.discard(d)
        if is_o:
            ordered.add(d)
        if is_m:
            mono.add(d)
    return False


# ---------------- comparison ----------------
NUM_TEXT = re.compile(r"-?\d+(\.\d+)?")   # the only way minivm prints an INT or NUM


def num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, str) and NUM_TEXT.fullmatch(v):
        return Decimal(v)
    return None


def close(a, b):
    if isinstance(a, bool) or isinstance(b, bool):   # JSON true/false never equal 1/0
        return type(a) is type(b) and a == b
    if a == b:
        return True
    na, nb = num(a), num(b)
    if na is None or nb is None:
        return False
    return na == nb or abs(na - nb) <= REL_TOL * max(abs(na), abs(nb))


def row_close(x, y):
    return len(x) == len(y) and all(close(p, q) for p, q in zip(x, y))


def canon(v):
    n = num(v)
    if n is not None:
        return (1, str(n.normalize()))  # "2.0" and "2.00" -> same key
    return (0, json.dumps(v, ensure_ascii=False))


def same_multiset(ra, rb):
    """Rows equal as a multiset, numbers within REL_TOL."""
    if len(ra) != len(rb):
        return False
    # fast path: exact after numeric normalization
    if Counter(tuple(map(canon, r)) for r in ra) == Counter(tuple(map(canon, r)) for r in rb):
        return True
    # tolerant path: sort, compare pairwise; then greedy matching as a fallback
    key = lambda r: [canon(v) for v in r]
    sa, sb = sorted(ra, key=key), sorted(rb, key=key)
    if all(row_close(x, y) for x, y in zip(sa, sb)):
        return True
    if len(ra) > 3000:
        return False
    unused = list(rb)
    for x in ra:
        for i, y in enumerate(unused):
            if row_close(x, y):
                del unused[i]
                break
        else:
            return False
    return True


# ---------------- running ----------------
def vm(prog, data):
    r = subprocess.run([VM, prog, data], capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stderr.strip() or f"exit {r.returncode}")
    return json.loads(r.stdout), None


def optimize(optimizer, prog, outdir):
    t = time.monotonic()
    try:
        r = subprocess.run([optimizer, prog, SCHEMA], capture_output=True, text=True, timeout=10 * OPT_LIMIT_S)
    except subprocess.TimeoutExpired:
        return None, f"optimizer timed out (> {10 * OPT_LIMIT_S:.0f} s)", None
    dt = time.monotonic() - t
    if r.returncode != 0 or not r.stdout.strip():
        return None, f"optimizer failed (exit {r.returncode}): {r.stderr.strip()[:200]}", dt
    out = os.path.join(outdir, os.path.basename(prog))
    with open(out, "w") as f:
        f.write(r.stdout)
    if dt > OPT_LIMIT_S:
        return out, f"optimizer took {dt:.2f} s (> {OPT_LIMIT_S} s)", dt
    return out, None, dt


def same_list(ra, rb):
    return len(ra) == len(rb) and all(row_close(x, y) for x, y in zip(ra, rb))


def check(orig, opt, data, ordered):
    a, ea = vm(orig, data)
    if a is None:
        return "SKIP", ea
    b, eb = vm(opt, data)
    if b is None:
        return "DEFECT", "optimized program errors: " + eb
    if a["ncols"] != b["ncols"]:
        return "DEFECT", f"ncols {a['ncols']} vs {b['ncols']}"
    if not same_multiset(a["rows"], b["rows"]):
        return "DEFECT", f"rows differ ({len(a['rows'])} vs {len(b['rows'])} rows)"
    if ordered and not same_list(a["rows"], b["rows"]):
        return "DEFECT", "same rows but different order (the original specifies order)"
    return "OK", f"{a['cycles']}->{b['cycles']}"


def datasets(args):
    out = []
    for p in args:
        out += sorted(glob.glob(os.path.join(p, "**", "*.json"), recursive=True)) if os.path.isdir(p) else [p]
    return out


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    optimizer = os.path.abspath(argv[0])
    quiet = "--quiet" in argv
    data_args = [a for a in argv[1:] if a != "--quiet" and a != "--data"]
    data = datasets(data_args or DEFAULT_DATA)
    progs = sorted(glob.glob(os.path.join(PROGS, "*.mini")))
    t0 = time.monotonic()
    checked = skipped = 0
    defects = []
    speed = []
    n_ordered = 0
    with tempfile.TemporaryDirectory() as tmp:
        # optimizer calls first, a few at a time, so machine load can't cause a false > 1 s
        with ThreadPoolExecutor(max_workers=4) as ex:
            opts = list(ex.map(lambda p: optimize(optimizer, p, tmp), progs))
        jobs = []
        for prog, (opt, err, dt) in zip(progs, opts):
            name = os.path.basename(prog)
            if err:
                defects.append((name, "-", err))
            if opt is None:
                continue
            ordered = output_ordered(prog)
            n_ordered += ordered
            jobs += [(name, prog, opt, d, ordered) for d in data]
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 8) as ex:
            results = list(ex.map(lambda j: (j, check(j[1], j[2], j[3], j[4])), jobs))
    for (name, _, _, d, _), (st, detail) in results:
        if st == "SKIP":
            skipped += 1
            continue
        checked += 1
        if st == "DEFECT":
            defects.append((name, os.path.relpath(d, REPO), detail))
        else:
            a, b = map(int, detail.split("->"))
            speed.append(a / b if b else 1.0)
    elapsed = time.monotonic() - t0

    for name, d, detail in defects[: 20 if not quiet else 5]:
        print(f"DEFECT  {name}  {d}  {detail}")
    if len(defects) > 20:
        print(f"... {len(defects) - 20} more")
    g = 1.0
    for s in speed:
        g *= s
    print(f"programs={len(progs)} (order-specified {n_ordered}) datasets={len(data)} checked={checked} skipped={skipped} "
          f"defects={len(defects)} time={elapsed:.1f}s"
          + (f" geomean_speedup={g ** (1 / len(speed)):.2f}x" if speed else ""))
    return 1 if defects else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
