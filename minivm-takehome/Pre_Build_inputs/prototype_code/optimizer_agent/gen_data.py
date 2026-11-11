#!/usr/bin/env python3
"""Generate tricky table sets that satisfy a schema's constraints.

  gen_data.py [--schema SCHEMA.json] [--out DIR] [--small N] [--medium N] [--large N] [--seed S]

Reads columns + constraints (key, not_null, refs, check, sorted) from the schema and
uses its stats only to pick realistic value ranges and vocabularies (so filters hit).
Each dataset mixes in: NULLs in every nullable column, duplicates and ties (values
drawn from small pools), empty and one-row tables, case/space variants of real
values ('Open ', 'OPEN'), weird strings (ß, ﬁ, emoji, combining marks, quotes,
separators, long strings), NUM scale variants ('1.0' vs '1.00'), and boundary values
(check bounds, year edges, 2024-02-29, 0001-01-01, 9999-12-31).

Literals harvested from the programs (--programs) are mixed in too, with case/space
variants for strings and +-1 neighbours for numbers and dates, so program filters
like IS 'KITCHEN' or GT 750.00 actually hit rows and their boundaries.

Every file is validated with `bin/minivm --schema`; invalid ones are reported and removed.
Output: DIR/{small,medium,large}/<size>_<seed>.json
"""
import argparse, datetime, glob, json, os, random, re, subprocess
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "minivm-takehome"))
VM = os.environ.get("MINIVM", os.path.join(ROOT, "bin", "minivm"))

SIZES = {"small": (0, 6), "medium": (20, 150), "large": (600, 2500)}
WEIRD = ["", " ", "  ", "ß", "straße", "Zoë", "e\u0301", "ﬁx", "İ", "ı", "🙂", "it's", "a,b", ";x",
         "NULL", "null", "\t", "ǅ", "x" * 45, "Ünïcødé ✓", "  lead", "trail  "]
SPECIAL_DATES = ["2022-12-31", "2023-01-01", "2023-01-02", "2023-06-30", "2023-07-01", "2023-07-31",
                 "2023-08-01", "2023-12-31", "2024-01-01", "2024-02-29", "2024-12-31", "0001-01-01", "9999-12-31"]
INT32 = (-2**31, 2**31 - 1)
LIT = {"STR": [], "INT": [], "NUM": [], "DATE": []}


def harvest(paths):
    """Collect literals from MiniVM programs (comments stripped)."""
    for p in paths:
        for line in open(p):
            code = re.sub(r"'(?:[^']|'')*'", lambda m: m.group(0).replace(";", "\0"), line).split(";")[0].replace("\0", ";")
            for s in re.findall(r"'((?:[^']|'')*)'", code):
                LIT["STR"].append(s.replace("''", "'"))
            for d in re.findall(r"#(\d{4}-\d{2}-\d{2})#", code):
                LIT["DATE"].append(d)
            ops = code.split(None, 1)
            if len(ops) == 2 and not re.match(r"(?i)(left|substr|slice|topk)$", ops[0]):
                for n in re.findall(r"(?<![\w.#'])-?\d+(?:\.\d+)?(?![\w.#-])", ops[1]):
                    LIT["NUM" if "." in n else "INT"].append(n)
    for k in LIT:
        LIT[k] = sorted(set(LIT[k]))


def low(x):
    return x.lower()


def variants(s, rng):
    return rng.choice([s, s, s.upper(), s.capitalize(), s + " ", s.upper() + "  ", " " + s, s.lower()])


def rand_word(rng):
    alphabet = "abcdefghijklmnopqrstuvwxyzABC _-'é"
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))


def fmt_num(d, scale):
    return f"{d:.{scale}f}"


class Gen:
    def __init__(self, schema, size, seed):
        self.s, self.rng, self.size = schema, random.Random(seed), size
        self.data = {}

    # ---------- per-column value generators ----------
    def bounds(self, tname, cname):
        chk = {low(k): v for k, v in self.s[tname].get("check", {}).items()}
        return chk.get(low(cname), [None, None])

    def stats(self, tname, cname):
        return self.s[tname].get("stats", {}).get("columns", {}).get(cname, {})

    def gen_value(self, tname, col, pool):
        rng, typ = self.rng, col["type"]
        if pool and rng.random() < 0.45:          # duplicates / ties
            return rng.choice(pool)
        lo, hi = self.bounds(tname, col["name"])
        st = self.stats(tname, col["name"])
        if typ == "INT":
            a = int(st.get("min", 0) if st.get("min") is not None else 0)
            b = int(st.get("max", 100) if st.get("max") is not None else 100)
            span = max(3, b - a)
            a, b = a - span // 3, b + span // 3
            if lo is not None: a = max(a, int(Decimal(str(lo))))
            if hi is not None: b = min(b, int(Decimal(str(hi))))
            a, b = max(a, INT32[0]), min(b, INT32[1])
            edges = [int(Decimal(str(x))) for x in (lo, hi) if x is not None]
            edges += [int(Decimal(x)) + dx for x in LIT["INT"] + LIT["NUM"] for dx in (-1, 0, 1)]
            edges = [e for e in edges if (lo is None or e >= Decimal(str(lo))) and (hi is None or e <= Decimal(str(hi)))
                     and INT32[0] <= e <= INT32[1]]
            if edges and rng.random() < 0.25:
                return rng.choice(edges)
            return rng.randint(a, max(a, b))
        if typ == "NUM":
            a = Decimal(str(st.get("min") if st.get("min") is not None else 0))
            b = Decimal(str(st.get("max") if st.get("max") is not None else 100))
            span = max(Decimal(1), b - a)
            a, b = a - span / 3, b + span / 3
            if lo is not None: a = max(a, Decimal(str(lo)))
            if hi is not None: b = min(b, Decimal(str(hi)))
            edges = [Decimal(str(x)) for x in (lo, hi) if x is not None]
            edges += [Decimal(x) + dx for x in LIT["NUM"] + LIT["INT"] for dx in (Decimal("-0.01"), 0, Decimal("0.01"))]
            edges = [e for e in edges if (lo is None or e >= Decimal(str(lo))) and (hi is None or e <= Decimal(str(hi)))]
            if edges and rng.random() < 0.25:
                v = rng.choice(edges)
            else:
                v = a + (b - a) * Decimal(rng.random())
            scale = rng.choice([0, 1, 2, 2, 3])
            v = v.quantize(Decimal(1).scaleb(-scale), rounding="ROUND_DOWN")
            v = min(max(v, a), b) if b >= a else a
            if v < a: v = a
            return fmt_num(v, max(0, -v.as_tuple().exponent))
        if typ == "DATE":
            lits = [(datetime.date.fromisoformat(x) + datetime.timedelta(days=dx)).isoformat()
                    for x in LIT["DATE"] for dx in (-1, 0, 1) if "0001" < x < "9999"]
            if rng.random() < 0.3:
                cand = rng.choice(SPECIAL_DATES + lits)
            else:
                d0 = datetime.date.fromisoformat(st.get("min") or "2023-01-01")
                d1 = datetime.date.fromisoformat(st.get("max") or "2024-12-31")
                d0, d1 = d0 - datetime.timedelta(days=200), d1 + datetime.timedelta(days=200)
                cand = (d0 + datetime.timedelta(days=rng.randint(0, (d1 - d0).days))).isoformat()
            if lo is not None and cand < str(lo): cand = str(lo)
            if hi is not None and cand > str(hi): cand = str(hi)
            return cand
        # STR
        vocab = [v for v, _ in st.get("common", [])] + [x for x in (st.get("min"), st.get("max")) if x]
        r = rng.random()
        if LIT["STR"] and r < 0.2:
            return variants(rng.choice(LIT["STR"]).lower(), rng)
        if vocab and r < 0.6:
            return variants(rng.choice(vocab), rng)
        if r < 0.8:
            return rng.choice(WEIRD)
        return rand_word(rng)

    def make_pool(self, tname, col):
        return [self.gen_value(tname, col, None) for _ in range(self.rng.randint(1, 4))]

    # ---------- table generation ----------
    def order(self):
        deps = {t: {v.split(".")[0] for v in self.s[t].get("refs", {}).values()} - {t} for t in self.s}
        done, out = set(), []
        while len(out) < len(self.s):
            for t in self.s:
                if t not in done and deps[t] <= done:
                    done.add(t); out.append(t)
        return out

    def nrows(self, t):
        lo, hi = SIZES[self.size]
        if self.size == "small" and self.rng.random() < 0.25:
            return self.rng.choice([0, 1])
        n = self.rng.randint(lo, hi)
        return n * 3 if self.s[t].get("refs") and self.size != "small" else n

    def gen_table(self, t):
        rng, spec = self.rng, self.s[t]
        cols = spec["columns"]
        names = [low(c["name"]) for c in cols]
        key = [low(k) for k in spec.get("key", [])]
        nn = set(key) | {low(c) for c in spec.get("not_null", [])}
        refs = {low(k): v for k, v in spec.get("refs", {}).items()}
        pools = {low(c["name"]): self.make_pool(t, c) for c in cols}
        n = self.nrows(t)

        # self-references are filled after this table's keys exist
        parents = {}
        for c, target in refs.items():
            pt, pc = target.split(".")
            if pt != t:
                pv = [r[[low(x["name"]) for x in self.s[pt]["columns"]].index(low(pc))] for r in self.data[pt]["rows"]]
                parents[c] = pv
                if not pv and c in nn:
                    n = 0                         # parent empty and ref is not_null: no rows possible

        rows, seen = [], set()
        for _ in range(n * 3):
            if len(rows) >= n:
                break
            row = []
            for c, cname in zip(cols, names):
                if cname in refs and cname in parents:
                    pv = parents[cname]
                    if (cname not in nn and rng.random() < 0.15) or not pv:
                        row.append(None)
                    else:
                        row.append(rng.choice(pv))
                elif cname not in nn and rng.random() < 0.15:
                    row.append(None)
                elif len(key) == 1 and cname == key[0] and c["type"] == "INT":
                    row.append(None)              # filled below with a unique id
                else:
                    row.append(self.gen_value(t, c, pools[cname]))
            rows.append(row)
        # unique single INT keys
        if len(key) == 1:
            ki = names.index(key[0])
            if cols[ki]["type"] == "INT":
                lo, hi = self.bounds(t, key[0])
                base = int(Decimal(str(lo))) if lo is not None else rng.choice([1, 10, 1001])
                ids = list(range(base, base + 2 * max(1, len(rows))))
                rng.shuffle(ids)
                for r, v in zip(rows, ids):
                    r[ki] = v
        # enforce key uniqueness (numeric values compared by value)
        if key:
            kis = [names.index(k) for k in key]
            canon = lambda v: str(Decimal(v).normalize()) if isinstance(v, (int, str)) and _isnum(v) else v
            uniq = []
            for r in rows:
                kt = tuple(canon(r[i]) for i in kis)
                if None in kt or kt in seen:
                    continue
                seen.add(kt); uniq.append(r)
            rows = uniq
        # self-refs
        for c, target in refs.items():
            pt, pc = target.split(".")
            if pt == t:
                ci, pi = names.index(c), names.index(low(pc))
                pv = [r[pi] for r in rows]
                for r in rows:
                    r[ci] = None if (c not in nn and rng.random() < 0.4) or not pv else rng.choice(pv)
        # sorted constraint
        if spec.get("sorted"):
            sis = [names.index(low(c)) for c in spec["sorted"]]
            types = {names.index(low(c["name"])): c["type"] for c in cols}
            def sk(r):
                out = []
                for i in sis:
                    v = r[i]
                    if v is None:
                        out.append((0, 0))
                    elif types[i] in ("INT", "NUM"):
                        out.append((1, Decimal(str(v))))
                    elif types[i] == "STR":
                        out.append((1, v.encode()))
                    else:
                        out.append((1, v))
                return out
            rows.sort(key=sk)
        tbl = {"columns": cols, "rows": rows}
        for k in ("key", "not_null", "refs", "check", "sorted"):
            if k in spec:
                tbl[k] = spec[k]
        self.data[t] = tbl

    def run(self):
        for t in self.order():
            self.gen_table(t)
        return self.data


def _isnum(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    try:
        Decimal(v); return v.strip() != "" and not v.strip().lower() in ("nan", "inf", "infinity")
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", default=os.path.join(ROOT, "examples", "schema.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "data"))
    ap.add_argument("--small", type=int, default=20)
    ap.add_argument("--medium", type=int, default=10)
    ap.add_argument("--large", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--programs", default=os.path.join(ROOT, "examples", "programs"),
                    help="directory of .mini programs to harvest literals from ('' to disable)")
    a = ap.parse_args()
    if a.programs:
        harvest(sorted(glob.glob(os.path.join(a.programs, "*.mini"))))
        print("literals:", {k: len(v) for k, v in LIT.items()}, LIT["STR"])
    schema = json.load(open(a.schema))
    counts = {"ok": 0, "invalid": 0}
    for size, n in (("small", a.small), ("medium", a.medium), ("large", a.large)):
        os.makedirs(os.path.join(a.out, size), exist_ok=True)
        for i in range(n):
            seed = a.seed * 1000 + i
            path = os.path.join(a.out, size, f"{size}_{seed}.json")
            json.dump(Gen(schema, size, seed).run(), open(path, "w"), ensure_ascii=False)
            r = subprocess.run([VM, "--schema", path], capture_output=True, text=True)
            if r.returncode == 0:
                counts["ok"] += 1
            else:
                counts["invalid"] += 1
                print("INVALID", path, r.stderr.strip())
                os.remove(path)
    print(counts)


if __name__ == "__main__":
    main()
