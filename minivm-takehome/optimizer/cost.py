"""Step 4: estimate a program's cycles with the docs/cycles.md cost table.

Uses the row / string-byte estimates from analyze() (stats are used for cost only).
Absolute numbers are rough; the estimate is used to compare two versions of the
same program, so the same estimator on both sides is what matters.
"""
import math

from .analyze import ELEMENTWISE, analyze
from .ir import key_reg, kind

BASE = 4
PER_ELEM = {"DIV": 6, "IDIV": 6, "MOD": 6, "TRUNC": 2, "YEAR": 2, "MONTH": 2, "DAY": 2, "DOW": 2,
            "DATEADD": 2, "DATEDIFF": 2}
CMP = {"EQ", "NE", "LT", "LE", "GT", "GE", "IS"}
NO_BYTES = {"ISNULL", "NVL", "IF", "NULLIF", "NULLIFE", "AND", "OR", "NOT"}


def instr_cost(ins, info):
    op = ins.op
    if op == "OUT":
        return BASE
    I = lambda t: info.get(key_reg(t)) if kind(t) in ("reg", "key") else None
    d = info.get(ins.dests[0]) if ins.dests else None
    n = d.rows if d else 1.0
    if op in ELEMENTWISE:
        per = PER_ELEM.get(op, 1)
        regs = [I(t) for t in ins.srcs if I(t)]
        lit_bytes = sum(len(t) - 2 for t in ins.srcs if kind(t) == "lit" and t.startswith("'"))
        if op in CMP:
            b = min([x.bytes for x in regs] + ([lit_bytes] if lit_bytes else [])) if regs else 0
        elif op == "LEN":
            b = regs[0].bytes if regs else 0
        elif op in NO_BYTES:
            b = 0
        else:
            b = sum(x.bytes for x in regs) + lit_bytes + (d.bytes if d and d.type == "STR" else 0)
        return BASE + n * (per + b)
    if op in ("LOAD", "FILL", "IOTA", "GATHER", "SLICE"):
        return BASE + n
    if op == "IDX":
        return BASE + I(ins.srcs[0]).rows
    if op in ("SORT", "TOPK"):
        keys = ins.srcs[1:] if op == "TOPK" else ins.srcs
        k0 = I(keys[0])
        m = k0.rows if k0 else 1.0
        per_cmp = 2 + (k0.bytes if k0 else 0) + 0.5 * 2 * (len(keys) - 1)
        if op == "SORT":
            return BASE + 2 * m + m * max(1.0, math.log2(max(m, 2))) * per_cmp
        k = float(ins.srcs[0])
        return BASE + 2 * m + m * per_cmp + min(m, k) * math.log2(max(k, 2)) * per_cmp + min(m, k) * 2
    if op == "HJOIN":
        l, r = I(ins.srcs[0]), I(ins.srcs[1])
        out = info[ins.dests[1]].rows
        return BASE + l.rows * (6 + l.bytes) + r.rows * (6 + r.bytes) + 2 * out
    if op == "NLJOIN":
        l, r = I(ins.srcs[0]), I(ins.srcs[1])
        out = info[ins.dests[1]].rows
        return BASE + l.rows * r.rows * (1 + min(l.bytes, r.bytes)) + 2 * out
    if op == "GROUP":
        regs = [I(t) for t in ins.srcs if I(t)]
        return BASE + regs[0].rows * (6 + sum(x.bytes for x in regs))
    if op in ("GALL",):
        return BASE + I(ins.srcs[0]).rows
    g = I(ins.srcs[0]) if ins.srcs else None
    rows = g.rows if g else 1.0
    if op in ("GID", "GFIRST"):
        return BASE + rows
    if op in ("GCOUNT", "GCOUNTV", "GSUM"):
        return BASE + 2 * rows
    if op in ("GMIN", "GMAX"):
        a = I(ins.srcs[1])
        return BASE + rows * (2 + (a.bytes if a else 0))
    return BASE


def estimate(prog, schema, info=None):
    info = info if info is not None else analyze(prog, schema)
    return sum(instr_cost(i, info) for i in prog)
