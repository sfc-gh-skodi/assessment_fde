#!/usr/bin/env python3
"""Scale-stress cases near the MiniVM limits (kept OUT of tests/cases and the evaluator corpus).

  tools/make_stress.py [--run]

Writes tests/stress/ (git-ignored; byte-for-byte reproducible, fixed seeds):
  example/data_10k.json         the example schema with every table at 9,990-10,000 rows
                                (limit: 10,000 rows per table)
  example/prog_20k.mini         exactly 20,000 instructions (limit: 20,000) of legacy-style
                                waste: dead loads, duplicate predicates, overwritten registers,
                                a long live NUM chain and a late filter
  example/regpressure.mini      ~6,000 live 10k-value registers (limit: 64M values in all)
  fanout/data.json, schema.json one key value shared by 1,999 rows (t) and 2,001 rows (u)
  fanout/fanout_ok.mini         self-join with 1,999^2 = 3,996,001 output pairs (limit: 4M per register)
  fanout/fanout_over.mini       2,001^2 = 4,004,001 pairs: the ORIGINAL errors (anything goes)
--run runs every stress program (and every tests/cases program on data_10k.json) and prints
cycles, wall time, or the error.
"""
import datetime
import glob
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from evaluator import vm  # noqa: E402

OUT = os.path.join(REPO, "tests", "stress")
N = 10000


def day(rng, y0=2022, y1=2024):
    a, b = datetime.date(y0, 1, 1).toordinal(), datetime.date(y1, 12, 31).toordinal()
    return datetime.date.fromordinal(rng.randint(a, b)).isoformat()


def money(rng, lo, hi):
    return f"{rng.randint(int(lo * 100), int(hi * 100)) / 100:.2f}"


def cols(*spec):
    return [{"name": n, "type": t} for n, t in spec]


def data_10k():
    rng = random.Random(10000)
    regs = ["west", "east", "north", "south", "central"]
    n = lambda: rng.randint(N - 10, N)
    regions = [[f"r{i}" if i >= 5 else regs[i], f"Region {i}"] for i in range(n())]
    customers = [[rng.randint(1, 8000), rng.choice(["Ann", "Bob", "Cy", "Zoë", "straße", f"c{i}"]),
                  rng.choice(regs + [None]), day(rng, 2015, 2023),
                  None if rng.random() < 0.1 else money(rng, 0, 5000)] for i in range(n())]
    n_ord = n()
    orders = [[i + 1, rng.randint(1, 8000), day(rng), None if rng.random() < 0.05 else money(rng, 0, 1000),
               rng.randint(1, 10), rng.choice(["open", "closed", "shipped", None]),
               rng.choice([None, None, "rush", "gift", ""])] for i in range(n_ord)]
    n_cat = n()
    categories = [[i + 1, rng.choice(["Tools", "Garden", "Kitchen", "Toys"]) + f" {i}",
                   None if i == 0 or rng.random() < 0.3 else rng.randint(1, i)] for i in range(n_cat)]
    n_sup = n()
    suppliers = [[i + 1, f"Supp {i}", rng.choice(regs + [None]), rng.choice([None, 1, 2, 3, 4, 5])]
                 for i in range(n_sup)]
    n_prod = n()
    products = [[1001 + i, rng.choice(["Lamp", "Tent", "Kettle", "Towel"]) + f" {i}", rng.randint(1, n_cat),
                 None if rng.random() < 0.1 else rng.randint(1, n_sup), money(rng, 0.01, 9999.99),
                 day(rng, 2015, 2024)] for i in range(n_prod)]
    lines, o = [], 1
    while len(lines) < N:            # sorted by (l_order, l_no); l_no in [1, 50]
        for no in range(1, rng.randint(1, 4) + 1):
            if len(lines) < N:
                lines.append([o, no, 1001 + rng.randrange(n_prod), rng.randint(1, 500), money(rng, 1, 999),
                              None if rng.random() < 0.1 else rng.choice(["0", "0.05", "0.10", "0.5"])])
        o += rng.randint(1, 2)
        if o > n_ord:
            o = n_ord
    payments = [[i + 1, rng.randint(1, n_ord), day(rng), money(rng, 0.01, 1500),
                 rng.choice(["card", "cash", "transfer", "voucher", None])] for i in range(n())]
    return {
        "regions": {"columns": cols(("r_code", "STR"), ("r_name", "STR")), "rows": regions},
        "customers": {"columns": cols(("c_id", "INT"), ("c_name", "STR"), ("c_region", "STR"), ("c_since", "DATE"),
                                      ("c_credit", "NUM")), "rows": customers},
        "orders": {"columns": cols(("o_id", "INT"), ("o_cust", "INT"), ("o_date", "DATE"), ("o_amt", "NUM"),
                                   ("o_qty", "INT"), ("o_status", "STR"), ("o_note", "STR")),
                   "key": ["o_id"], "rows": orders},
        "categories": {"columns": cols(("k_id", "INT"), ("k_name", "STR"), ("k_parent", "INT")),
                       "key": ["k_id"], "not_null": ["k_name"], "refs": {"k_parent": "categories.k_id"},
                       "rows": categories},
        "suppliers": {"columns": cols(("s_id", "INT"), ("s_name", "STR"), ("s_region", "STR"), ("s_rating", "INT")),
                      "key": ["s_id"], "check": {"s_rating": [1, 5]}, "rows": suppliers},
        "products": {"columns": cols(("p_id", "INT"), ("p_name", "STR"), ("p_cat", "INT"), ("p_supp", "INT"),
                                     ("p_price", "NUM"), ("p_added", "DATE")),
                     "key": ["p_id"], "not_null": ["p_cat", "p_price"],
                     "refs": {"p_cat": "categories.k_id", "p_supp": "suppliers.s_id"},
                     "check": {"p_price": ["0.01", "9999.99"]}, "rows": products},
        "lines": {"columns": cols(("l_order", "INT"), ("l_no", "INT"), ("l_prod", "INT"), ("l_qty", "INT"),
                                  ("l_price", "NUM"), ("l_disc", "NUM")),
                  "key": ["l_order", "l_no"], "not_null": ["l_prod", "l_qty"],
                  "refs": {"l_order": "orders.o_id", "l_prod": "products.p_id"},
                  "check": {"l_no": [1, 50], "l_qty": [1, 500], "l_disc": ["0", "0.5"]},
                  "sorted": ["l_order", "l_no"], "rows": lines},
        "payments": {"columns": cols(("y_id", "INT"), ("y_order", "INT"), ("y_date", "DATE"), ("y_amt", "NUM"),
                                     ("y_method", "STR")),
                     "key": ["y_id"], "not_null": ["y_order", "y_amt"], "refs": {"y_order": "orders.o_id"},
                     "check": {"y_amt": ["0.01", None]}, "rows": payments},
    }


def prog_20k():
    rng = random.Random(20000)
    L = ["; stress: exactly 20,000 instructions of legacy waste over orders (dead loads, duplicate",
         ";   predicates, overwritten registers, a 6,000-step live NUM chain, a late filter)",
         "LOAD   id, orders.o_id", "LOAD   amt, orders.o_amt", "LOAD   q, orders.o_qty", "NVL    acc, amt, 0.00"]
    body = 20000 - 8          # 4 instructions above, 4 below
    i = 0
    while i < body:
        r = rng.random()
        if r < 0.30 and i < body:
            L.append(f"ADD    acc, acc, {rng.choice(['0.01', '0.02', '1', '-1'])}")
            i += 1
        elif r < 0.55:
            L.append(f"LOAD   d{i}, orders.{rng.choice(['o_note', 'o_status', 'o_date', 'o_cust'])}")
            i += 1
        elif r < 0.80:
            L.append(f"GT     p{i % 50}, q, {rng.randint(0, 10)}")
            i += 1
        elif i + 2 <= body:
            L.append(f"MUL    t, amt, {rng.randint(1, 3)}")
            L.append(f"SUB    w{i % 97}, t, acc")
            i += 2
    L += ["GT     keep, acc, 500.00", "IDX    k, keep", "GATHER oid, id, k"]
    L.append("OUT    oid")      # 20,000 instructions
    return "\n".join(L) + "\n"


def regpressure(n_regs=6000):
    L = ["; stress: %d live registers of 10k values each (~%dM of the 64M total-values limit)" % (n_regs, n_regs // 100)]
    for i in range(n_regs):
        L.append(f"LOAD   r{i}, lines.{['l_order', 'l_no', 'l_qty', 'l_prod'][i % 4]}")
    acc = "r0"
    for i in range(1, 40):
        L.append(f"ADD    s{i}, {acc}, r{i * 97 % n_regs}")
        acc = f"s{i}"
    L.append(f"ADD    last, {acc}, r{n_regs - 1}")
    L.append("OUT    last")
    return "\n".join(L) + "\n"


def fanout():
    data = {"t": {"columns": cols(("t_k", "INT"), ("t_v", "INT")), "rows": [[1, i % 7] for i in range(1999)]},
            "u": {"columns": cols(("u_k", "INT"), ("u_v", "INT")), "rows": [[1, i % 5] for i in range(2001)]}}
    ok = ("; stress: self-join of 1,999 equal keys -> 3,996,001 pairs (just under the 4M values per register)\n"
          "; then per-left-row count of larger partners; an optimizer must not grow any intermediate\n"
          "LOAD   k, t.t_k\nLOAD   v, t.t_v\nHJOIN  a, b, k, k\nGATHER va, v, a\nGATHER vb, v, b\n"
          "GT     h, vb, va\nIDX    i, h\nGATHER ai, a, i\nGROUP  g, ai\nGFIRST f, g\nGATHER pos, ai, f\n"
          "GCOUNT n, g\nGATHER pv, v, pos\nOUT    pv, n\n")
    over = ("; stress: self-join of 2,001 equal keys -> 4,004,001 pairs: the ORIGINAL exceeds the 4M limit\n"
            "; and errors, so any optimized output is acceptable (the evaluator SKIPs it)\n"
            "LOAD   k, u.u_k\nLOAD   v, u.u_v\nHJOIN  a, b, k, k\nGATHER vb, v, b\nGROUP  g, a\n"
            "GSUM   s, g, vb\nOUT    s\n")
    return data, ok, over


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    print(f"wrote {os.path.relpath(path, REPO)}")


def main(argv):
    ex = os.path.join(OUT, "example")
    write(os.path.join(ex, "data_10k.json"), json.dumps(data_10k(), ensure_ascii=False) + "\n")
    write(os.path.join(ex, "prog_20k.mini"), prog_20k())
    write(os.path.join(ex, "regpressure.mini"), regpressure())
    fd, ok, over = fanout()
    fo = os.path.join(OUT, "fanout")
    write(os.path.join(fo, "data.json"), json.dumps(fd) + "\n")
    write(os.path.join(fo, "fanout_ok.mini"), ok)
    write(os.path.join(fo, "fanout_over.mini"), over)
    bad = 0
    for d in (ex, fo):
        data = os.path.join(d, "data_10k.json" if d == ex else "data.json")
        s, err = vm.schema_of(data)
        if s is None:
            print(f"INVALID {os.path.relpath(data, REPO)}: {err}")
            bad += 1
            continue
        if d == fo:
            write(os.path.join(fo, "schema.json"), json.dumps(s) + "\n")
        else:
            write(os.path.join(ex, "schema.json"), json.dumps(s, ensure_ascii=False) + "\n")
            print("  rows per table:", {t: v["stats"]["rows"] for t, v in s.items()})
    n = sum(1 for line in open(os.path.join(ex, "prog_20k.mini")) if line.split(";")[0].strip())
    print(f"  prog_20k.mini: {n} instructions")
    if "--run" in argv:
        runs = [(os.path.join(ex, p), os.path.join(ex, "data_10k.json")) for p in ("prog_20k.mini", "regpressure.mini")]
        runs += [(os.path.join(ex, "prog_20k.mini"), os.path.join(REPO, "examples", "data.json"))]
        runs += [(os.path.join(fo, p), os.path.join(fo, "data.json")) for p in ("fanout_ok.mini", "fanout_over.mini")]
        cases = sorted(glob.glob(os.path.join(REPO, "examples", "programs", "*.mini")))
        cases += sorted(glob.glob(os.path.join(REPO, "tests", "cases", "*", "*.mini")))
        runs += [(p, os.path.join(ex, "data_10k.json")) for p in cases]
        for p, d in runs:
            t = time.monotonic()
            r, err = vm.run(p, d, timeout=120)
            dt = time.monotonic() - t
            what = f"{len(r['rows'])} rows, {r['cycles']} cycles" if r else f"ERROR {err[:90]}"
            print(f"  {os.path.relpath(p, REPO):55} on {os.path.basename(d):14} {dt:6.2f} s  {what}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
