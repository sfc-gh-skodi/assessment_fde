"""Schema-driven generator of tricky table sets (production port of prototype gen_data.py).

  generate(schema, size, seed, lits) -> table-set dict
  harvest(texts) -> literal pools taken from MiniVM program texts

Respects every constraint (key, not_null, refs, check, sorted). Uses stats only to
pick realistic ranges/vocabularies so filters hit. Mixes in NULLs, duplicates and
ties, empty and 1-row tables, case/space variants, weird Unicode (ß, ﬁ, emoji,
combining marks), NUM scale variants (1.0 vs 1.00), zeros (to make DIV error),
boundary dates, and the programs' own literals with +-1 neighbours.
"""
import datetime
import random
import re
from decimal import Decimal

SIZES = {"small": (0, 6), "medium": (20, 150), "large": (600, 2500)}
WEIRD = ["", " ", "  ", "ß", "straße", "Zoë", "e\u0301", "ﬁx", "İ", "ı", "🙂", "it's", "a,b", ";x",
         "NULL", "null", "\t", "ǅ", "x" * 45, "Ünïcødé ✓", "  lead", "trail  ", "1.0", "1.00", "2024-01-01"]
SPECIAL_DATES = ["2022-12-31", "2023-01-01", "2023-01-02", "2023-06-30", "2023-07-01", "2023-07-31",
                 "2023-08-01", "2023-12-31", "2024-01-01", "2024-02-29", "2024-12-31", "0001-01-01", "9999-12-31"]
INT32 = (-2**31, 2**31 - 1)
_STR_LIT = re.compile(r"'((?:[^']|'')*)'")


def strip_comment(line):
    out, q = [], False
    for ch in line:
        if ch == "'":
            q = not q
        if ch == ";" and not q:
            break
        out.append(ch)
    return "".join(out)


def harvest(texts):
    lit = {"STR": set(), "INT": set(), "NUM": set(), "DATE": set()}
    for text in texts:
        for line in text.splitlines():
            code = strip_comment(line)
            for s in _STR_LIT.findall(code):
                lit["STR"].add(s.replace("''", "'"))
            for d in re.findall(r"#(\d{4}-\d{2}-\d{2})#", code):
                lit["DATE"].add(d)
            ops = code.split(None, 1)
            if len(ops) == 2 and not re.match(r"(?i)(left|substr|slice|topk)$", ops[0]):
                rest = _STR_LIT.sub("''", ops[1])
                for n in re.findall(r"(?<![\w.#'])-?\d+(?:\.\d+)?(?![\w.#-])", rest):
                    lit["NUM" if "." in n else "INT"].add(n)
    return {k: sorted(v) for k, v in lit.items()}


def _variants(s, rng):
    return rng.choice([s, s, s.upper(), s.capitalize(), s + " ", s.upper() + "  ", " " + s, s.lower()])


def _rand_word(rng):
    alphabet = "abcdefghijklmnopqrstuvwxyzABC _-'é"
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))


def _isnum(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    try:
        Decimal(v)
        return v.strip() != "" and v.strip().lower() not in ("nan", "inf", "infinity", "-inf")
    except Exception:
        return False


def _canon(v):
    return str(Decimal(v).normalize()) if isinstance(v, (int, str)) and _isnum(v) else v


class Gen:
    def __init__(self, schema, size, seed, lits=None):
        self.s, self.rng, self.size = schema, random.Random(seed), size
        self.lit = lits or {"STR": [], "INT": [], "NUM": [], "DATE": []}
        self.data = {}

    def bounds(self, tname, cname):
        chk = {k.lower(): v for k, v in self.s[tname].get("check", {}).items()}
        return chk.get(cname.lower(), [None, None])

    def stats(self, tname, cname):
        cols = self.s[tname].get("stats", {}).get("columns", {})
        for k, v in cols.items():
            if k.lower() == cname.lower():
                return v
        return {}

    def gen_value(self, tname, col, pool):
        rng, typ = self.rng, col["type"]
        if pool and rng.random() < 0.45:
            return rng.choice(pool)
        lo, hi = self.bounds(tname, col["name"])
        st = self.stats(tname, col["name"])
        if typ == "INT":
            a = int(Decimal(str(st["min"]))) if st.get("min") is not None else 0
            b = int(Decimal(str(st["max"]))) if st.get("max") is not None else 100
            span = max(3, b - a)
            a, b = a - span // 3, b + span // 3
            if lo is not None:
                a = max(a, int(Decimal(str(lo)).to_integral_value("ROUND_CEILING")))
            if hi is not None:
                b = min(b, int(Decimal(str(hi)).to_integral_value("ROUND_FLOOR")))
            a, b = max(a, INT32[0]), min(b, INT32[1])
            edges = [int(Decimal(str(x))) for x in (lo, hi) if x is not None] + [0, 1, -1]
            edges += [int(Decimal(x)) + dx for x in self.lit["INT"] + self.lit["NUM"] for dx in (-1, 0, 1)]
            edges = [e for e in edges if (lo is None or e >= Decimal(str(lo))) and (hi is None or e <= Decimal(str(hi)))
                     and INT32[0] <= e <= INT32[1]]
            if edges and rng.random() < 0.25:
                return rng.choice(edges)
            return rng.randint(a, max(a, b))
        if typ == "NUM":
            a = Decimal(str(st["min"])) if st.get("min") is not None else Decimal(0)
            b = Decimal(str(st["max"])) if st.get("max") is not None else Decimal(100)
            span = max(Decimal(1), b - a)
            a, b = a - span / 3, b + span / 3
            if lo is not None:
                a = max(a, Decimal(str(lo)))
            if hi is not None:
                b = min(b, Decimal(str(hi)))
            edges = [Decimal(str(x)) for x in (lo, hi) if x is not None] + [Decimal("0"), Decimal("0.0")]
            edges += [Decimal(x) + dx for x in self.lit["NUM"] + self.lit["INT"]
                      for dx in (Decimal("-0.01"), 0, Decimal("0.01"))]
            edges = [e for e in edges if (lo is None or e >= Decimal(str(lo))) and (hi is None or e <= Decimal(str(hi)))]
            if edges and rng.random() < 0.25:
                v = rng.choice(edges)
                if rng.random() < 0.3:
                    v = v.quantize(Decimal("0.001")) if abs(v) < 10**20 else v   # same value, other scale
            else:
                v = a + (b - a) * Decimal(rng.random())
                scale = rng.choice([0, 1, 2, 2, 3])
                v = v.quantize(Decimal(1).scaleb(-scale), rounding="ROUND_DOWN")
                if v < a:
                    v = a
                if v > b:
                    v = b
            return f"{v:f}"
        if typ == "DATE":
            lits = []
            for x in self.lit["DATE"]:
                for dx in (-1, 0, 1):
                    try:
                        lits.append((datetime.date.fromisoformat(x) + datetime.timedelta(days=dx)).isoformat())
                    except (ValueError, OverflowError):
                        pass
            if rng.random() < 0.3:
                cand = rng.choice(SPECIAL_DATES + lits)
            else:
                d0 = datetime.date.fromisoformat(st.get("min") or "2023-01-01")
                d1 = datetime.date.fromisoformat(st.get("max") or "2024-12-31")
                try:
                    d0, d1 = d0 - datetime.timedelta(days=200), d1 + datetime.timedelta(days=200)
                except OverflowError:
                    pass
                cand = (d0 + datetime.timedelta(days=rng.randint(0, max(0, (d1 - d0).days)))).isoformat()
            if lo is not None and cand < str(lo):
                cand = str(lo)
            if hi is not None and cand > str(hi):
                cand = str(hi)
            return cand
        vocab = [v for v, _ in st.get("common", [])] + [x for x in (st.get("min"), st.get("max")) if x]
        r = rng.random()
        if self.lit["STR"] and r < 0.25:
            return _variants(rng.choice(self.lit["STR"]).lower(), rng)
        if vocab and r < 0.6:
            return _variants(rng.choice(vocab), rng)
        if r < 0.8:
            return rng.choice(WEIRD)
        return _rand_word(rng)

    def order(self):
        deps = {t: {v.split(".")[0] for v in self.s[t].get("refs", {}).values()} - {t} for t in self.s}
        lower = {t.lower(): t for t in self.s}
        deps = {t: {lower.get(d.lower(), d) for d in ds} for t, ds in deps.items()}
        done, out = set(), []
        while len(out) < len(self.s):
            progress = False
            for t in self.s:
                if t not in done and deps[t] <= done:
                    done.add(t)
                    out.append(t)
                    progress = True
            if not progress:          # cyclic refs: emit the rest in any order
                out += [t for t in self.s if t not in done]
                break
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
        names = [c["name"].lower() for c in cols]
        key = [k.lower() for k in spec.get("key", [])]
        nn = set(key) | {c.lower() for c in spec.get("not_null", [])}
        refs = {k.lower(): v for k, v in spec.get("refs", {}).items()}
        pools = {c["name"].lower(): [self.gen_value(t, c, None) for _ in range(rng.randint(1, 4))] for c in cols}
        n = self.nrows(t)
        lower = {x.lower(): x for x in self.s}
        parents = {}
        for c, target in refs.items():
            pt, pc = target.split(".")
            pt = lower[pt.lower()]
            if pt != t:
                pnames = [x["name"].lower() for x in self.s[pt]["columns"]]
                pv = [r[pnames.index(pc.lower())] for r in self.data[pt]["rows"]]
                parents[c] = pv
                if not pv and c in nn:
                    n = 0
        rows = []
        for _ in range(n):
            row = []
            for c, cname in zip(cols, names):
                if cname in parents:
                    pv = parents[cname]
                    row.append(None if (cname not in nn and rng.random() < 0.15) or not pv else rng.choice(pv))
                elif cname not in nn and rng.random() < 0.15:
                    row.append(None)
                elif len(key) == 1 and cname == key[0] and c["type"] == "INT":
                    row.append(None)
                else:
                    row.append(self.gen_value(t, c, pools[cname]))
            rows.append(row)
        if len(key) == 1:
            ki = names.index(key[0])
            if cols[ki]["type"] == "INT":
                lo, hi = self.bounds(t, key[0])
                base = int(Decimal(str(lo))) if lo is not None else rng.choice([1, 10, 1001])
                ids = list(range(base, base + 2 * max(1, len(rows))))
                if hi is not None:
                    ids = [i for i in ids if i <= Decimal(str(hi))]
                rng.shuffle(ids)
                rows = rows[:len(ids)]
                for r, v in zip(rows, ids):
                    r[ki] = v
        if key:
            kis = [names.index(k) for k in key]
            seen, uniq = set(), []
            for r in rows:
                kt = tuple(_canon(r[i]) for i in kis)
                if None in kt or kt in seen:
                    continue
                seen.add(kt)
                uniq.append(r)
            rows = uniq
        for c, target in refs.items():
            pt, pc = target.split(".")
            if lower[pt.lower()] == t:
                ci, pi = names.index(c), names.index(pc.lower())
                pv = [r[pi] for r in rows]
                for r in rows:
                    r[ci] = None if (c not in nn and rng.random() < 0.4) or not pv else rng.choice(pv)
        if spec.get("sorted"):
            sis = [names.index(c.lower()) for c in spec["sorted"]]
            types = {i: c["type"] for i, c in enumerate(cols)}

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


def generate(schema, size, seed, lits=None):
    return Gen(schema, size, seed, lits).run()
