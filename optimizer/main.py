#!/usr/bin/env python3
"""./optimize program.mini schema.json -> prints an equivalent, cheaper program.

Pipeline: 1 parse -> SSA, 2 annotate, 3 passes to a fixpoint, 4 estimate cost, 5 emit.
Global guard: on any error, a missed deadline, or no estimated gain, print the input unchanged.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optimizer import analyze, cost, ir, passes  # noqa: E402

DEADLINE_S = 0.7
PASS_BUDGET_S = 0.4      # passes stop here so analyze/estimate/emit fit under DEADLINE_S


def optimize(text, schema):
    t0 = time.monotonic()
    prog = ir.to_ssa(ir.parse(text))                    # 1
    before = cost.estimate(prog, schema)                 # 2 + 4 (annotate inside)
    new = passes.run(prog, schema, deadline=t0 + PASS_BUDGET_S)     # 3
    analyze.analyze(new, schema)                         # 2: re-annotate; raises on anything malformed
    after = cost.estimate(new, schema)                   # 4
    if after >= before or time.monotonic() - t0 > DEADLINE_S:
        return text
    out = ir.emit(ir.reuse_registers(new))               # 5: reuse dead registers' names
    if not ir.same_shape(new, ir.to_ssa(ir.parse(out))): # re-read it: must be the same program
        out = ir.emit(new)
    return out


def main(argv):
    if len(argv) != 2:
        print("usage: optimize program.mini schema.json", file=sys.stderr)
        return 2
    text = open(argv[0]).read()
    try:
        out = optimize(text, json.load(open(argv[1])))
    except Exception:
        out = text
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
