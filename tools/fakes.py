#!/usr/bin/env python3
"""Fake optimizers for testing ./evaluate (the tester's tests).

  fakes.py MODE program.mini schema.json      prints the transformed program
  fakes.py --list                             prints MODE kind description

Every MODE is a generic transform that works on any MiniVM program (it may leave
a program unchanged when its pattern is absent). HONEST modes keep results equal
under the one-pager rules and the evaluator's documented defaults (BUILD_PLAN §7),
so ./evaluate must NOT flag them; BUGGY modes change results on some valid data,
so ./evaluate MUST flag them. Written from the MiniVM docs only: no code is shared
with evaluator/ or optimizer/.
"""
import datetime
import hashlib
import json
import os
import re
import sys
import time

KEYWORDS = {"NULL", "TRUE", "FALSE", "ASC", "DESC", "NF", "NL", "NULLEQ"}
TWO_DEST = {"HJOIN", "NLJOIN"}
GROUP_OPS = {"GROUP", "GALL", "GID", "GFIRST", "GCOUNT", "GCOUNTV", "GSUM", "GMIN", "GMAX"}
ELEMENTWISE = {"ADD", "SUB", "MUL", "DIV", "IDIV", "MOD", "NEG", "WRAP", "TRUNC", "EQ", "NE", "LT", "LE",
               "GT", "GE", "IS", "AND", "OR", "NOT", "ISNULL", "NVL", "IF", "NULLIF", "NULLIFE", "UPPER",
               "RTRIM", "TRIM", "LEFT", "SUBSTR", "LEN", "CAT", "YEAR", "MONTH", "DAY", "DOW", "DATEADD",
               "DATEDIFF"}
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


# ---------------------------------------------------------------- parse / print
def split_operands(s):
    out, cur, q = [], "", False
    for ch in s:
        if ch == "'":
            q = not q
        if ch == "," and not q:
            out.append(cur.strip())
            cur = ""
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


def parse(text):
    prog = []
    for line in text.splitlines():
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


def head(tok):
    """register of an operand (sort key 'r ASC NF' -> r), or None."""
    t = tok.split()[0] if tok.split() else tok
    return t if is_reg(t) else None


def dests(op, ops):
    if op == "OUT":
        return []
    return ops[:2] if op in TWO_DEST else ops[:1]


def src_toks(op, ops):
    return ops if op == "OUT" else ops[2:] if op in TWO_DEST else [] if op == "LOAD" else ops[1:]


def sources(op, ops):
    return [r for r in (head(t) for t in src_toks(op, ops)) if r]


def is_num_lit(t):
    return re.fullmatch(r"-?\d+(\.\d+)?", t.strip()) is not None


def is_int_lit(t):
    return re.fullmatch(r"-?\d+", t.strip()) is not None


def hsel(path, mod, always=()):
    """deterministic per-program selection (by basename) for 'only some programs' bugs."""
    b = os.path.basename(path)
    return any(a in b for a in always) or int(hashlib.md5(b.encode()).hexdigest(), 16) % mod == 0


# ---------------------------------------------------------------- schema helpers
class Schema:
    def __init__(self, s):
        self.s = {t.lower(): v for t, v in s.items()}

    def table(self, t):
        return self.s.get(t.lower(), {})

    def col(self, tc):
        t, c = tc.split(".")
        for x in self.table(t).get("columns", []):
            if x["name"].lower() == c.lower():
                return x
        return None

    def not_null(self, tc):
        t, c = tc.split(".")
        sp = self.table(t)
        return c.lower() in {x.lower() for x in sp.get("key", []) + sp.get("not_null", [])}

    def stats(self, tc):
        t, c = tc.split(".")
        for k, v in self.table(t).get("stats", {}).get("columns", {}).items():
            if k.lower() == c.lower():
                return v
        return {}


def load_map(prog):
    """per instruction index: {reg: 'table.col'} for registers that still hold a raw LOAD there."""
    cur, out = {}, []
    for op, ops in prog:
        out.append(dict(cur))
        for d in dests(op, ops):
            cur.pop(d, None)
        if op == "LOAD":
            cur[ops[0]] = ops[1]
    return out


def types(prog, sch):
    """crude static types (only what the fakes need): reg -> INT/NUM/STR/DATE/BOOL/None."""
    ty = {}
    for op, ops in prog:
        if op == "OUT" or not ops:
            continue
        d = ops[0]
        s = [head(t) for t in ops[1:]]
        t = None
        if op == "LOAD":
            c = sch.col(ops[1])
            t = c["type"] if c else None
        elif op in ("NULLIFE", "RTRIM", "TRIM", "UPPER", "LEFT", "SUBSTR", "CAT"):
            t = "STR"
        elif op in ("GATHER", "SLICE", "NVL", "NULLIF") and s and s[0]:
            t = ty.get(s[0])
        elif op in ("EQ", "NE", "LT", "LE", "GT", "GE", "IS", "AND", "OR", "NOT", "ISNULL"):
            t = "BOOL"
        elif op in ("IOTA", "IDX", "SORT", "TOPK", "GCOUNT", "GCOUNTV", "GFIRST", "GID", "LEN", "YEAR",
                    "MONTH", "DAY", "DOW", "DATEDIFF", "IDIV", "MOD", "TRUNC", "WRAP"):
            t = "INT"
        elif op == "DATEADD":
            t = "DATE"
        if op in TWO_DEST:
            ty[ops[0]] = ty[ops[1]] = "INT"
            continue
        ty[d] = t
    return ty


# ---------------------------------------------------------------- generic transforms
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


def ssa(prog, cse_loads=False):
    """rename to single assignment (v0, v1, ...); optionally merge repeated LOADs of a column."""
    cur, n, out, seen = {}, [0], [], {}

    def new():
        n[0] += 1
        return f"v{n[0]}"

    def use(tok):
        r = head(tok)
        if r is None:
            return tok
        rest = tok.split(None, 1)
        return cur.get(r, r) + (" " + rest[1] if len(rest) > 1 else "")

    for op, ops in prog:
        if op == "OUT":
            out.append([op, [use(t) for t in ops]])
            continue
        if op == "LOAD":
            key = ops[1].lower()
            if cse_loads and key in seen:
                cur[ops[0]] = seen[key]
                continue
            v = new()
            seen[key] = v
            cur[ops[0]] = v
            out.append([op, [v, ops[1]]])
            continue
        srcs = [use(t) for t in src_toks(op, ops)]
        if op in TWO_DEST:
            if ops[0] == ops[1]:
                v = new()
                cur[ops[0]] = v
                out.append([op, [v, v] + srcs])
            else:
                a, b = new(), new()
                cur[ops[0]], cur[ops[1]] = a, b
                out.append([op, [a, b] + srcs])
            continue
        v = new()
        out.append([op, [v] + srcs])
        cur[ops[0]] = v
    return out


def hoist_loads(prog):
    p = ssa(prog)
    return [x for x in p if x[0] == "LOAD"] + [x for x in p if x[0] != "LOAD"]


def rename(prog):
    m = {}

    def r(tok):
        parts = tok.split()
        if not parts or tok.startswith("'") or tok.startswith("#") or "." in parts[0]:
            return tok
        if is_reg(parts[0]):
            parts[0] = m.setdefault(parts[0], f"q{len(m)}")
        return " ".join(parts)
    return [[op, [r(t) for t in ops]] for op, ops in prog]


def fmt(prog):
    text = "; reformatted by fake optimizer\r\n\r\n"
    for op, ops in prog:
        text += f"\t{op.lower()}\t" + " ,  ".join(ops) + "   ; same instruction, ';' kept\r\n\r\n"
    return text + "; trailing comment after OUT\n"


def case_mix(prog):
    def kw(tok):
        if tok.startswith("'") or tok.startswith("#"):
            return tok
        parts = tok.split()
        return " ".join(p if (i == 0 and is_reg(p)) else (p.capitalize() if p.upper() in KEYWORDS else p)
                        for i, p in enumerate(parts))
    return "".join(f"{op[0].lower() + op[1:] if k % 2 else op.capitalize()} {', '.join(kw(t) for t in ops)}\n"
                   for k, (op, ops) in enumerate(prog))


def each(prog, pred, fn):
    return [fn(op, ops) if pred(op, ops) else [op, ops] for op, ops in prog]


def first(prog, pred, fn):
    prog = [list(x) for x in prog]
    for i, (op, ops) in enumerate(prog):
        if pred(op, ops):
            prog[i] = fn(op, ops)
            break
    return prog


def after_op(prog, name, tmpl):
    out = []
    for op, ops in prog:
        out.append([op, ops])
        if op == name:
            out += tmpl(ops[0])
    return out


def before_out(prog, fn):
    """fn(out_regs) -> (instructions, new out regs)"""
    body, (op, outs) = prog[:-1], prog[-1]
    ins, new = fn(outs)
    return body + ins + [["OUT", new]]


def flip_strict(op, ops):
    return [{"GT": "GE", "GE": "GT", "LT": "LE", "LE": "LT"}[op], ops]


def flip_dir(op, ops):
    k = 2 if op == "TOPK" else 1
    parts = ops[k].split()
    parts[1] = "DESC" if parts[1].upper() == "ASC" else "ASC"
    return [op, ops[:k] + [" ".join(parts)] + ops[k + 1:]]


def flip_nulls(op, ops):
    k = 2 if op == "TOPK" else 1
    parts = ops[k].split()
    parts[2] = "NL" if parts[2].upper() == "NF" else "NF"
    return [op, ops[:k] + [" ".join(parts)] + ops[k + 1:]]


def reverse_rows(outs):
    ins = [["IOTA", ["_fkp", outs[0]]], ["SORT", ["_fks", "_fkp DESC NF"]]]
    new = []
    for i, o in enumerate(outs):
        ins.append(["GATHER", [f"_fko{i}", o, "_fks"]])
        new.append(f"_fko{i}")
    return ins, new


def dead_div0(prog):
    for i, (op, ops) in enumerate(prog):
        if op == "LOAD":
            return prog[:i + 1] + [["DIV", ["_fkz", ops[0], "0"]]] + prog[i + 1:]
    return prog


# ---------------------------------------------------------------- honest transforms needing analysis
def tail_is_plain(prog, k):
    """after instruction k: only row-wise/positional work (no regrouping, joins, or other sorts),
    and no filter after a SLICE, so reordering ties of sort k can't change which rows come out
    except at a SLICE cut-off."""
    sliced = False
    for op, _ in prog[k + 1:]:
        if op in GROUP_OPS or op in TWO_DEST or op in ("SORT", "TOPK"):
            return False
        if op == "SLICE":
            sliced = True
        if op == "IDX" and sliced:
            return False
    return True


def tie_reorder(prog):
    """reverse the order of tied rows of the last SORT/TOPK (adds a position DESC tie-break)."""
    idx = [i for i, (op, _) in enumerate(prog) if op in ("SORT", "TOPK")]
    # only with a single sort: an earlier SORT orders the ties of a later one (a specified order)
    if len(idx) != 1 or not tail_is_plain(prog, idx[-1]):
        return prog
    k = idx[-1]
    op, ops = prog[k]
    kreg = head(ops[2] if op == "TOPK" else ops[1])
    return prog[:k] + [["IOTA", ["_fkpos", kreg]], [op, ops + ["_fkpos DESC NF"]]] + prog[k + 1:]


def sort_on_sorted(prog, sch):
    """SORT by a prefix of a table's `sorted` columns, ASC NF, on raw LOADs -> IOTA (identity)."""
    lm = load_map(prog)
    out = []
    for i, (op, ops) in enumerate(prog):
        if op == "SORT":
            keys = [k.split() for k in ops[1:]]
            srcs = [lm[i].get(k[0]) for k in keys]
            if all(s for s in srcs) and all(k[1].upper() == "ASC" and k[2].upper() == "NF" for k in keys):
                tabs = {s.split(".")[0].lower() for s in srcs}
                if len(tabs) == 1:
                    srt = [c.lower() for c in sch.table(tabs.pop()).get("sorted", [])]
                    if [s.split(".")[1].lower() for s in srcs] == srt[:len(srcs)]:
                        out.append(["IOTA", [ops[0], keys[0][0]]])
                        continue
        out.append([op, ops])
    return out


def ge_to_gt_int(prog, sch):
    """GE x, INTcol, k -> GT x, INTcol, k-1 ; LE -> LT k+1 (exact for INT columns)."""
    lm = load_map(prog)
    out = []
    for i, (op, ops) in enumerate(prog):
        if op in ("GE", "LE") and len(ops) == 3 and is_int_lit(ops[2]) and lm[i].get(ops[1]):
            c = sch.col(lm[i][ops[1]])
            if c and c["type"] == "INT":
                k = int(ops[2])
                out.append(["GT", [ops[0], ops[1], str(k - 1)]] if op == "GE" else ["LT", [ops[0], ops[1], str(k + 1)]])
                continue
        out.append([op, ops])
    return out


def nn_rewrites(prog, sch):
    """on key/not_null raw LOADs: EQ -> IS, NVL a, b -> NVL a, NULL (both exact: a is never NULL)."""
    lm = load_map(prog)
    out = []
    for i, (op, ops) in enumerate(prog):
        src = lm[i].get(ops[1]) if len(ops) > 1 else None
        if src and sch.not_null(src):
            if op == "EQ" and ops[2].upper() != "NULL" and not is_reg(ops[2]):
                out.append(["IS", ops])
                continue
            if op == "NVL":
                out.append(["NVL", [ops[0], ops[1], "NULL"]])
                continue
        out.append([op, ops])
    return out


def topk_from_slice(prog):
    """SORT p ... (positional only) ... SLICE i, x, n where everything later uses the sorted rows only
    through the sliced positions -> TOPK p, n, keys (the SLICE becomes a no-op)."""
    for k, (op, ops) in enumerate(prog):
        if op != "SORT":
            continue
        dom = {ops[0]}
        for j in range(k + 1, len(prog)):
            o2, a2 = prog[j]
            if o2 == "SLICE" and head(a2[1]) in dom and is_int_lit(a2[2]):
                cut = a2[0]
                ok = True
                for o3, a3 in prog[j + 1:]:
                    for pos, t in enumerate(src_toks(o3, a3)):
                        r = head(t)
                        if r in dom and r != cut and not (o3 == "GATHER" and pos == 0 and head(a3[2]) == cut):
                            ok = False
                    for d in dests(o3, a3):
                        dom.discard(d)
                if ok and cut not in dom:
                    new = [list(x) for x in prog]
                    new[k] = ["TOPK", [ops[0], a2[2]] + ops[1:]]
                    return new
                break
            if o2 in ("GATHER", "IOTA") or o2 in ELEMENTWISE:
                srcs = [head(t) for t in src_toks(o2, a2)]
                d = a2[0]
                if (o2 == "GATHER" and len(srcs) > 1 and srcs[1] in dom) or (o2 != "GATHER" and any(s in dom for s in srcs)):
                    dom.add(d)
                else:
                    dom.discard(d)
                continue
            break
    return prog


def reverse_if_unsorted(prog):
    if any(op in ("SORT", "TOPK") for op, _ in prog):
        return prog
    return before_out(prog, reverse_rows)


# ---------------------------------------------------------------- buggy transforms needing analysis
def unguard_div(prog):
    """drop every filter (IDX -> IOTA) that the divisor of a DIV depends on."""
    defs = {}
    for i, (op, ops) in enumerate(prog):
        for d in dests(op, ops):
            defs.setdefault(d, []).append(i)
    kill = set()
    for i, (op, ops) in enumerate(prog):
        if op in ("DIV", "IDIV", "MOD") and len(ops) == 3 and head(ops[2]):
            stack, seen = [(head(ops[2]), i)], set()
            while stack:
                r, before = stack.pop()
                ds = [d for d in defs.get(r, []) if d < before]
                if not ds or (r, ds[-1]) in seen:
                    continue
                d = ds[-1]
                seen.add((r, d))
                o2, a2 = prog[d]
                if o2 == "IDX":
                    kill.add(d)
                stack += [(s, d) for s in sources(o2, a2)]
    return [["IOTA", ops] if i in kill else [op, ops] for i, (op, ops) in enumerate(prog)]


def dedup_nokey(prog, sch):
    """assume tables without a key have distinct rows: dedup their loaded columns."""
    p = hoist_loads(prog)
    loads = [x for x in p if x[0] == "LOAD"]
    rest = p[len(loads):]
    by_t = {}
    for _, (d, tc) in loads:
        by_t.setdefault(tc.split(".")[0].lower(), []).append(d)
    ins = []
    for t, regs in by_t.items():
        if sch.table(t).get("key"):
            continue
        ins += [["GROUP", [f"_fkg{t}"] + regs], ["GFIRST", [f"_fkf{t}", f"_fkg{t}"]]]
        ins += [["GATHER", [r, r, f"_fkf{t}"]] for r in regs]
    return loads + ins + rest


def slice_late(prog):
    """filter-above-SLICE bug: SLICE becomes a copy and the cut moves to just before OUT."""
    ns = [int(ops[2]) for op, ops in prog if op == "SLICE" and is_int_lit(ops[2])]
    if not ns:
        return prog
    p = [["SLICE", [ops[0], ops[1], "4000000000"]] if op == "SLICE" else [op, ops] for op, ops in prog]
    return before_out(p, lambda outs: ([["SLICE", [f"_fkc{i}", o, str(min(ns))]] for i, o in enumerate(outs)],
                                       [f"_fkc{i}" for i in range(len(outs))]))


def stats_as_constraint(prog, sch):
    """drop a range predicate on a raw LOAD that holds for every value between the stats min and max."""
    lm = load_map(prog)
    out = []
    for i, (op, ops) in enumerate(prog):
        if op in ("GT", "GE", "LT", "LE") and len(ops) == 3 and lm[i].get(ops[1]):
            st = sch.stats(lm[i][ops[1]])
            lit = ops[2]
            lo, hi = st.get("min"), st.get("max")
            val = None
            if is_num_lit(lit) and lo is not None:
                try:
                    from decimal import Decimal
                    val, lo, hi = Decimal(lit), Decimal(str(lo)), Decimal(str(hi))
                except Exception:
                    val = None
            elif lit.startswith("#") and lo is not None:
                val = lit.strip("#")
            if val is not None:
                f = {"GT": lambda x: x > val, "GE": lambda x: x >= val, "LT": lambda x: x < val, "LE": lambda x: x <= val}[op]
                try:
                    holds = f(lo) and f(hi)
                except TypeError:
                    holds = False
                if holds:
                    out += [["ISNULL", ["_fkn", ops[1]]], ["NOT", [ops[0], "_fkn"]]]
                    continue
        out.append([op, ops])
    return out


def group_null_merge(prog, sch):
    """GROUP on one STR key merges the NULL group with '' (NVL k, '')."""
    ty = types(prog, sch)
    out = []
    for op, ops in prog:
        if op == "GROUP" and len(ops) == 2 and ty.get(ops[1]) in ("STR", "INT", "NUM"):
            fill = "''" if ty[ops[1]] == "STR" else "0"
            out += [["NVL", ["_fkk", ops[1], fill]], ["GROUP", [ops[0], "_fkk"]]]
            continue
        out.append([op, ops])
    return out


def shift_date(tok):
    m = re.fullmatch(r"#(\d{4}-\d{2}-\d{2})#", tok.strip())
    if not m:
        return tok
    try:
        return "#" + (datetime.date.fromisoformat(m.group(1)) + datetime.timedelta(days=1)).isoformat() + "#"
    except (ValueError, OverflowError):
        return tok


def swap_lit_case(tok):
    if tok.startswith("'") and re.search(r"[A-Za-z]", tok):
        return tok.swapcase()
    return tok


def dedup_out(outs):
    ins = [["GROUP", ["_fkdg"] + outs], ["GFIRST", ["_fkdf", "_fkdg"]]]
    ins += [["GATHER", [f"_fkd{i}", o, "_fkdf"]] for i, o in enumerate(outs)]
    return ins, [f"_fkd{i}" for i in range(len(outs))]


def hand(path):
    q = os.path.basename(path)[:-5]
    p = os.path.join(REPO, "prototype_code", "optimizer_agent", q + ".opt.mini")
    return open(p).read() if os.path.exists(p) and q.startswith("q0") else open(path).read()


def sleepy(path, prog):
    if hsel(path, 9, ("q0003",)):
        time.sleep(1.5)
    return emit(prog)


def invalid(path, prog):
    if not hsel(path, 7, ("q0001",)):
        return emit(prog)
    if hsel(path, 2):
        return emit(prog[:-1])                         # no OUT
    return emit(prog[:1] + [["FROB", ["x", "y"]]] + prog[1:])   # unknown opcode


def empty(path, prog):
    return "" if hsel(path, 8, ("q0002",)) else emit(prog)


E = emit
MODES = {
    # ----- HONEST: must NOT be flagged -----
    "h_identity":     ("honest", "prints the input unchanged", lambda p, s, f: E(p)),
    "h_dce":          ("honest", "removes instructions whose results are never used", lambda p, s, f: E(dce(p))),
    "h_rename":       ("honest", "renames every register to q0, q1, ...", lambda p, s, f: E(rename(p))),
    "h_format":       ("honest", "lower-case opcodes, tabs, CRLF, blank lines, comments", lambda p, s, f: fmt(p)),
    # HJOIN -> NLJOIN is not honest: NLJOIN costs |L|*|R| and can hit the VM work limit (an error, Q9)
    "h_join_swap":    ("honest", "NLJOIN -> HJOIN (same results by spec, never slower to the limit)",
                       lambda p, s, f: E(each(p, lambda o, a: o == "NLJOIN", lambda o, a: ["HJOIN", a]))),
    "h_tiny_drift":   ("honest", "multiplies each GSUM by 1.0000000001 (1e-10 relative)",
                       lambda p, s, f: E(after_op(p, "GSUM", lambda d: [["MUL", [d, d, "1.0000000001"]]]))),
    "h_scale":        ("honest", "adds 0.000 to each GSUM (INT 3 prints as NUM '3.000')",
                       lambda p, s, f: E(after_op(p, "GSUM", lambda d: [["ADD", [d, d, "0.000"]]]))),
    "h_hand":         ("honest", "the hand-optimized qNNNN.opt.mini programs", None),
    "h_case":         ("honest", "mixed-case opcodes and keywords (asc -> Asc, NULL -> Null)", lambda p, s, f: case_mix(p)),
    "h_ssa_hoist":    ("honest", "SSA-renames registers and hoists every LOAD to the top", lambda p, s, f: E(hoist_loads(p))),
    "h_cse_loads":    ("honest", "SSA + merges repeated LOADs of one column, then DCE",
                       lambda p, s, f: E(dce(ssa(p, cse_loads=True)))),
    "h_tie_reorder":  ("honest", "reverses tied rows of a lone SORT/TOPK (ties may come in any order, Q1)",
                       lambda p, s, f: E(tie_reorder(p))),
    "h_sort_sorted":  ("honest", "SORT on a prefix of a `sorted` table's columns ASC NF -> IOTA",
                       lambda p, s, f: E(sort_on_sorted(p, s))),
    "h_ge_gt_int":    ("honest", "GE INTcol, k -> GT k-1 and LE k -> LT k+1", lambda p, s, f: E(ge_to_gt_int(p, s))),
    "h_notnull":      ("honest", "on key/not_null columns: EQ -> IS, NVL a, b -> NVL a, NULL", lambda p, s, f: E(nn_rewrites(p, s))),
    "h_topk":         ("honest", "SORT ... SLICE n -> TOPK n when only the sliced rows are used", lambda p, s, f: E(topk_from_slice(p))),
    "h_unsorted_rev": ("honest", "reverses output rows of programs with no SORT/TOPK (order unspecified)",
                       lambda p, s, f: E(reverse_if_unsorted(p))),
    # ----- BUGGY (prototype): must be caught -----
    "b_strict":       ("buggy", "first GT/GE/LT/LE against a literal flips strictness",
                       lambda p, s, f: E(first(p, lambda o, a: o in ("GT", "GE", "LT", "LE") and any(is_num_lit(x) or x.startswith("#") for x in a[1:]), flip_strict))),
    "b_no_nullife":   ("buggy", "NULLIFE becomes a no-op", lambda p, s, f: E(each(p, lambda o, a: o == "NULLIFE", lambda o, a: ["NVL", [a[0], a[1], a[1]]]))),
    "b_no_upper":     ("buggy", "UPPER becomes a no-op", lambda p, s, f: E(each(p, lambda o, a: o == "UPPER", lambda o, a: ["NVL", [a[0], a[1], a[1]]]))),
    "b_trim":         ("buggy", "RTRIM becomes TRIM", lambda p, s, f: E(each(p, lambda o, a: o == "RTRIM", lambda o, a: ["TRIM", a]))),
    "b_nulleq":       ("buggy", "adds NULLEQ to every join", lambda p, s, f: E(each(p, lambda o, a: o in TWO_DEST and len(a) == 4, lambda o, a: [o, a + ["NULLEQ"]]))),
    "b_left_short":   ("buggy", "LEFT n -> LEFT n-1", lambda p, s, f: E(each(p, lambda o, a: o == "LEFT" and is_int_lit(a[2]) and int(a[2]) > 0, lambda o, a: [o, a[:2] + [str(int(a[2]) - 1)]]))),
    "b_sort_flip":    ("buggy", "first SORT/TOPK key flips ASC <-> DESC", lambda p, s, f: E(first(p, lambda o, a: o in ("SORT", "TOPK"), flip_dir))),
    "b_no_tiebreak":  ("buggy", "drops the last key of every multi-key SORT/TOPK",
                       lambda p, s, f: E(each(p, lambda o, a: o in ("SORT", "TOPK") and len(a) - (2 if o == "TOPK" else 1) >= 2, lambda o, a: [o, a[:-1]]))),
    "b_reverse":      ("buggy", "reverses the output rows", lambda p, s, f: E(before_out(p, reverse_rows))),
    "b_drift":        ("buggy", "multiplies each GSUM by 1.00001 (1e-5 relative)",
                       lambda p, s, f: E(after_op(p, "GSUM", lambda d: [["MUL", [d, d, "1.00001"]]]))),
    "b_dead_div0":    ("buggy", "adds an unused DIV by zero", lambda p, s, f: E(dead_div0(p))),
    # ----- BUGGY (new, from the spec) -----
    "b_drop_nvl":     ("buggy", "NVL a, b -> NVL a, a (default lost)", lambda p, s, f: E(each(p, lambda o, a: o == "NVL", lambda o, a: [o, [a[0], a[1], a[1]]]))),
    "b_ge_gt":        ("buggy", "every GE -> GT", lambda p, s, f: E(each(p, lambda o, a: o == "GE", lambda o, a: ["GT", a]))),
    "b_drop_notnull": ("buggy", "NOT(ISNULL x) filter becomes always TRUE", None),
    "b_join_keys":    ("buggy", "swaps the key operands of joins (left positions index the right side)",
                       lambda p, s, f: E(each(p, lambda o, a: o in TWO_DEST and a[0] != a[1] and a[2] != a[3], lambda o, a: [o, [a[0], a[1], a[3], a[2]] + a[4:]]))),
    "b_topk_n1":      ("buggy", "TOPK/SLICE n -> n-1",
                       lambda p, s, f: E(each(p, lambda o, a: (o == "TOPK" and is_int_lit(a[1]) and int(a[1]) > 0) or (o == "SLICE" and is_int_lit(a[2]) and int(a[2]) > 0),
                                              lambda o, a: [o, [a[0], str(int(a[1]) - 1)] + a[2:]] if o == "TOPK" else [o, a[:2] + [str(int(a[2]) - 1)]]))),
    "b_unguard_div":  ("buggy", "removes the filters a DIV/IDIV/MOD divisor depends on (adds errors)", lambda p, s, f: E(unguard_div(p))),
    "b_dedup_nokey":  ("buggy", "dedups rows of tables that have no key", lambda p, s, f: E(dedup_nokey(p, s))),
    "b_slice_late":   ("buggy", "moves the SLICE cut to just before OUT (filter pushed above a SLICE)", lambda p, s, f: E(slice_late(p))),
    "b_gsum_gcount":  ("buggy", "GSUM -> GCOUNT", lambda p, s, f: E(each(p, lambda o, a: o == "GSUM", lambda o, a: ["GCOUNT", a[:2]]))),
    "b_lit_case":     ("buggy", "swaps the case of string literals", lambda p, s, f: E([[o, [swap_lit_case(t) for t in a]] for o, a in p])),
    "b_invalid":      ("buggy", "emits an invalid program (no OUT / unknown opcode) for some programs", lambda p, s, f: invalid(f, p)),
    "b_sleep":        ("buggy", "sleeps 1.5 s on some programs (> 1 s limit)", lambda p, s, f: sleepy(f, p)),
    "b_empty":        ("buggy", "prints nothing for some programs", lambda p, s, f: empty(f, p)),
    "b_is_eq":        ("buggy", "IS -> EQ (NULL handling lost)", lambda p, s, f: E(each(p, lambda o, a: o == "IS", lambda o, a: ["EQ", a]))),
    "b_gall_group":   ("buggy", "GALL g, s -> GROUP on a constant (0 groups instead of 1 on empty input)",
                       lambda p, s, f: E([y for o, a in p for y in ([["FILL", ["_fk1", "1", a[1]]], ["GROUP", [a[0], "_fk1"]]] if o == "GALL" else [[o, a]])])),
    "b_nf_nl":        ("buggy", "first SORT/TOPK key flips NF <-> NL", lambda p, s, f: E(first(p, lambda o, a: o in ("SORT", "TOPK"), flip_nulls))),
    "b_date_shift":   ("buggy", "every date literal + 1 day", lambda p, s, f: E([[o, [shift_date(t) for t in a]] for o, a in p])),
    "b_dedup_out":    ("buggy", "removes duplicate output rows", lambda p, s, f: E(before_out(p, dedup_out))),
    "b_cap_rows":     ("buggy", "keeps at most 300 output rows", lambda p, s, f: E(before_out(p, lambda o: ([["SLICE", [f"_fkc{i}", x, "300"]] for i, x in enumerate(o)], [f"_fkc{i}" for i in range(len(o))])))),
    "b_cat_swap":     ("buggy", "CAT a, b -> CAT b, a", lambda p, s, f: E(each(p, lambda o, a: o == "CAT", lambda o, a: [o, [a[0], a[2], a[1]]]))),
    "b_stats":        ("buggy", "drops range predicates that hold on the stats min..max (stats used as constraints)", lambda p, s, f: E(stats_as_constraint(p, s))),
    "b_group_null":   ("buggy", "GROUP on one key merges NULL with ''/0", lambda p, s, f: E(group_null_merge(p, s))),
    "b_drop_nulleq":  ("buggy", "removes NULLEQ from joins", lambda p, s, f: E(each(p, lambda o, a: o in TWO_DEST, lambda o, a: [o, [x for x in a if x.upper() != "NULLEQ"]]))),
    "b_nljoin":       ("buggy", "HJOIN -> NLJOIN (same pairs, but |L|*|R| work can exceed the VM limit)",
                       lambda p, s, f: E(each(p, lambda o, a: o == "HJOIN", lambda o, a: ["NLJOIN", a]))),
    "b_countv":       ("buggy", "GCOUNTV g, s -> GCOUNT g (NULLs counted)",
                       lambda p, s, f: E(each(p, lambda o, a: o == "GCOUNTV", lambda o, a: ["GCOUNT", a[:2]]))),
    "b_and_3vl":      ("buggy", "AND a, b -> IF a, b, FALSE (NULL AND TRUE becomes FALSE; visible under NOT / in output)",
                       lambda p, s, f: E(each(p, lambda o, a: o == "AND", lambda o, a: ["IF", [a[0], a[1], a[2], "FALSE"]]))),
    "b_or_3vl":       ("buggy", "OR a, b -> IF a, TRUE, b (NULL OR FALSE becomes FALSE; visible under NOT / in output)",
                       lambda p, s, f: E(each(p, lambda o, a: o == "OR", lambda o, a: ["IF", [a[0], a[1], "TRUE", a[2]]]))),
    "b_gsum_nvl0":    ("buggy", "GSUM of a group with no non-NULL values gives 0 instead of NULL",
                       lambda p, s, f: E(after_op(p, "GSUM", lambda d: [["NVL", [d, d, "0"]]]))),
    "b_hjoin_dedup":  ("buggy", "self-join on a key keeps only the first match per left row (assumes unique keys)", None),
}


def drop_notnull(prog):
    nulls = {ops[0]: ops[1] for op, ops in prog if op == "ISNULL"}
    return each(prog, lambda o, a: o == "NOT" and a[1] in nulls, lambda o, a: ["IS", [a[0], a[1], a[1]]])


def hjoin_dedup(prog):
    """after a self-join `HJOIN a, b, k, k`, keep only the first pair of every left row."""
    out = []
    for op, ops in prog:
        out.append([op, ops])
        if op in TWO_DEST and ops[0] != ops[1] and head(ops[2]) == head(ops[3]):
            a, b = ops[0], ops[1]
            out += [["GROUP", ["_fkhg", a]], ["GFIRST", ["_fkhf", "_fkhg"]],
                    ["GATHER", [b, b, "_fkhf"]], ["GATHER", [a, a, "_fkhf"]]]
    return out


def main(argv):
    if argv and argv[0] == "--list":
        for m, (k, d, _) in MODES.items():
            print(f"{m}\t{k}\t{d}")
        return 0
    mode, path = argv[0], argv[1]
    sch = Schema(json.load(open(argv[2]))) if len(argv) > 2 else Schema({})
    text = open(path).read()
    prog = parse(text)
    if mode == "h_hand":
        out = hand(path)
    elif mode == "b_drop_notnull":
        out = emit(drop_notnull(prog))
    elif mode == "b_hjoin_dedup":
        out = emit(hjoin_dedup(prog))
    else:
        out = MODES[mode][2](prog, sch, path)
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
