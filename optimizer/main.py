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


def optimize(text, schema):
    t0 = time.monotonic()
    prog = ir.to_ssa(ir.parse(text))                    # 1
    before = cost.estimate(prog, schema)                 # 2 + 4 (annotate inside)
    new = passes.run(prog, deadline=t0 + DEADLINE_S)     # 3
    analyze.analyze(new, schema)                         # 2: re-annotate; raises on anything malformed
    after = cost.estimate(new, schema)                   # 4
    if after >= before or time.monotonic() - t0 > DEADLINE_S:
        return text
    return ir.emit(new)                                  # 5


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
