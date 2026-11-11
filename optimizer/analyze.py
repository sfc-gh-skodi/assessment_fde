"""Step 2: annotate every SSA register.

Info per register:
  kind      'col' (a column) or 'gset' (a group set)
  type      INT NUM STR DATE BOOL, or None if unknown
  nullable  may hold NULL
  table     source table if the values are a stored column (possibly gathered)
  column    source column name (with table)
  domain    id of the row set the column lives on (same domain => same rows, same order)
  into      for position columns: the domain they point into
  rows      estimated row count (stats = cost only, never correctness)
  bytes     estimated mean string bytes per value
  sorted_by stored-order keys still valid for this column's rows (LOAD / ascending subsets)
  ordered   rows are in a program-specified order (a SORT/TOPK result reached it)
  monotone  position column that is strictly ascending (IDX, IOTA, left side of a join, GFIRST)
"""
from .ir import key_reg, kind

ELEMENTWISE = {"ADD", "SUB", "MUL", "DIV", "IDIV", "MOD", "NEG", "WRAP", "TRUNC", "EQ", "NE", "LT", "LE", "GT",
               "GE", "IS", "AND", "OR", "NOT", "ISNULL", "NVL", "IF", "NULLIF", "NULLIFE", "UPPER", "RTRIM", "TRIM",
               "LEFT", "SUBSTR", "LEN", "CAT", "YEAR", "MONTH", "DAY", "DOW", "DATEADD", "DATEDIFF"}
BOOL_OPS = {"EQ", "NE", "LT", "LE", "GT", "GE", "IS", "AND", "OR", "NOT", "ISNULL"}
NEVER_NULL = {"IS", "ISNULL", "IDX", "IOTA", "SORT", "TOPK", "GID", "GCOUNT", "GCOUNTV", "HJOIN", "NLJOIN"}
STR_OPS = {"UPPER", "RTRIM", "TRIM", "LEFT", "SUBSTR", "CAT", "NULLIFE"}
INT_OPS = {"IDIV", "MOD", "WRAP", "TRUNC", "LEN", "YEAR", "MONTH", "DAY", "DOW", "DATEDIFF", "IDX", "IOTA",
           "SORT", "TOPK", "GID", "GFIRST", "GCOUNT", "GCOUNTV"}
FILTER_SEL = 0.33        # default selectivity of an IDX when we can't tell


class Info:
    __slots__ = ("kind", "type", "nullable", "table", "column", "domain", "into", "rows", "bytes",
                 "sorted_by", "ordered", "monotone", "ngroups")

    def __init__(self, **kw):
        self.kind, self.type, self.nullable, self.table, self.column = "col", None, True, None, None
        self.domain, self.into, self.rows, self.bytes = None, None, 1.0, 0.0
        self.sorted_by, self.ordered, self.monotone, self.ngroups = (), False, False, 1.0
        for k, v in kw.items():
            setattr(self, k, v)


def lit_type(tok):
    t = tok.strip()
    if t.startswith("'"):
        return "STR"
    if t.startswith("#"):
        return "DATE"
    if t in ("TRUE", "FALSE"):
        return "BOOL"
    if t == "NULL":
        return None
    return "NUM" if "." in t else "INT"


class Schema:
    def __init__(self, s):
        self.s = {t.lower(): v for t, v in s.items()}

    def table(self, t):
        return self.s.get(t.lower(), {})

    def col(self, tc):
        t, c = tc.split(".", 1)
        spec = self.table(t)
        for col in spec.get("columns", []):
            if col["name"].lower() == c.lower():
                return spec, col
        return spec, None

    def nn(self, t):
        spec = self.table(t)
        return {k.lower() for k in spec.get("key", [])} | {k.lower() for k in spec.get("not_null", [])}

    def stat(self, tc):
        t, c = tc.split(".", 1)
        cols = self.table(t).get("stats", {}).get("columns", {})
        for k, v in cols.items():
            if k.lower() == c.lower():
                return v
        return {}

    def rows(self, t):
        return float(self.table(t).get("stats", {}).get("rows", 100))


def analyze(prog, schema):
    S = Schema(schema)
    info = {}
    ndom = [0]

    def new_dom(tag):
        ndom[0] += 1
        return f"{tag}{ndom[0]}"

    def I(tok):
        return info.get(key_reg(tok)) if kind(tok) in ("reg", "key") else None

    for ins in prog:
        op, d, src = ins.op, (ins.dests[0] if ins.dests else None), ins.srcs
        ops = [I(t) for t in src]
        regs = [x for x in ops if x is not None]
        first = regs[0] if regs else Info()
        if op == "OUT":
            continue
        if op == "LOAD":
            spec, col = S.col(src[0])
            t = src[0].split(".")[0].lower()
            st = S.stat(src[0])
            nul = col is None or col["name"].lower() not in S.nn(t)
            info[d] = Info(type=col["type"] if col else None, nullable=nul, table=t, column=src[0].lower(),
                           domain="T:" + t, rows=S.rows(t), bytes=float(st.get("avg_bytes", 0) or 0),
                           sorted_by=tuple(k.lower() for k in spec.get("sorted", [])))
        elif op in ELEMENTWISE:
            if op in BOOL_OPS:
                ty = "BOOL"
            elif op in STR_OPS:
                ty = "STR"
            elif op in INT_OPS:
                ty = "INT"
            elif op == "DIV":
                ty = "NUM"
            elif op == "DATEADD":
                ty = "DATE"
            elif op in ("ADD", "SUB", "MUL"):
                ts = {x.type for x in regs} | {lit_type(t) for t in src if kind(t) == "lit"}
                ty = "INT" if ts == {"INT"} else "NUM"
            elif op == "IF":
                ts = {(I(t).type if I(t) else lit_type(t)) for t in src[1:]} - {None}
                ty = ts.pop() if len(ts) == 1 else None
            elif op == "NVL":
                ts = {(I(t).type if I(t) else lit_type(t)) for t in src} - {None}
                ty = ts.pop() if len(ts) == 1 else None
            else:                         # NEG NULLIF
                ty = first.type
            if op in NEVER_NULL:
                nul = False
            elif op == "NVL":
                b = I(src[1]) if len(src) > 1 else None
                nul = first.nullable and (b.nullable if b else src[1] == "NULL")
            elif op in ("IF",):
                nul = any((I(t).nullable if I(t) else t == "NULL") for t in src[1:])
            elif op in ("NULLIFE", "NULLIF", "DIV", "IDIV", "MOD"):
                nul = True
            elif op in ("AND", "OR"):
                nul = any(x.nullable for x in regs)
            else:
                nul = any(x.nullable for x in regs) or any(t == "NULL" for t in src)
            by = first.bytes if ty == "STR" else 0.0
            if op == "CAT":
                by = sum(x.bytes for x in regs) + sum(len(t) - 2 for t in src if kind(t) == "lit")
            info[d] = Info(type=ty, nullable=nul, domain=first.domain, rows=first.rows, bytes=by,
                           ordered=any(x.ordered for x in regs),
                           table=first.table if op in ("NULLIFE", "RTRIM", "TRIM", "UPPER") else None)
        elif op == "FILL":
            info[d] = Info(type=lit_type(src[0]), nullable=src[0] == "NULL", domain=first.domain, rows=first.rows,
                           ordered=first.ordered)
        elif op == "IOTA":
            info[d] = Info(type="INT", nullable=False, domain=first.domain, into=first.domain, rows=first.rows,
                           ordered=first.ordered, monotone=True)
        elif op == "IDX":
            dom = new_dom("F")
            info[d] = Info(type="INT", nullable=False, domain=dom, into=first.domain,
                           rows=max(1.0, first.rows * FILTER_SEL), monotone=True)
        elif op == "GATHER":
            s, i = ops[0] or Info(), ops[1] or Info()
            info[d] = Info(type=s.type, nullable=s.nullable or s.kind == "gset", table=s.table, column=s.column,
                           domain=i.domain, into=s.into, rows=i.rows, bytes=s.bytes,
                           sorted_by=s.sorted_by if (i.monotone and s.domain == i.into) else (),
                           ordered=i.ordered or (s.ordered and i.monotone),
                           monotone=s.monotone and i.monotone)
        elif op == "SLICE":
            n = float(src[1])
            info[d] = Info(type=first.type, nullable=first.nullable, table=first.table, column=first.column,
                           domain=new_dom("P"), into=first.into, rows=min(first.rows, n), bytes=first.bytes,
                           sorted_by=first.sorted_by, ordered=first.ordered, monotone=first.monotone)
        elif op in ("SORT", "TOPK"):
            keys = [I(t) for t in (src[1:] if op == "TOPK" else src)]
            k0 = next((k for k in keys if k), Info())
            n = min(k0.rows, float(src[0])) if op == "TOPK" else k0.rows
            info[d] = Info(type="INT", nullable=False, domain=new_dom("S"), into=k0.domain, rows=n, ordered=True)
        elif op in ("HJOIN", "NLJOIN"):
            l, r = ops[0] or Info(), ops[1] or Info()
            ld = S.stat(l.column) if l.column else {}
            rd = S.stat(r.column) if r.column else {}
            dl = max(1.0, float(ld.get("distinct", l.rows) or 1))
            dr = max(1.0, float(rd.get("distinct", r.rows) or 1))
            rows = max(1.0, l.rows * r.rows / max(dl, dr))
            dom = new_dom("J")
            li, ri = ins.dests
            info[ri] = Info(type="INT", nullable=False, domain=dom, into=r.domain, rows=rows, ordered=l.ordered)
            if li != ri:
                info[li] = Info(type="INT", nullable=False, domain=dom, into=l.domain, rows=rows,
                                ordered=l.ordered, monotone=True)
        elif op in ("GROUP", "GALL"):
            ng = 1.0
            if op == "GROUP":
                ng = 1.0
                for k in regs:
                    st = S.stat(k.column) if k.column else {}
                    ng *= max(1.0, float(st.get("distinct", k.rows) or 1))
                ng = min(first.rows, ng)
            info[d] = Info(kind="gset", domain=first.domain, rows=first.rows, ngroups=ng,
                           ordered=any(x.ordered for x in regs))
            info[d].into = new_dom("G")      # domain of this group set's aggregates
        elif op in ("GFIRST", "GCOUNT", "GCOUNTV", "GSUM", "GMIN", "GMAX"):
            g = first
            arg = ops[1] if len(ops) > 1 else None
            ty = {"GFIRST": "INT", "GCOUNT": "INT", "GCOUNTV": "INT"}.get(op, arg.type if arg else None)
            if op == "GSUM" and arg and arg.type == "INT":
                ty = "INT"
            info[d] = Info(type=ty, nullable=op not in ("GCOUNT", "GCOUNTV"), domain=g.into, rows=g.ngroups,
                           into=g.domain if op == "GFIRST" else None, ordered=g.ordered,
                           monotone=op == "GFIRST", bytes=arg.bytes if arg and op in ("GMIN", "GMAX") else 0.0)
        elif op == "GID":
            g = first
            info[d] = Info(type="INT", nullable=False, domain=g.domain, into=g.into, rows=g.rows)
        else:
            raise ValueError(f"unknown opcode {op}")
    return info
