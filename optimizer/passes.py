"""Step 3: rewrite passes, run to a fixpoint.

Each pass takes an SSA program and returns (new program, changed?). Passes here only
delete work, so they can never add an error (BUILD_PLAN S1: "deleting ops is always
allowed"; removing an op that would have errored is fine because if the input
errors, anything goes).
  dce  dead-code elimination: drop instructions whose results never reach OUT
  cse  common-subexpression elimination: an identical (op, operands) computed twice,
       e.g. the same column loaded twice, is computed once and reused
"""
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


PASSES = [gather_chain, cse, dce]


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
