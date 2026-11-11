#!/usr/bin/env python3
"""Self-test of the evaluator's comparator and analyses (evaluator/compare.py), < 10 s.

  python3 tools/eval_selftest.py [-v]

Groups:
  CMP    value / multiset rules (BOOL vs INT, typed STR '1.0' vs '1.00', NUM scale, tolerance, NULL)
  ORDER  does the original specify output order? (case, overwrites, joins, groups, comments)
  TIE    tie blocks, instrumented sort keys, TOPK/SLICE cut-off WARN vs DEFECT (run on bin/minivm)
  TYPES  static output types
  CANON  fast-path canonical text (same program up to register names / case only)
  VM     bin/minivm facts the evaluator relies on
Exit 1 if any check fails.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.dont_write_bytecode = True
sys.path.insert(0, REPO)
from evaluator import compare as C  # noqa: E402
from evaluator import vm            # noqa: E402

results = []
TMP = tempfile.mkdtemp(prefix="minivm_selftest_")


def check(group, name, got, want):
    results.append((group, name, got == want, got, want))


def M(a, b, types=()):
    return C.same_multiset(a, b, list(types))


def P(text):
    return C.parse(text)


def res(rows, n=None):
    return {"ncols": n if n is not None else (len(rows[0]) if rows else 1), "rows": rows, "cycles": 0}


# ---------------- CMP ----------------
check("CMP", "rows reordered, multiset equal", M([[1, "a"], [2, "b"]], [[2, "b"], [1, "a"]]), True)
check("CMP", "NUM scale '2.0' vs '2.00' (untyped)", M([["2.0"]], [["2.00"]]), True)
check("CMP", "NUM scale '2.0' vs '2.00' (typed NUM)", M([["2.0"]], [["2.00"]], ["NUM"]), True)
check("CMP", "INT 2 vs NUM '2.0'", M([[2]], [["2.0"]]), True)
check("CMP", "negative zero '-0.0' vs '0'", M([["-0.0"]], [["0"]]), True)
check("CMP", "big INT as string vs JSON int", M([["18446744073709551614"]], [[18446744073709551614]]), True)
check("CMP", "within 1e-6 relative", M([["1000000.0"]], [["1000000.9"]]), True)
check("CMP", "beyond 1e-6 relative", M([["1000000.0"]], [["1000002"]]), False)
check("CMP", "1e-5 drift is a defect", M([["100.00000"]], [["100.00100"]]), False)
check("CMP", "INT off by one at 1e7 (within 1e-6: spec allows)", M([[10000000]], [[10000001]]), True)
check("CMP", "0 vs 1e-7 (pure relative tolerance)", M([["0"]], [["0.0000001"]]), False)
check("CMP", "BOOL true vs INT 1", M([[True]], [[1]]), False)
check("CMP", "BOOL false vs INT 0", M([[False]], [[0]]), False)
check("CMP", "BOOL true vs STR 'true'", M([[True]], [["true"]]), False)
check("CMP", "BOOL true vs true", M([[True]], [[True]]), True)
check("CMP", "NULL vs 0", M([[None]], [[0]]), False)
check("CMP", "NULL vs ''", M([[None]], [[""]]), False)
check("CMP", "NULL vs NULL", M([[None]], [[None]]), True)
check("CMP", "STR exact: 'ab' vs 'ab '", M([["ab"]], [["ab "]]), False)
check("CMP", "STR '1.0 ' vs '1.0'", M([["1.0 "]], [["1.0"]]), False)
check("CMP", "STR '1e5' vs INT 100000", M([["1e5"]], [[100000]]), False)
check("CMP", "unicode not normalized: 'é' vs 'e\\u0301'", M([["é"]], [["e\u0301"]]), False)
check("CMP", "duplicate counts differ", M([[1], [1], [2]], [[1], [2], [2]]), False)
check("CMP", "empty vs empty", M([], []), True)
check("CMP", "tolerance + reorder", M([["1.0000001", "x"], ["5", "y"]], [["5", "y"], ["1.0000002", "x"]]), True)
check("CMP", "tolerance leftovers matched by value (not text order)",
      M([["9.0000001"], ["10"], ["100"]], [["100"], ["10.0000001"], ["9"]]), True)
check("CMP", "row width differs", M([[1, 2]], [[1]]), False)
check("CMP", "typed STR '1.0' vs '1.00' is a defect", M([["1.0"]], [["1.00"]], ["STR"]), False)
check("CMP", "typed DATE text exact", M([["2024-01-01"]], [["2024-01-01"]], ["DATE"]), True)
check("CMP", "untyped (unknown) '1.0' vs '1.00' compares as numbers", M([["1.0"]], [["1.00"]], [None]), True)
check("CMP", "ncols differ -> DEFECT", C.compare(res([[1]], 1), res([[1, 2]], 2), False, [None])[0], "DEFECT")
check("CMP", "unordered output, reordered rows -> OK", C.compare(res([[1], [2]]), res([[2], [1]]), False, [None])[0], "OK")
check("CMP", "ordered output, reordered rows, no keys -> DEFECT",
      C.compare(res([[1], [2]]), res([[2], [1]]), True, [None])[0], "DEFECT")

# ---------------- ORDER ----------------
O = lambda t: C.output_ordered(P(t))
check("ORDER", "no SORT -> unordered", O("LOAD a, t.x\nGT m, a, 1\nIDX i, m\nGATHER b, a, i\nOUT b\n"), False)
check("ORDER", "SORT then GATHER -> ordered", O("LOAD a, t.x\nSORT s, a ASC NF\nGATHER b, a, s\nOUT b\n"), True)
check("ORDER", "lower/mixed case", O("load a, t.x\nsOrT s, a asc nf\ngather b, a, s\nout b\n"), True)
check("ORDER", "SORT result never reaches OUT", O("LOAD a, t.x\nSORT s, a ASC NF\nGATHER b, a, s\nOUT a\n"), False)
check("ORDER", "sorted register overwritten by LOAD", O("LOAD a, t.x\nSORT s, a ASC NF\nGATHER b, a, s\nLOAD b, t.x\nOUT b\n"), False)
check("ORDER", "sort, then filter keeps order",
      O("LOAD a, t.x\nSORT s, a ASC NF\nGATHER b, a, s\nGT m, b, 1\nIDX i, m\nGATHER c, b, i\nOUT c\n"), True)
check("ORDER", "sort, then right side of a join keeps left order",
      O("LOAD a, t.x\nLOAD k, u.k\nLOAD n, u.n\nSORT s, a ASC NF\nGATHER b, a, s\nHJOIN l, r, b, k\nGATHER x, n, r\nOUT x\n"), True)
check("ORDER", "sort the RIGHT join key only -> unordered",
      O("LOAD a, t.x\nLOAD k, u.k\nSORT s, k ASC NF\nGATHER kk, k, s\nHJOIN l, r, a, kk\nGATHER x, a, l\nOUT x\n"), False)
check("ORDER", "sort then GROUP: groups numbered in sorted order",
      O("LOAD a, t.x\nSORT s, a ASC NF\nGATHER b, a, s\nGROUP g, b\nGCOUNT c, g\nOUT c\n"), True)
check("ORDER", "sorted rows aggregated by GALL -> one row, unordered",
      O("LOAD a, t.x\nSORT s, a ASC NF\nGATHER b, a, s\nGALL g, b\nGSUM c, g, b\nOUT c\n"), False)
check("ORDER", "TOPK -> ordered", O("LOAD a, t.x\nTOPK s, 3, a DESC NL\nGATHER b, a, s\nOUT b\n"), True)
check("ORDER", "element-wise op on sorted column", O("LOAD a, t.x\nSORT s, a ASC NF\nGATHER b, a, s\nADD c, b, 1\nOUT c\n"), True)
check("ORDER", "';' inside a string literal", O("LOAD a, t.s\nSORT s, a ASC NF\nGATHER b, a, s\nCAT c, b, ';x'\nOUT c\n"), True)
check("ORDER", "comment mentioning SORT", O("LOAD a, t.x\nOUT a ; SORT s, a ASC NF\n"), False)
check("ORDER", "register names case-sensitive (s vs S)", O("LOAD a, t.x\nSORT S, a ASC NF\nIOTA s, a\nGATHER b, a, s\nOUT b\n"), False)
for f in sorted(x for x in os.listdir(os.path.join(vm.BUNDLE, "examples", "programs")) if x.endswith(".mini")):
    want = f != "q0004.mini"     # q0004 ends in a GALL total: one row, so its order is moot
    check("ORDER", f"example {f} is order-specified: {want}",
          C.output_ordered(P(open(os.path.join(vm.BUNDLE, "examples", "programs", f)).read())), want)

# ---------------- TYPES ----------------
T = lambda t, s: C.out_types(P(t), s)
SCH = {"t": {"columns": [{"name": "x", "type": "INT"}, {"name": "s", "type": "STR"}, {"name": "n", "type": "NUM"},
                         {"name": "d", "type": "DATE"}]}}
check("TYPES", "LOAD types", T("LOAD a, t.x\nLOAD b, T.S\nLOAD c, t.n\nLOAD d, t.d\nOUT a, b, c, d\n", SCH), ["INT", "STR", "NUM", "DATE"])
check("TYPES", "comparison is BOOL, GCOUNT INT", T("LOAD a, t.x\nGT m, a, 1\nGALL g, a\nGCOUNT c, g\nOUT m\n", SCH), ["BOOL"])
check("TYPES", "ADD INT+NUM -> NUM, DIV -> NUM", T("LOAD a, t.x\nADD b, a, 1.5\nDIV c, a, a\nOUT b, c\n", SCH), ["NUM", "NUM"])
check("TYPES", "string ops STR, GATHER keeps type", T("LOAD a, t.s\nUPPER u, a\nIOTA i, u\nGATHER v, u, i\nOUT v\n", SCH), ["STR"])

# ---------------- CANON ----------------
K = lambda t: C.canon_text(P(t))
base = "LOAD a, t.x\nSORT s, a ASC NF\nGATHER b, a, s\nOUT b\n"
check("CANON", "rename + case + comments + whitespace -> same", K(base) == K("; c\nload  q1 ,t.x\nsort Z, q1 asc nf ; x\n\ngather b2, q1, Z\nout b2\n"), True)
check("CANON", "different literal case -> different", K("LOAD a, t.s\nEQ m, a, 'x'\nOUT m\n") == K("LOAD a, t.s\nEQ m, a, 'X'\nOUT m\n"), False)
check("CANON", "swapped operands -> different", K("LOAD a, t.x\nLOAD b, t.y\nSUB c, a, b\nOUT c\n") == K("LOAD a, t.x\nLOAD b, t.y\nSUB c, b, a\nOUT c\n"), False)
check("CANON", "non-bijective rename -> different", K("LOAD a, t.x\nLOAD b, t.y\nOUT a, b\n") == K("LOAD a, t.x\nLOAD a, t.y\nOUT a, a\n"), False)


# ---------------- TIE (on bin/minivm) ----------------
def run(text, data):
    p, d = os.path.join(TMP, "p.mini"), os.path.join(TMP, "d.json")
    with open(p, "w", newline="") as f:
        f.write(text)
    with open(d, "w") as f:
        json.dump(data, f)
    r, e = vm.run(p, d)
    return r if r is not None else "error"


TD = {"t": {"columns": [{"name": "k", "type": "INT"}, {"name": "v", "type": "STR"}],
            "rows": [[2, "a"], [1, "b"], [2, "c"], [1, "d"], [3, "e"]]}}
SRT = "LOAD k, t.k\nLOAD v, t.v\nSORT s, k ASC NF\nGATHER a, k, s\nGATHER b, v, s\nOUT a, b\n"
TIE_REV = "LOAD k, t.k\nLOAD v, t.v\nIOTA p, k\nSORT s, k ASC NF, p DESC NF\nGATHER a, k, s\nGATHER b, v, s\nOUT a, b\n"
FLIP = "LOAD k, t.k\nLOAD v, t.v\nSORT s, k DESC NF\nGATHER a, k, s\nGATHER b, v, s\nOUT a, b\n"


def cmp_prog(orig, opt, data):
    pr = P(orig)
    a, b = run(orig, data), run(opt, data)
    ins = C.instrument(pr)
    keyed = run(ins, data)["rows"] if ins else None
    full_t = C.instrument(pr, no_cut=True)
    full = run(full_t, data)["rows"] if full_t else None
    cut = any(op in ("TOPK", "SLICE") for op, _ in pr)
    return C.compare(a, b, C.output_ordered(pr), C.out_types(pr, data), keyed, cut, full)[0]


check("TIE", "instrument() traces the sort key", C.instrument(P(SRT)) is not None, True)
check("TIE", "tied rows reversed -> OK", cmp_prog(SRT, TIE_REV, TD), "OK")
check("TIE", "sort direction flipped -> DEFECT", cmp_prog(SRT, FLIP, TD), "DEFECT")
TWO = "LOAD k, t.k\nLOAD v, t.v\nSORT s, v DESC NF\nGATHER a, k, s\nGATHER b, v, s\nSORT u, a ASC NF\nGATHER c, a, u\nGATHER d, b, u\nOUT c, d\n"
TWO_REV = TWO.replace("SORT u, a ASC NF", "IOTA p, a\nSORT u, a ASC NF, p DESC NF")
check("TIE", "ties of a later sort are ordered by an earlier sort -> reversing is DEFECT", cmp_prog(TWO, TWO_REV, TD), "DEFECT")
TOP = "LOAD k, t.k\nLOAD v, t.v\nTOPK s, 1, k ASC NF\nGATHER a, k, s\nGATHER b, v, s\nOUT a, b\n"
TOP_TIE = "LOAD k, t.k\nLOAD v, t.v\nIOTA p, k\nTOPK s, 1, k ASC NF, p DESC NF\nGATHER a, k, s\nGATHER b, v, s\nOUT a, b\n"
TOP_BAD = "LOAD k, t.k\nLOAD v, t.v\nTOPK s, 1, v DESC NF\nGATHER a, k, s\nGATHER b, v, s\nOUT a, b\n"
check("TIE", "TOPK 1 picks another tied row -> WARN", cmp_prog(TOP, TOP_TIE, TD), "WARN")
check("TIE", "TOPK 1 picks a non-tied row -> DEFECT", cmp_prog(TOP, TOP_BAD, TD), "DEFECT")
TD2 = {"t": {"columns": [{"name": "k", "type": "INT"}, {"name": "v", "type": "STR"}],
             "rows": [[1, "a"], [1, "b"], [2, "c"], [2, "z"]]}}
TOP2 = TOP.replace("TOPK s, 1,", "TOPK s, 3,")
check("TIE", "TOPK 3 with ties: only the cut-off block may differ (same program -> OK)", cmp_prog(TOP2, TOP2, TD2), "OK")
SL = "LOAD k, t.k\nLOAD v, t.v\nSORT s, k ASC NF\nGATHER a, k, s\nGATHER b, v, s\nIOTA i, a\nSLICE i, i, 3\nGATHER c, a, i\nGATHER d, b, i\nOUT c, d\n"
SL_TIE = SL.replace("SORT s, k ASC NF", "IOTA p, k\nSORT s, k ASC NF, p DESC NF")
SL_BAD = SL.replace("SLICE i, i, 3", "SLICE i, i, 2")
check("TIE", "SORT+SLICE 3 picks another tied row -> WARN", cmp_prog(SL, SL_TIE, TD2), "WARN")
check("TIE", "SLICE 3 -> 2 -> DEFECT", cmp_prog(SL, SL_BAD, TD2), "DEFECT")
check("TIE", "tie_blocks NULL == NULL, 1 == 1.0", C.tie_blocks([[None], [None], [1], ["1.0"], [2]]), [[0, 1], [2, 3], [4]])

# ---------------- VM ----------------
E = {"e": {"columns": [{"name": "v", "type": "INT"}]}}
R = lambda t, d: (lambda r: r if r == "error" else r["rows"])(run(t, d))
check("VM", "empty table: GROUP -> 0 rows", R("LOAD v, e.v\nGROUP g, v\nGCOUNT c, g\nOUT c\n", E), [])
check("VM", "empty table: GALL -> 1 row [0, NULL]", R("LOAD v, e.v\nGALL g, v\nGCOUNT c, g\nGSUM s, g, v\nOUT c, s\n", E), [[0, None]])
check("VM", "empty table: DIV by 0 never fires", R("LOAD v, e.v\nUPPER u, v\nDIV z, v, 0\nOUT u\n", E), [])
check("VM", "CRLF accepted", R("LOAD v, e.v\r\nOUT v\r\n", E), [])
check("VM", "OUT with no operands is an error", R("LOAD v, e.v\nOUT\n", E), "error")
TS = {"t": {"columns": [{"name": "s", "type": "STR"}], "rows": [["a"]]}}
check("VM", "';' inside a string literal is data", R("LOAD s, t.s\nCAT c, s, ';x'\nOUT c\n", TS), [["a;x"]])
check("VM", "opcode/keyword case-insensitive", R("load s, t.s\nsOrT p, s aSc nF\nOUT p\n", TS), [[0]])
check("VM", "SLICE with a huge n keeps everything (uncut() relies on it)", R("LOAD s, t.s\nSLICE c, s, 4000000000\nOUT c\n", TS), [["a"]])
check("VM", "evaluator uses the platform binary", vm.VM != vm.WRAPPER, True)
check("VM", "deterministic output", run(SRT, TD) == run(SRT, TD), True)

bad = 0
verbose = "-v" in sys.argv
for group, name, ok, got, want in results:
    bad += not ok
    if verbose or not ok:
        print(f"{'PASS' if ok else 'FAIL'}  {group:<5} {name}" + ("" if ok else f"   (got {got!r}, want {want!r})"))
print(f"{len(results) - bad}/{len(results)} passed")
sys.exit(1 if bad else 0)
