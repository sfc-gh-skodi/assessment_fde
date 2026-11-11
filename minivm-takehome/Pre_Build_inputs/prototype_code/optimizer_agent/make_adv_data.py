#!/usr/bin/env python3
"""Make adversarial variants of examples/data.json that still satisfy schema constraints.

  make_adv_data.py [N] [OUTDIR]     default N=6, OUTDIR=./data/adv

Each variant mutates only columns the constraints leave free: case/space status
variants, '' and NULL in nullable columns, duplicate customer ids (customers has no
key), NULL discounts, etc. Every file is checked with `bin/minivm --schema`, which
rejects any table set that breaks a declared constraint.
"""
import copy, json, os, random, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "minivm-takehome"))
VM = os.environ.get("MINIVM", os.path.join(ROOT, "bin", "minivm"))


def col(t, name):
    return [c["name"] for c in t["columns"]].index(name)


def mutate(base, rng):
    d = copy.deepcopy(base)
    pick = lambda opts: rng.choice(opts)

    o = d["orders"]
    for r in o["rows"]:
        s = r[col(o, "o_status")]
        if s is not None and rng.random() < 0.5:
            r[col(o, "o_status")] = pick([s.upper(), s + " ", s.capitalize() + "  ", "", None])
        if rng.random() < 0.3:
            r[col(o, "o_note")] = pick([None, "", "rush", "Rush ", "gift"])
        if rng.random() < 0.1:
            r[col(o, "o_cust")] = None
        if rng.random() < 0.1:
            r[col(o, "o_date")] = None
        if rng.random() < 0.1:
            r[col(o, "o_amt")] = None

    c = d["customers"]
    for r in c["rows"]:
        if rng.random() < 0.4:
            reg = r[col(c, "c_region")]
            r[col(c, "c_region")] = pick([None, "", (reg or "").upper(), (reg or "") + " "])
    for r in rng.sample(c["rows"], 3):  # duplicate ids: customers has no key
        c["rows"].append(copy.deepcopy(r))

    y = d["payments"]
    for r in y["rows"]:
        if rng.random() < 0.4:
            r[col(y, "y_method")] = pick(["Card", "card ", "CARD", "", None])

    k = d["categories"]
    for r in k["rows"]:
        if rng.random() < 0.5:
            r[col(k, "k_name")] = pick([r[col(k, "k_name")].upper() + " ", r[col(k, "k_name")].lower()])

    p = d["products"]
    for r in p["rows"]:
        if rng.random() < 0.2:
            r[col(p, "p_name")] = pick([None, ""])

    ln = d["lines"]
    for r in ln["rows"]:
        if rng.random() < 0.15:
            r[col(ln, "l_disc")] = None
    return d


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "data", "adv")
    os.makedirs(out, exist_ok=True)
    base = json.load(open(os.path.join(ROOT, "examples", "data.json")))
    for i in range(n):
        path = os.path.join(out, f"adv{i}.json")
        json.dump(mutate(base, random.Random(i)), open(path, "w"))
        r = subprocess.run([VM, "--schema", path], capture_output=True, text=True)
        print(path, "OK" if r.returncode == 0 else "INVALID: " + r.stderr.strip())


if __name__ == "__main__":
    main()
