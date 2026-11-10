#!/usr/bin/env python3
"""Fake optimizers for testing the evaluator (the tester's tests).

  fake_opt.py MODE program.mini schema.json      prints the transformed program

Each MODE is a generic text-level transform that works on any MiniVM program.
HONEST modes keep results identical under the one-pager rules (and must not be
flagged); BUGGY modes change results on some valid data (and must be caught).
See MODES at the bottom for the list and what each one does.
"""
import re, sys

KEYWORDS = {"NULL", "TRUE", "FALSE", "ASC", "DESC", "NF", "NL", "NULLEQ"}
TWO_DEST = {"HJOIN", "NLJOIN"}


# ---------------- tiny parser / printer ----------------
def split_operands(s):
    out, cur, q = [], "", False
    for ch in s:
        if ch == "'":
            q = not q
        if ch == "," and not q:
            out.append(cur.strip()); cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def strip_comment(line):
    q = False
    for i, ch in enumerate(line):
        if ch == "'":
            q = not q
        elif ch == ";" and not q:
            return line[:i]
    return line


def parse(path):
    prog = []
    for line in open(path):
        code = strip_comment(line).strip()
        if not code:
            continue
        parts = code.split(None, 1)
        prog.append([parts[0].upper(), split_operands(parts[1]) if len(parts) > 1 else []])
    return prog


def emit(prog):
    return "\n".join(f"{op} {', '.join(ops)}" for op, ops in prog) + "\n"


def is_reg(tok):
    return re.fullmatch(r"[A-Za-z_]\w*", tok) is not None and tok.upper() not in KEYWORDS


def regs_in(tok):
    first = tok.split()[0] if tok.split() else tok   # sort key "r ASC NF" -> r
    return [first] if is_reg(first) else []


def dests(op, ops):
    if op == "OUT":
        return []
    return ops[:2] if op in TWO_DEST else ops[:1]


def sources(op, ops):
    srcs = ops if op == "OUT" else ops[2:] if op in TWO_DEST else ops[1:]
    return [r for t in srcs for r in regs_in(t)]


# ---------------- transforms ----------------
def dce(prog):
    live, keep = set(), []
    for op, ops in reversed(prog):
        d = dests(op, ops)
        if op == "OUT" or any(x in live for x in d):
            for x in d:
                live.discard(x)
            live.update(sources(op, ops))
            keep.append([op, ops])
    return list(reversed(keep))


def rename(prog):
    m = {}
    def r(tok):
        def sub(mt):
            w = mt.group(0)
            if not is_reg(w):
                return w
            return m.setdefault(w, f"v{len(m)}")
        if tok.startswith("'") or "." in tok or tok.startswith("#"):
            return tok
        return re.sub(r"[A-Za-z_]\w*", sub, tok)
    return [[op, [r(t) for t in ops]] for op, ops in prog]


def fmt(prog):
    text = "; reformatted by fake optimizer\n"
    for op, ops in prog:
        text += f"\t{op.lower()}\t" + " ,  ".join(ops) + "   ; same instruction\n\n"
    return text


def swap_joins(prog):
    return [[{"HJOIN": "NLJOIN", "NLJOIN": "HJOIN"}.get(op, op), ops] for op, ops in prog]


def after_gsum(prog, tmpl):
    out = []
    for op, ops in prog:
        out.append([op, ops])
        if op == "GSUM":
            out.append(tmpl(ops[0]))
    return out


def first(prog, pred, fn):
    for i, (op, ops) in enumerate(prog):
        if pred(op, ops):
            prog[i] = fn(op, ops)
            break
    return prog


def each(prog, pred, fn):
    return [fn(op, ops) if pred(op, ops) else [op, ops] for op, ops in prog]


def is_lit(t):
    return re.fullmatch(r"-?\d+(\.\d+)?", t) is not None


def flip_strict(op, ops):
    return [{"GT": "GE", "GE": "GT", "LT": "LE", "LE": "LT"}[op], ops]


def flip_dir(op, ops):
    k = 2 if op == "TOPK" else 1
    parts = ops[k].split()
    parts[1] = "DESC" if parts[1].upper() == "ASC" else "ASC"
    return [op, ops[:k] + [" ".join(parts)] + ops[k + 1:]]


def reverse_rows(prog):
    op, outs = prog[-1]
    body = prog[:-1] + [["IOTA", ["_rp", outs[0]]], ["SORT", ["_rs", "_rp DESC NF"]]]
    new = []
    for i, o in enumerate(outs):
        body.append(["GATHER", [f"_ro{i}", o, "_rs"]]); new.append(f"_ro{i}")
    return body + [["OUT", new]]


def dead_div0(prog):
    for i, (op, ops) in enumerate(prog):
        if op == "LOAD":
            return prog[:i + 1] + [["DIV", ["_z", ops[0], "0"]]] + prog[i + 1:]
    return prog


def hand(path):
    import os
    q = os.path.basename(path)[:-5]
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "optimizer_agent", q + ".opt.mini")
    return open(p).read() if os.path.exists(p) else open(path).read()


MODES = {
    # ----- HONEST: must NOT be flagged -----
    "h_identity":    ("honest", "prints the input unchanged", lambda p: emit(p)),
    "h_dce":         ("honest", "removes instructions whose results are never used", lambda p: emit(dce(p))),
    "h_rename":      ("honest", "renames every register to v0, v1, ...", lambda p: emit(rename(p))),
    "h_format":      ("honest", "lower-case opcodes, tabs, extra spaces, comments, blank lines", lambda p: fmt(p)),
    "h_join_swap":   ("honest", "HJOIN <-> NLJOIN (same results by spec)", lambda p: emit(swap_joins(p))),
    "h_tiny_drift":  ("honest", "multiplies each GSUM by 1.0000000001 (1e-10 relative, within 1e-6)",
                      lambda p: emit(after_gsum(p, lambda d: ["MUL", [d, d, "1.0000000001"]]))),
    "h_scale":       ("honest", "adds 0.000 to each GSUM (INT 3 prints as NUM '3.000'; same number)",
                      lambda p: emit(after_gsum(p, lambda d: ["ADD", [d, d, "0.000"]]))),
    "h_hand":        ("honest", "the hand-optimized qNNNN.opt.mini programs", None),
    # ----- BUGGY: must be caught -----
    "b_strict":      ("buggy", "first GT/GE/LT/LE against a literal flips strictness (boundary bug)",
                      lambda p: emit(first(p, lambda o, a: o in ("GT", "GE", "LT", "LE") and any(is_lit(x) for x in a[1:]), flip_strict))),
    "b_no_nullife":  ("buggy", "NULLIFE becomes a no-op ('' no longer treated as NULL)",
                      lambda p: emit(each(p, lambda o, a: o == "NULLIFE", lambda o, a: ["NVL", [a[0], a[1], a[1]]]))),
    "b_no_upper":    ("buggy", "UPPER becomes a no-op (case-sensitive matching)",
                      lambda p: emit(each(p, lambda o, a: o == "UPPER", lambda o, a: ["NVL", [a[0], a[1], a[1]]]))),
    "b_trim":        ("buggy", "RTRIM becomes TRIM (leading spaces stripped too)",
                      lambda p: emit(each(p, lambda o, a: o == "RTRIM", lambda o, a: ["TRIM", a]))),
    "b_nulleq":      ("buggy", "adds NULLEQ to every join (NULL keys start matching)",
                      lambda p: emit(each(p, lambda o, a: o in TWO_DEST and len(a) == 4, lambda o, a: [o, a + ["NULLEQ"]]))),
    "b_left_short":  ("buggy", "LEFT n becomes LEFT n-1 (off by one)",
                      lambda p: emit(each(p, lambda o, a: o == "LEFT" and int(a[2]) > 0, lambda o, a: [o, a[:2] + [str(int(a[2]) - 1)]]))),
    "b_sort_flip":   ("buggy", "first SORT/TOPK key flips ASC <-> DESC",
                      lambda p: emit(first(p, lambda o, a: o in ("SORT", "TOPK"), flip_dir))),
    "b_no_tiebreak": ("buggy", "drops the last key of every multi-key SORT/TOPK",
                      lambda p: emit(each(p, lambda o, a: o in ("SORT", "TOPK") and len(a) - (2 if o == "TOPK" else 1) >= 2,
                                          lambda o, a: [o, a[:-1]]))),
    "b_reverse":     ("buggy", "reverses the output rows (order is specified: every example SORTs)", lambda p: emit(reverse_rows(p))),
    "b_drift":       ("buggy", "multiplies each GSUM by 1.00001 (1e-5 relative, beyond 1e-6)",
                      lambda p: emit(after_gsum(p, lambda d: ["MUL", [d, d, "1.00001"]]))),
    "b_dead_div0":   ("buggy", "adds an unused DIV by zero (errors where the original didn't)", lambda p: emit(dead_div0(p))),
}


def main():
    mode, prog_path = sys.argv[1], sys.argv[2]
    _, _, fn = MODES[mode]
    sys.stdout.write(hand(prog_path) if mode == "h_hand" else fn(parse(prog_path)))


if __name__ == "__main__":
    main()
