"""Random, type-correct MiniVM program generator over any schema ("held-out" programs).

  gen_program(schema, rng) -> program text

Programs look like the legacy examples: every column carried through every join,
filters applied late, labels built before filters, sorts on sorted tables, dead
loads, full SORT + SLICE, self-join idioms, GROUP/GALL aggregates. Literals come
from the schema stats so filters actually hit. Some programs can error on some
data (DIV by a column) to exercise the "original errors -> anything goes" path.
"""
import random

NUMT = ("INT", "NUM")


class Col:
    __slots__ = ("reg", "type", "table", "name", "nullable", "src")

    def __init__(self, reg, type_, table=None, name=None, nullable=True, src=None):
        self.reg, self.type, self.table, self.name, self.nullable, self.src = reg, type_, table, name, nullable, src


class P:
    def __init__(self, schema, rng, force=None):
        self.s, self.rng, self.force = schema, rng, force
        self.lines, self.n = [], 0
        self.style = rng.choice(["upper", "lower"])
        self.prefix = rng.choice(["r", "t", "x"])

    # ---- emission helpers
    def fresh(self, hint=""):
        self.n += 1
        return f"{self.prefix}{self.n}" + (f"_{hint}" if hint and self.rng.random() < 0.5 else "")

    def emit(self, op, *args, comment=None):
        op = op.upper() if self.style == "upper" else op.lower()
        line = f"{op:<7} {', '.join(str(a) for a in args)}"
        if comment:
            line += f"   ; {comment}"
        self.lines.append(line)

    # ---- schema helpers
    def tcols(self, t):
        return self.s[t]["columns"]

    def nn(self, t):
        sp = self.s[t]
        return {c.lower() for c in sp.get("key", [])} | {c.lower() for c in sp.get("not_null", [])}

    def stats(self, t, c):
        for k, v in self.s[t].get("stats", {}).get("columns", {}).items():
            if k.lower() == c.lower():
                return v
        return {}

    def load_table(self, t, only=None):
        cols = []
        for c in self.tcols(t):
            if only is not None and c["name"].lower() not in only:
                continue
            r = self.fresh(c["name"][:3])
            self.emit("LOAD", r, f"{t}.{c['name']}")
            cols.append(Col(r, c["type"], t, c["name"], c["name"].lower() not in self.nn(t)))
        return cols

    def gather_all(self, cols, idx):
        out = []
        for c in cols:
            r = self.fresh()
            self.emit("GATHER", r, c.reg, idx)
            out.append(Col(r, c.type, c.table, c.name, c.nullable, c.src))
        return out

    # ---- literals
    def literal_for(self, c):
        rng = self.rng
        st = self.stats(c.table, c.name) if c.table else {}
        vals = [v for v, _ in st.get("common", [])] + [st.get("min"), st.get("max")] + st.get("histogram", [])[2:9]
        vals = [v for v in vals if v is not None]
        if c.type == "STR":
            v = rng.choice(vals) if vals else rng.choice(["open", "x", "card"])
            return "'" + str(v).replace("'", "''") + "'", v
        if c.type == "DATE":
            v = rng.choice(vals) if vals else "2023-06-01"
            return f"#{v}#", v
        if c.type == "INT":
            v = rng.choice(vals) if vals else rng.randint(0, 10)
            return str(int(float(v))), v
        if c.type == "NUM":
            v = rng.choice(vals) if vals else "10.00"
            s = str(v)
            return (s if "." in s else s + ".00"), v
        return "NULL", None

    # ---- predicates (return a BOOL register)
    def predicate(self, cols):
        rng = self.rng
        cands = [c for c in cols if c.type in ("INT", "NUM", "STR", "DATE")]
        c = rng.choice(cands)
        kind = rng.random()
        if c.type == "STR":
            if kind < 0.5:
                a = self.fresh("n")
                self.emit("NULLIFE", a, c.reg)
                b = self.fresh("t")
                self.emit("RTRIM", b, a)
                u = self.fresh("u")
                self.emit("UPPER", u, b)
                lit, _ = self.literal_for(c)
                m = self.fresh("f")
                self.emit("IS", m, u, lit.upper())
                return m
            if kind < 0.7:
                m = self.fresh("f")
                self.emit("ISNULL", m, c.reg)
                m2 = self.fresh("f")
                self.emit("NOT", m2, m)
                return m2
            lit, _ = self.literal_for(c)
            m = self.fresh("f")
            self.emit(rng.choice(["EQ", "NE", "IS", "GE", "LT"]), m, c.reg, lit)
            return m
        if c.type == "DATE" and kind < 0.6:
            y = self.fresh("y")
            self.emit("YEAR", y, c.reg)
            m = self.fresh("f")
            self.emit(rng.choice(["EQ", "GE", "LE"]), m, y, rng.choice([2022, 2023, 2024]))
            if rng.random() < 0.4:
                mo = self.fresh("mo")
                self.emit("MONTH", mo, c.reg)
                m2 = self.fresh("f")
                self.emit("LE", m2, mo, rng.randint(1, 12))
                m3 = self.fresh("f")
                self.emit("AND", m3, m, m2)
                return m3
            return m
        lit, _ = self.literal_for(c)
        m = self.fresh("f")
        self.emit(rng.choice(["GT", "GE", "LT", "LE", "EQ", "NE"]), m, c.reg, lit)
        return m

    def predicate2(self, cols):
        """predicate(), sometimes negated (3-valued NOT) or a null-safe IS test."""
        rng = self.rng
        r = rng.random()
        if self.force == "notnull_filter":
            self.force = None
            nb = [c for c in cols if c.nullable and c.type != "BOOL"] or cols
            c = rng.choice(nb)
            m = self.fresh("f")
            self.emit("ISNULL", m, c.reg)
            m2 = self.fresh("f")
            self.emit("NOT", m2, m)
            return m2
        if self.force == "is_null":
            self.force = None
            r = 0.0
        if r < 0.08:
            c = rng.choice(cols)
            m = self.fresh("f")
            self.emit("IS", m, c.reg, "NULL")
            if rng.random() < 0.6:
                m2 = self.fresh("f")
                self.emit("NOT", m2, m)
                return m2
            return m
        if r < 0.14:
            same = [(x, y) for x in cols for y in cols if x is not y and x.type == y.type and x.type != "BOOL"]
            if same:
                x, y = rng.choice(same)
                m = self.fresh("f")
                self.emit(rng.choice(["IS", "EQ", "LT"]), m, x.reg, y.reg)
                return m
        m = self.predicate(cols)
        if r > 0.85:
            m2 = self.fresh("f")
            self.emit("NOT", m2, m)
            return m2
        return m

    def conj(self, cols, k):
        m = self.predicate2(cols)
        for _ in range(k - 1):
            m2 = self.predicate2(cols)
            r = self.fresh("f")
            self.emit("AND" if self.rng.random() < 0.8 else "OR", r, m, m2)
            m = r
        return m

    def filt(self, cols, k=None):
        m = self.conj(cols, k or self.rng.choice([1, 1, 2, 3]))
        if self.rng.random() < 0.12:              # "exclude ...": NOT over a whole conjunction (3-valued)
            n = self.fresh("x")
            self.emit("NOT", n, m)
            m = n
        i = self.fresh("w")
        self.emit("IDX", i, m)
        return self.gather_all(cols, i)

    # ---- computed columns
    def computed(self, cols):
        rng, out = self.rng, []
        strs = [c for c in cols if c.type == "STR"]
        nums = [c for c in cols if c.type in NUMT]
        if strs and rng.random() < 0.6:
            a = rng.choice(strs)
            b = rng.choice(strs)
            x = self.fresh("l")
            self.emit("NVL", x, a.reg, "''")
            y = self.fresh("l")
            self.emit("CAT", y, x, rng.choice(["' / '", "' '", "'-'"]))
            z = self.fresh("l")
            self.emit("CAT", z, y, b.reg)
            w = self.fresh("lab")
            self.emit("LEFT", w, z, rng.choice([8, 12, 20, 40]), comment="sheet column width")
            out.append(Col(w, "STR"))
        if len(nums) >= 2 and rng.random() < 0.5:
            a, b = rng.sample(nums, 2)
            x = self.fresh("v")
            self.emit("MUL", x, a.reg, b.reg)
            out.append(Col(x, "NUM" if "NUM" in (a.type, b.type) else "INT"))
        if nums and rng.random() < 0.15:
            a, b = rng.choice(nums), rng.choice(nums)
            x = self.fresh("q")
            self.emit("DIV", x, a.reg, b.reg, comment="ratio")
            out.append(Col(x, "NUM"))
        if rng.random() < 0.3 and cols:   # dead "display copy"
            c = rng.choice(cols)
            if c.type == "STR":
                self.emit("UPPER", self.fresh("d"), c.reg, comment="display copy")
            elif c.type == "DATE":
                self.emit("DOW", self.fresh("d"), c.reg, comment="weekday split (removed)")
        return out

    def guarded_div(self, cols):
        """keep rows with a non-zero divisor, then divide (the filter guards the DIV)."""
        nums = [c for c in cols if c.type in NUMT]
        if not nums:
            return cols
        ia, ib = cols.index(self.rng.choice(nums)), cols.index(self.rng.choice(nums))
        m = self.fresh("nz")
        self.emit("NE", m, cols[ib].reg, 0, comment="avoid divide by zero")
        i = self.fresh("w")
        self.emit("IDX", i, m)
        cols = self.gather_all(cols, i)
        a2, b2 = cols[ia], cols[ib]
        op = self.rng.choice(["DIV", "DIV", "IDIV", "MOD"]) if a2.type == b2.type == "INT" else "DIV"
        q = self.fresh("ratio")
        self.emit(op, q, a2.reg, b2.reg)
        return cols + [Col(q, "NUM" if op == "DIV" else "INT")]

    # ---- joins
    def join_options(self, cols):
        opts = []
        for c in cols:
            if not c.table:
                continue
            for k, v in self.s[c.table].get("refs", {}).items():
                if k.lower() == c.name.lower():
                    pt, pc = v.split(".")
                    pt = next(t for t in self.s if t.lower() == pt.lower())
                    opts.append(("fk", c, pt, pc))
        tabs = {c.table for c in cols if c.table}
        for t in self.s:
            for k, v in self.s[t].get("refs", {}).items():
                pt, pc = v.split(".")
                for c in cols:
                    if c.table and c.table.lower() == pt.lower() and c.name.lower() == pc.lower() and t not in tabs:
                        opts.append(("rev", c, t, k))
        for c in cols:                    # same-type columns without refs (e.g. no-key tables)
            for t in self.s:
                if t in tabs:
                    continue
                for tc in self.tcols(t):
                    if tc["type"] == c.type and c.type == "INT" and tc["name"].lower().endswith(c.name.lower()[-2:]) \
                            and self.rng.random() < 0.05:
                        opts.append(("loose", c, t, tc["name"]))
        return opts

    def join(self, cols):
        opts = self.join_options(cols)
        if not opts:
            return cols, False
        kind, c, t, tc = self.rng.choice(opts)
        other = self.load_table(t)
        oc = next(o for o in other if o.name.lower() == tc.lower())
        li, ri = self.fresh("j"), self.fresh("j")
        op = "NLJOIN" if self.rng.random() < 0.15 else "HJOIN"
        if c.nullable and oc.nullable and self.rng.random() < 0.3:
            self.emit(op, li, ri, c.reg, oc.reg, "NULLEQ", comment="old outer-join port: NULL keys match")
        else:
            self.emit(op, li, ri, c.reg, oc.reg)
        return self.gather_all(cols, li) + self.gather_all(other, ri), True

    # ---- idioms
    def self_join_agg(self, cols):
        """per row: aggregate over the rows sharing a key (correlated subquery style)."""
        rng = self.rng
        keys = [c for c in cols if c.type in ("STR", "INT") and c.table]
        if self.force == "self_join_nulleq":
            keys = [c for c in keys if c.nullable] or keys
        vals = [c for c in cols if c.type in NUMT]
        if not keys or not vals:
            return cols, None
        k, v = rng.choice(keys), rng.choice(vals)
        kr = k.reg
        if k.type == "STR" and rng.random() < 0.6:
            a = self.fresh("n")
            self.emit("NULLIFE", a, k.reg)
            b = self.fresh("t")
            self.emit("RTRIM", b, a)
            kr = self.fresh("u")
            self.emit("UPPER", kr, b)
        a, b = self.fresh("a"), self.fresh("b")
        if k.nullable and (rng.random() < 0.3 or self.force == "self_join_nulleq"):
            self.emit("HJOIN", a, b, kr, kr, "NULLEQ", comment="every pair with the same key, NULLs together")
        else:
            self.emit("HJOIN", a, b, kr, kr, comment="every pair with the same key")
        vb = self.fresh()
        self.emit("GATHER", vb, v.reg, b)
        g = self.fresh("g")
        mode = rng.choice(["max", "min", "cnt_less"])
        if mode == "cnt_less":
            va = self.fresh()
            self.emit("GATHER", va, v.reg, a)
            h = self.fresh("hit")
            self.emit("LT", h, vb, va)
            one = self.fresh("one")
            self.emit("IF", one, h, 1, 0)
            self.emit("GROUP", g, a)
            agg = self.fresh("cnt")
            self.emit("GSUM", agg, g, one)
            t = "INT"
        else:
            self.emit("GROUP", g, a)
            agg = self.fresh(mode)
            self.emit("GMAX" if mode == "max" else "GMIN", agg, g, vb)
            t = v.type
        f = self.fresh("f")
        self.emit("GFIRST", f, g)
        row = self.fresh("row")
        self.emit("GATHER", row, a, f)
        out = self.gather_all(cols, row)
        return out + [Col(agg, t)], agg

    # ---- endings
    def sort_keys(self, cols, n):
        ks = self.rng.sample(cols, min(n, len(cols)))
        return [f"{c.reg} {self.rng.choice(['ASC', 'DESC'])} {self.rng.choice(['NF', 'NL'])}" for c in ks]

    def finish(self, cols):
        rng = self.rng
        kind = rng.choice(["proj", "sort", "sort", "topn", "group", "gall", "topk", "topn_filter", "proj_bool"])
        if self.force in FINISH:
            kind = self.force
        out = rng.sample(cols, min(len(cols), rng.randint(1, 4)))
        if kind == "logic3":               # 3-valued AND / OR / NOT visible in the output
            nb = [c for c in cols if c.nullable and c.type != "BOOL"] or cols
            c = rng.choice([x for x in nb if x.type in ("INT", "NUM", "STR", "DATE")] or nb)
            lit, _ = self.literal_for(c)
            m1 = self.fresh("f")                  # NULL wherever c is NULL
            self.emit(rng.choice(["EQ", "NE", "GT", "LE"]), m1, c.reg, lit)
            m2 = self.predicate(cols)
            a, o, n = self.fresh("and"), self.fresh("or"), self.fresh("nand")
            self.emit("AND", a, m1, m2)
            self.emit("OR", o, m1, m2)
            self.emit("NOT", n, a)
            self.emit("OUT", *([c.reg for c in out[:2]] + [a, o, n]))
        elif kind == "countv":             # non-NULL count of a nullable column per group
            nb = [c for c in cols if c.nullable and c.type != "BOOL"] or cols
            gk = rng.choice([c for c in cols if c.type != "BOOL"])
            g, f, key, cv, cn = self.fresh("g"), self.fresh("f"), self.fresh("key"), self.fresh("cv"), self.fresh("n")
            self.emit("GROUP", g, gk.reg)
            self.emit("GFIRST", f, g)
            self.emit("GATHER", key, gk.reg, f)
            self.emit("GCOUNTV", cv, g, rng.choice(nb).reg)
            self.emit("GCOUNT", cn, g)
            self.emit("OUT", key, cv, cn)
        elif kind == "proj":
            self.emit("OUT", *[c.reg for c in out])
        elif kind == "proj_bool":
            m = self.conj(cols, rng.choice([1, 2, 2, 3]))
            self.emit("OUT", *([c.reg for c in out[:2]] + [m]))
        elif kind == "topk":
            keys = self.sort_keys(cols, rng.choice([1, 2]))
            p = self.fresh("k")
            self.emit("TOPK", p, rng.choice([1, 2, 5, 10, 25]), *keys)
            outs = self.gather_all(out, p)
            self.emit("OUT", *[c.reg for c in outs])
        elif kind == "topn_filter":           # top N first, then filter the N (order of the two matters)
            keys = self.sort_keys(cols, rng.choice([1, 2]))
            p = self.fresh("s")
            self.emit("SORT", p, *keys)
            outs = self.gather_all(cols, p)
            i = self.fresh("k")
            self.emit("IOTA", i, outs[0].reg)
            self.emit("SLICE", i, i, rng.choice([2, 3, 5, 10]))
            outs = self.gather_all(outs, i)
            outs = self.filt(outs, 1)
            self.emit("OUT", *[c.reg for c in outs[:rng.randint(1, 4)]])
        elif kind in ("sort", "topn"):
            keys = self.sort_keys(cols, rng.choice([1, 2, 2]))
            p = self.fresh("s")
            self.emit("SORT", p, *keys)
            outs = self.gather_all(out, p)
            if kind == "topn":
                i = self.fresh("k")
                self.emit("IOTA", i, outs[0].reg)
                self.emit("SLICE", i, i, rng.choice([1, 3, 5, 10]))
                outs = self.gather_all(outs, i)
            self.emit("OUT", *[c.reg for c in outs])
        elif kind == "group":
            gk = rng.choice([c for c in cols if c.type != "BOOL"])
            g = self.fresh("g")
            self.emit("GROUP", g, gk.reg)
            f = self.fresh("f")
            self.emit("GFIRST", f, g)
            key = self.fresh("key")
            self.emit("GATHER", key, gk.reg, f)
            aggs = [key]
            nums = [c for c in cols if c.type in NUMT]
            for _ in range(rng.randint(1, 3)):
                a = self.fresh("agg")
                choice = rng.choice(["GCOUNT", "GSUM", "GMIN", "GMAX", "GCOUNTV"])
                if choice == "GCOUNT":
                    self.emit("GCOUNT", a, g)
                elif choice == "GCOUNTV":
                    self.emit("GCOUNTV", a, g, rng.choice(cols).reg)
                elif nums:
                    self.emit(choice, a, g, rng.choice(nums).reg)
                else:
                    self.emit("GCOUNT", a, g)
                aggs.append(a)
            if rng.random() < 0.7:
                s = self.fresh("s")
                self.emit("SORT", s, f"{key} ASC NF")
                outs = []
                for a in aggs:
                    r = self.fresh()
                    self.emit("GATHER", r, a, s)
                    outs.append(r)
                aggs = outs
            self.emit("OUT", *aggs)
        else:
            nums = [c for c in cols if c.type in NUMT] or cols
            g = self.fresh("g")
            self.emit("GALL", g, nums[0].reg)
            a, b = self.fresh("tot"), self.fresh("n")
            if nums[0].type in NUMT:
                self.emit("GSUM", a, g, nums[0].reg)
            else:
                self.emit("GCOUNTV", a, g, nums[0].reg)
            self.emit("GCOUNT", b, g)
            self.emit("OUT", a, b)

    def build(self):
        rng = self.rng
        tabs = [t for t in self.s if self.s[t].get("stats", {}).get("rows", 1) > 0] or list(self.s)
        if self.force == "sorted_sort":
            tabs = [t for t in tabs if self.s[t].get("sorted")] or tabs
        t0 = rng.choice(tabs)
        self.lines.append(f"; generated legacy-style program over {t0}")
        cols = self.load_table(t0)
        sp = self.s[t0]
        if sp.get("sorted") and (rng.random() < 0.3 or self.force == "sorted_sort"):   # sort on a sorted table: identity
            sk = [next(c for c in cols if c.name.lower() == k.lower()) for k in sp["sorted"]]
            p = self.fresh("s")
            self.emit("SORT", p, *[f"{c.reg} ASC NF" for c in sk], comment="keep the stored order stable")
            cols = self.gather_all(cols, p)
        many = self.force in ("topn_filter", "topk", "topn")      # cut-off idioms need many rows
        if rng.random() < 0.3 and not many:
            cols = self.filt(cols)
        late_filter = (rng.random() < 0.7 and not many) or self.force in ("notnull_filter", "is_null")
        for _ in range(rng.choice([0, 1, 1, 2, 3])):
            cols, _ = self.join(cols)
            if len(cols) > 40:
                break
        extra = self.computed(cols)
        cols = cols + extra
        if rng.random() < 0.15 or self.force == "guarded_div":
            cols = self.guarded_div(cols)
        if rng.random() < 0.25 or self.force == "self_join_nulleq":
            cols, _ = self.self_join_agg(cols)
        if rng.random() < 0.3:      # sort, then filter (filter-before-sort is equivalent)
            keys = self.sort_keys(cols, 2)
            p = self.fresh("s")
            self.emit("SORT", p, *keys, comment="audit trail order")
            cols = self.gather_all(cols, p)
        if late_filter:
            cols = self.filt(cols)
        self.finish(cols)
        return "\n".join(self.lines) + "\n"


FINISH = ("proj", "sort", "topn", "group", "gall", "topk", "topn_filter", "proj_bool", "logic3", "countv")
# idioms a corpus cycles through so each one is covered under every seed
IDIOMS = ("topn_filter", "logic3", "countv", "notnull_filter", "guarded_div", "self_join_nulleq", "is_null",
          "topk", "gall", "group", "proj_bool", "sorted_sort", "topn", None)


def gen_program(schema, rng, force=None):
    return P(schema, rng, force).build()


def random_schema(rng, name="gen"):
    """A random schema (columns + constraints) for generalization tests; stats come from bin/minivm later."""
    ntab = rng.randint(2, 4)
    tables = {}
    for ti in range(ntab):
        t = f"{name}_t{ti}"
        cols = [{"name": f"c{ti}_id", "type": "INT"}]
        for ci in range(rng.randint(2, 5)):
            cols.append({"name": f"c{ti}_{ci}", "type": rng.choice(["INT", "NUM", "STR", "STR", "DATE"])})
        spec = {"columns": cols}
        if rng.random() < 0.8:
            spec["key"] = [cols[0]["name"]]
        nn = [c["name"] for c in cols[1:] if rng.random() < 0.3]
        if nn:
            spec["not_null"] = nn
        chk = {}
        for c in cols[1:]:
            if c["type"] == "INT" and rng.random() < 0.3:
                chk[c["name"]] = [rng.randint(-5, 1), rng.choice([None, 100])]
        if chk:
            spec["check"] = chk
        if ti > 0:
            parents = [p for p in tables if "key" in tables[p]]
            if parents and rng.random() < 0.8:
                p = rng.choice(parents)
                fk = {"name": f"c{ti}_fk", "type": "INT"}
                cols.append(fk)
                spec["refs"] = {fk["name"]: f"{p}.{tables[p]['key'][0]}"}
                if rng.random() < 0.5:
                    spec.setdefault("not_null", []).append(fk["name"])
                if rng.random() < 0.3:
                    spec["sorted"] = [fk["name"]]
        tables[t] = spec
    return tables
