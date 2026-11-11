"""Step 3: rewrite passes, run to a fixpoint.

Each pass takes an SSA program and returns (new program, changed?). Passes here only
delete work, so they can never add an error (BUILD_PLAN S1: "deleting ops is always
allowed"; removing an op that would have errored is fine because if the input
errors, anything goes).
  dce  dead-code elimination: drop instructions whose results never reach OUT
  cse  common-subexpression elimination: an identical (op, operands) computed twice,
       e.g. the same column loaded twice, is computed once and reused
"""
from .analyze import ELEMENTWISE, analyze
from .cost import instr_cost
from .ir import Instr, key_reg, kind


def _rename(tok, sub):
    if kind(tok) not in ("reg", "key"):
        return tok
    r = key_reg(tok)
    return tok.replace(r, sub[r], 1) if r in sub else tok


def dce(prog, schema=None):
    live = set()
    keep = []
    for ins in reversed(prog):
        if ins.op == "OUT" or any(d in live for d in ins.dests):
            keep.append(ins)
            live.update(ins.regs_used())
    keep.reverse()
    return keep, len(keep) != len(prog)


# Operand order doesn't change the result (or which rows error) for these:
# AND/OR are symmetric [doc: logic.md#and-or]; ADD/MUL exact then rounded once;
# EQ/NE/IS compare both ways the same. LT a,b is GT b,a (same for LE/GE).
COMMUTATIVE = {"AND", "OR", "ADD", "MUL", "EQ", "NE", "IS"}
FLIP = {"LT": "GT", "GT": "LT", "LE": "GE", "GE": "LE"}


def _cse_key(op, srcs, same_dest):
    if op == "LOAD":                       # table and column names ignore case
        return (op, (srcs[0].lower(),), same_dest)
    if op in COMMUTATIVE and len(srcs) == 2:
        return (op, tuple(sorted(srcs)), same_dest)
    if op in FLIP and len(srcs) == 2 and srcs[1] < srcs[0]:
        return (FLIP[op], (srcs[1], srcs[0]), same_dest)
    return (op, tuple(srcs), same_dest)


def cse(prog, schema=None):
    seen, sub, out, changed = {}, {}, [], False
    for ins in prog:
        srcs = [_rename(t, sub) for t in ins.srcs]
        ins = Instr(ins.op, ins.dests, srcs)
        if ins.op == "OUT":
            out.append(ins)
            continue
        same_dest = len(ins.dests) == 2 and ins.dests[0] == ins.dests[1]
        # AND/OR x, x is x (TRUE/FALSE/NULL each map to themselves; only a non-BOOL x
        # would differ, by erroring, and removing an error is allowed)
        if ins.op in ("AND", "OR") and len(srcs) == 2 and srcs[0] == srcs[1] and kind(srcs[0]) == "reg":
            sub[ins.dests[0]] = srcs[0]
            changed = True
            continue
        key = _cse_key(ins.op, srcs, same_dest)
        if key in seen:
            for d, e in zip(ins.dests, seen[key]):
                sub[d] = e
            changed = True
            continue
        seen[key] = ins.dests
        out.append(ins)
    return out, changed


def _defs(prog):
    return {d: ins for ins in prog for d in ins.dests}


def _fresh(prog):
    """-> new_name(): register names not used anywhere in prog."""
    taken = {d for ins in prog for d in ins.dests}
    n = [0]

    def new():
        while True:
            n[0] += 1
            name = f"t_{n[0]}"
            if name not in taken:
                taken.add(name)
                return name
    return new


def gather_chain(prog, schema=None):
    """Rule 1: GATHER(GATHER(s, i), j) -> GATHER(s, GATHER(i, j)).

    d[k] = s[i[j[k]]] either way. The composed form only reads the entries of i
    that j picks, so it can only drop an error (an out-of-range i entry j skips),
    never add one. Many columns gathered by the same i then j share one GATHER(i, j)
    (cse), and the inner GATHER(s, i) dies (dce)."""
    defs, new, out, changed = _defs(prog), _fresh(prog), [], False
    # only when every use of the inner GATHER is as a GATHER source, so it dies;
    # otherwise the rewrite adds a GATHER(i, j) and saves nothing
    other_use = set()
    for ins in prog:
        for k, t in enumerate(ins.srcs):
            if kind(t) in ("reg", "key") and not (ins.op == "GATHER" and k == 0):
                other_use.add(key_reg(t))
    for ins in prog:
        if ins.op == "GATHER" and kind(ins.srcs[0]) == "reg" and kind(ins.srcs[1]) == "reg":
            inner = defs.get(ins.srcs[0])
            if (inner is not None and inner.op == "GATHER" and inner.dests[0] not in other_use
                    and all(kind(t) == "reg" for t in inner.srcs)):
                s, i = inner.srcs
                t = new()
                out.append(Instr("GATHER", [t], [i, ins.srcs[1]]))
                ins = Instr("GATHER", ins.dests, [s, t])
                changed = True
        out.append(ins)
    return out, changed


def _uses(prog):
    """-> {reg: [(instr, operand position)]}"""
    u = {}
    for ins in prog:
        for k, t in enumerate(ins.srcs):
            if kind(t) in ("reg", "key"):
                u.setdefault(key_reg(t), []).append((ins, k))
    return u


def _injective(prog):
    """Position columns that name each row at most once (no repeats): IDX, IOTA,
    SORT, TOPK, GFIRST, and SLICE / GATHER built only from those. Join outputs
    can repeat rows, so they are left out."""
    inj = set()
    for ins in prog:
        if ins.op in ("IDX", "IOTA", "SORT", "TOPK", "GFIRST"):
            inj.add(ins.dests[0])
        elif ins.op == "SLICE" and ins.srcs[0] in inj:
            inj.add(ins.dests[0])
        elif ins.op == "GATHER" and ins.srcs[0] in inj and ins.srcs[1] in inj:
            inj.add(ins.dests[0])
    return inj


def filter_first(prog, schema=None):
    """Rule 2: GATHER(E(a, b, ...), i) -> E(GATHER(a, i), GATHER(b, i), ...) for an
    element-wise E (or FILL) whose only uses are GATHERs by the same index i.

    Element-wise means row k of the result depends only on row k of the operands,
    so both forms give the same values in the same order. The new form runs E only
    on the rows i picks, a subset of the rows it ran on before, so it can't add an
    error (a DIV by zero on a dropped row goes away; none appears). Only when i
    names each row at most once, and the price list says it's cheaper."""
    if schema is None:
        return prog, False
    info = analyze(prog, schema)
    uses, inj, new = _uses(prog), _injective(prog), _fresh(prog)
    push = {}                                    # E dest -> index i
    for ins in prog:
        if not (ins.op in ELEMENTWISE or ins.op == "FILL") or len(ins.dests) != 1:
            continue
        e = ins.dests[0]
        us = uses.get(e, [])
        if not us or any(u.op != "GATHER" or k != 0 for u, k in us):
            continue
        idx = {u.srcs[1] for u, k in us}
        if len(idx) != 1:
            continue
        i = idx.pop()
        if i not in inj or i not in info or e not in info:
            continue
        regs = {t for t in ins.srcs if kind(t) == "reg"}
        n, m = max(info[e].rows, 1.0), info[i].rows
        ce = instr_cost(ins, info)
        old = ce + (4 + m)
        newc = len(regs) * (4 + m) + 4 + (ce - 4) * m / n
        if newc < old:
            push[e] = i
    if not push:
        return prog, False
    defs = _defs(prog)
    out = []
    for ins in prog:
        if ins.op == "GATHER" and ins.srcs[0] in push and push[ins.srcs[0]] == ins.srcs[1]:
            e_ins, i = defs[ins.srcs[0]], ins.srcs[1]
            if e_ins.op == "FILL":
                out.append(Instr("FILL", ins.dests, [e_ins.srcs[0], i]))
                continue
            sub = {}
            for t in e_ins.srcs:
                if kind(t) == "reg" and t not in sub:
                    sub[t] = new()
                    out.append(Instr("GATHER", [sub[t]], [t, i]))
            out.append(Instr(e_ins.op, ins.dests, [sub.get(t, t) if kind(t) == "reg" else t
                                                   for t in e_ins.srcs]))
            continue
        out.append(ins)
    return out, True


def sorted_sort(prog, schema=None):
    """Rule 3: SORT over rows already in stored order -> IOTA (positions 0..n-1).

    The schema's `sorted` constraint says rows are stored in ascending order of
    those columns as ASC NF sorts them (docs/running.md). If every key is ASC NF,
    the keys are a prefix of that column list, and analyze says the key rows are
    still in stored order (sorted_by: a LOAD, or gathered through ascending
    positions), the rows are already ordered, so the stable SORT returns 0..n-1.
    This is a schema constraint, true of every table set; stats are not used.

    Also GATHER(s, IOTA(x)) -> s when s and x are the same rows: d[k] = s[k]."""
    if schema is None:
        return prog, False
    info = analyze(prog, schema)
    defs, out, changed, sub = _defs(prog), [], False, {}
    for ins in prog:
        ins = Instr(ins.op, ins.dests, [_rename(t, sub) for t in ins.srcs])
        if ins.op == "SORT" and _already_sorted(ins.srcs, info):
            out.append(Instr("IOTA", ins.dests, [key_reg(ins.srcs[0])]))
            changed = True
            continue
        if ins.op == "GATHER" and all(kind(t) == "reg" for t in ins.srcs):
            s, i = ins.srcs
            di = defs.get(i)
            si, xi = info.get(s), info.get(di.srcs[0]) if di is not None and di.op == "IOTA" else None
            if si is not None and xi is not None and si.kind == "col" and si.domain is not None \
                    and si.domain == xi.domain:
                sub[ins.dests[0]] = s
                changed = True
                continue
        out.append(ins)
    return out, changed


def _already_sorted(keys, info):
    cols, dom, valid = [], None, None
    for t in keys:
        p = t.split()
        if kind(t) != "key" or p[1:] != ["ASC", "NF"]:
            return False
        r = info.get(p[0])
        if r is None or r.kind != "col" or not r.column or not r.sorted_by or r.domain is None:
            return False
        tab, col = r.column.split(".", 1)
        if dom is None:
            dom, valid, table = r.domain, r.sorted_by, tab
        if r.domain != dom or r.sorted_by != valid or tab != table:
            return False
        cols.append(col)
    return bool(cols) and tuple(cols) == tuple(valid[:len(cols)])


PASSES = [gather_chain, filter_first, sorted_sort, cse, dce]


def run(prog, schema=None, deadline=None):
    """Apply PASSES until none changes anything (or the deadline passes)."""
    import time
    for _ in range(50):
        changed = False
        for p in PASSES:
            prog, c = p(prog, schema)
            changed |= c
        if not changed or (deadline and time.monotonic() > deadline):
            break
    return prog
