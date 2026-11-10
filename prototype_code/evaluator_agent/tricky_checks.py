#!/usr/bin/env python3
"""Tricky-rule checks for eval-proto.py (run: python3 tricky_checks.py).

Each check states the rule, the expected behaviour, and what we got. Three groups:
  CMP    comparator rules (types print as text, tolerance, NULL, BOOL vs INT, ...)
  ORDER  does the program specify output order? (case-insensitive opcodes, overwrites,
         order through filters/joins/groups, sorts whose result is never output, ...)
  VM     facts about bin/minivm the evaluator relies on (empty tables, literal parsing,
         platform binary == wrapper, determinism)
Exit 1 if any check fails.
"""
import importlib.util, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ev", os.path.join(HERE, "eval-proto.py"))
ev = importlib.util.module_from_spec(spec); spec.loader.exec_module(ev)
results = []


def check(group, name, got, want, note=""):
    results.append((group, name, got == want, got, want, note))


# ---------------- CMP ----------------
M = ev.same_multiset
check("CMP", "rows reordered, multiset equal", M([[1, "a"], [2, "b"]], [[2, "b"], [1, "a"]]), True)
check("CMP", "NUM scale '2.0' vs '2.00'", M([["2.0"]], [["2.00"]]), True)
check("CMP", "INT 2 vs NUM '2.0'", M([[2]], [["2.0"]]), True)
check("CMP", "negative zero '-0.0' vs '0'", M([["-0.0"]], [["0"]]), True)
check("CMP", "big INT as string vs JSON int", M([["18446744073709551614"]], [[18446744073709551614]]), True)
check("CMP", "within 1e-6 relative", M([["1000000.0"]], [["1000000.9"]]), True)
check("CMP", "beyond 1e-6 relative", M([["1000000.0"]], [["1000002"]]), False)
check("CMP", "INT off by one at 1e7 (within 1e-6: spec allows)", M([[10000000]], [[10000001]]), True,
      "one-pager tolerance applies to every number, so this is NOT a defect")
check("CMP", "0 vs 1e-7 (pure relative tolerance)", M([["0"]], [["0.0000001"]]), False)
check("CMP", "BOOL true vs INT 1", M([[True]], [[1]]), False, "JSON true must not equal 1")
check("CMP", "BOOL false vs INT 0", M([[False]], [[0]]), False)
check("CMP", "BOOL true vs STR 'true'", M([[True]], [["true"]]), False)
check("CMP", "NULL vs 0", M([[None]], [[0]]), False)
check("CMP", "NULL vs ''", M([[None]], [[""]]), False)
check("CMP", "NULL vs NULL", M([[None]], [[None]]), True)
check("CMP", "STR exact: 'ab' vs 'ab '", M([["ab"]], [["ab "]]), False)
check("CMP", "STR numeric-looking with space '1.0 ' vs '1.0'", M([["1.0 "]], [["1.0"]]), False,
      "a TRIM bug on numeric-looking strings must not hide behind number parsing")
check("CMP", "STR '1e5' vs INT 100000", M([["1e5"]], [[100000]]), False, "minivm never prints numbers as 1e5")
check("CMP", "STR 'NaN' vs 'NaN'", M([["NaN"]], [["NaN"]]), True)
check("CMP", "unicode not normalized: 'é' vs 'e\\u0301'", M([["é"]], [["e\u0301"]]), False)
check("CMP", "duplicate counts differ", M([[1], [1], [2]], [[1], [2], [2]]), False)
check("CMP", "empty vs empty", M([], []), True)
check("CMP", "tolerance + reorder", M([["1.0000001", "x"], ["5", "y"]], [["5", "y"], ["1.0000002", "x"]]), True)
check("CMP", "row width differs", M([[1, 2]], [[1]]), False)
# known ambiguity: STR '1.0' and NUM '1.00' print alike; without column types they compare as numbers
check("CMP", "AMBIGUOUS: STR '1.0' vs STR '1.00' (compares as numbers)", M([["1.0"]], [["1.00"]]), True,
      "output JSON has no types; documented limitation")

# ---------------- ORDER ----------------
def ordered(src):
    with tempfile.NamedTemporaryFile("w", suffix=".mini", delete=False) as f:
        f.write(src)
    try:
        return ev.output_ordered(f.name)
    finally:
        os.remove(f.name)


check("ORDER", "no SORT -> unordered", ordered("LOAD a, t.x\nGT m, a, 1\nIDX i, m\nGATHER b, a, i\nOUT b\n"), False)
check("ORDER", "SORT then GATHER -> ordered", ordered("LOAD a, t.x\nSORT s, a ASC NF\nGATHER b, a, s\nOUT b\n"), True)
check("ORDER", "lower/mixed case: sort/SoRt + asc nf", ordered("load a, t.x\nsOrT s, a asc nf\ngather b, a, s\nout b\n"), True)
check("ORDER", "SORT result never reaches OUT", ordered("LOAD a, t.x\nSORT s, a ASC NF\nGATHER b, a, s\nOUT a\n"), False)
check("ORDER", "sorted register overwritten by unsorted LOAD", ordered("LOAD a, t.x\nSORT s, a ASC NF\nGATHER b, a, s\nLOAD b, t.x\nOUT b\n"), False)
check("ORDER", "sort, then filter (IDX on sorted) keeps order",
      ordered("LOAD a, t.x\nSORT s, a ASC NF\nGATHER b, a, s\nGT m, b, 1\nIDX i, m\nGATHER c, b, i\nOUT c\n"), True)
check("ORDER", "sort, then right side of a join keeps left order",
      ordered("LOAD a, t.x\nLOAD k, u.k\nLOAD n, u.n\nSORT s, a ASC NF\nGATHER b, a, s\nHJOIN l, r, b, k\nGATHER x, n, r\nOUT x\n"), True)
check("ORDER", "sort the RIGHT join key only -> output not ordered",
      ordered("LOAD a, t.x\nLOAD k, u.k\nSORT s, k ASC NF\nGATHER kk, k, s\nHJOIN l, r, a, kk\nGATHER x, a, l\nOUT x\n"), False)
check("ORDER", "sort then GROUP: groups numbered in sorted order",
      ordered("LOAD a, t.x\nSORT s, a ASC NF\nGATHER b, a, s\nGROUP g, b\nGCOUNT c, g\nOUT c\n"), True)
check("ORDER", "TOPK -> ordered", ordered("LOAD a, t.x\nTOPK s, 3, a DESC NL\nGATHER b, a, s\nOUT b\n"), True)
check("ORDER", "element-wise op on sorted column", ordered("LOAD a, t.x\nSORT s, a ASC NF\nGATHER b, a, s\nADD c, b, 1\nOUT c\n"), True)
check("ORDER", "';' inside a string literal is not a comment",
      ordered("LOAD a, t.s\nSORT s, a ASC NF\nGATHER b, a, s\nCAT c, b, ';x'\nOUT c\n"), True)
check("ORDER", "comment that mentions SORT does not count", ordered("LOAD a, t.x\nOUT a ; SORT s, a ASC NF\n"), False)
check("ORDER", "register names are case-sensitive (s vs S)",
      ordered("LOAD a, t.x\nSORT S, a ASC NF\nIOTA s, a\nGATHER b, a, s\nOUT b\n"), False)
progs = os.path.join(ev.ROOT, "examples", "programs")
for f in sorted(os.listdir(progs)):
    check("ORDER", f"example {f} ends in an order-specified output", ev.output_ordered(os.path.join(progs, f)), True)

# ---------------- VM ----------------
def vm_run(src, data, binary=ev.VM):
    with tempfile.TemporaryDirectory() as t:
        p, d = os.path.join(t, "p.mini"), os.path.join(t, "d.json")
        open(p, "w", newline="").write(src); json.dump(data, open(d, "w"))
        r = subprocess.run([binary, p, d], capture_output=True, text=True)
        return json.loads(r.stdout)["rows"] if r.returncode == 0 else "error"


E = {"e": {"columns": [{"name": "v", "type": "INT"}]}}
check("VM", "empty table: GROUP -> 0 rows", vm_run("LOAD v, e.v\nGROUP g, v\nGCOUNT c, g\nOUT c\n", E), [])
check("VM", "empty table: GALL -> 1 row [0, NULL]", vm_run("LOAD v, e.v\nGALL g, v\nGCOUNT c, g\nGSUM s, g, v\nOUT c, s\n", E), [[0, None]])
check("VM", "empty table: DIV by 0 / type error never fire", vm_run("LOAD v, e.v\nUPPER u, v\nDIV z, v, 0\nOUT u\n", E), [])
check("VM", "CRLF line endings accepted", vm_run("LOAD v, e.v\r\nOUT v\r\n", E), [])
check("VM", "OUT with no operands is an error", vm_run("LOAD v, e.v\nOUT\n", E), "error")
T = {"t": {"columns": [{"name": "s", "type": "STR"}], "rows": [["a"]]}}
check("VM", "';' inside a string literal is data", vm_run("LOAD s, t.s\nCAT c, s, ';x'\nOUT c\n", T), [["a;x"]])
check("VM", "opcode/keyword case-insensitive", vm_run("load s, t.s\nsOrT p, s aSc nF\nOUT p\n", T), [[0]])
native = ev.native_vm() if hasattr(ev, "native_vm") else None
check("VM", "evaluator uses the platform binary (about 4.6x faster than the wrapper)", bool(native and native != ev.VM_WRAPPER), True)
if native:
    data = os.path.join(ev.ROOT, "examples", "data.json")
    same = all(subprocess.run([b, os.path.join(progs, f), data], capture_output=True, text=True).stdout
               == subprocess.run([ev.VM_WRAPPER, os.path.join(progs, f), data], capture_output=True, text=True).stdout
               for f in sorted(os.listdir(progs)) for b in [native])
    check("VM", "platform binary output == bin/minivm output (all examples)", same, True)

# ---------------- report ----------------
bad = 0
for group, name, ok, got, want, note in results:
    bad += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {group:<5} {name}" + ("" if ok else f"   (got {got!r}, want {want!r})")
          + (f"   [{note}]" if note and not ok else ""))
print(f"\n{len(results) - bad}/{len(results)} passed")
sys.exit(1 if bad else 0)
