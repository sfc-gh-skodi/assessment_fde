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


def dce(prog):
    live = set()
    keep = []
    for ins in reversed(prog):
        if ins.op == "OUT" or any(d in live for d in ins.dests):
            keep.append(ins)
            live.update(ins.regs_used())
    keep.reverse()
    return keep, len(keep) != len(prog)


def cse(prog):
    seen, sub, out, changed = {}, {}, [], False
    for ins in prog:
        srcs = [_rename(t, sub) for t in ins.srcs]
        ins = Instr(ins.op, ins.dests, srcs)
        if ins.op == "OUT":
            out.append(ins)
            continue
        same_dest = len(ins.dests) == 2 and ins.dests[0] == ins.dests[1]
        key = (ins.op, tuple(srcs), same_dest)
        if key in seen:
            for d, e in zip(ins.dests, seen[key]):
                sub[d] = e
            changed = True
            continue
        seen[key] = ins.dests
        out.append(ins)
    return out, changed


PASSES = [cse, dce]


def run(prog, deadline=None):
    """Apply PASSES until none changes anything (or the deadline passes)."""
    import time
    for _ in range(50):
        changed = False
        for p in PASSES:
            prog, c = p(prog)
            changed |= c
        if not changed or (deadline and time.monotonic() > deadline):
            break
    return prog
