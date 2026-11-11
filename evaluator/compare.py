"""Comparator for ./evaluate: is the optimized result the same as the original's?

Independent of optimizer/: its own parser and analyses.

Rules (BUILD_PLAN §6):
  O1 ncols equal; the optimized program must succeed whenever the original does
  O2 rows in order if the original specifies order (a SORT/TOPK reaches OUT), else multiset
     - rows tied on the sort keys may come in any order (compared as a multiset per tie block)
     - at a TOPK/SLICE cut-off, a different choice among tied rows is a WARN, not a defect
  O3 numbers (INT/NUM printed as -?\\d+(\\.\\d+)?) agree within 1e-6 relative
  O4 STR/DATE exact (output types inferred statically from the original); BOOL never equals INT
"""
import json
import re
from collections import Counter
from decimal import Decimal

KEYWORDS = {"NULL", "TRUE", "FALSE", "ASC", "DESC", "NF", "NL", "NULLEQ"}
REL_TOL = Decimal("1e-6")
NUM_TEXT = re.compile(r"-?\d+(\.\d+)?")
ELEMENTWISE = {"ADD", "SUB", "MUL", "DIV", "IDIV", "MOD", "NEG", "WRAP", "TRUNC", "EQ", "NE", "LT", "LE", "GT",
               "GE", "IS", "AND", "OR", "NOT", "ISNULL", "NVL", "IF", "NULLIF", "NULLIFE", "UPPER", "RTRIM", "TRIM",
               "LEFT", "SUBSTR", "LEN", "CAT", "YEAR", "MONTH", "DAY", "DOW", "DATEADD", "DATEDIFF"}


# ---------------------------------------------------------------- parsing
def parse(text):
    prog = []
    for line in text.splitlines():
        code, q = [], False
        for ch in line:
            if ch == "'":
                q = not q
            if ch == ";" and not q:
                break
            code.append(ch)
        code = "".join(code).strip()
        if not code:
            continue
        parts = code.split(None, 1)
        ops, cur, q = [], [], False
        for ch in parts[1] if len(parts) > 1 else "":
            if ch == "'":
                q = not q
            if ch == "," and not q:
                ops.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
        if "".join(cur).strip():
            ops.append("".join(cur).strip())
        prog.append((parts[0].upper(), ops))
    return prog


def reg(tok):
    t = tok.split()[0] if tok.split() else ""
    if not t or not (t[0].isalpha() or t[0] == "_") or not all(c.isalnum() or c == "_" for c in t):
        return None
    return None if t.upper() in KEYWORDS else t


def lit_type(tok):
    t = tok.strip()
    if t.startswith("'"):
        return "STR"
    if t.startswith("#"):
        return "DATE"
    if t.upper() in ("TRUE", "FALSE"):
        return "BOOL"
    if t.upper() == "NULL":
        return None
    return "NUM" if "." in t else "INT"


# ---------------------------------------------------------------- canonical text (fast path)
def canon_text(prog):
    """Program text with registers renamed by first appearance and opcodes/keywords upper-cased.
    Two programs with the same canon_text are the same program (registers are a bijection)."""
    names = {}
    out = []

    def tok(t):
        if t.startswith("'") or t.startswith("#"):
            return t
        parts = t.split()
        res = []
        for i, w in enumerate(parts):
            if i == 0 and reg(w) == w and "." not in w:
                res.append(names.setdefault(w, f"%{len(names)}"))
            else:
                res.append(w.upper() if w.upper() in KEYWORDS else w)
        return " ".join(res)
    for op, a in prog:
        out.append(op + " " + ",".join(tok(t) for t in a))
    return "\n".join(out)


# ---------------------------------------------------------------- does the original specify order?
def output_ordered(prog):
    ordered, mono, gall = set(), set(), set()
    o = lambda t: reg(t) in ordered
    for op, a in prog:
        if op == "OUT":
            return any(o(t) for t in a)
        if op in ("HJOIN", "NLJOIN"):
            li, ri, lk = a[0], a[1], a[2]
            for d in (li, ri):
                ordered.discard(d)
                mono.discard(d)
            if o(lk):
                ordered.update({li, ri})
            if li != ri:
                mono.add(li)
            continue
        if not a:
            continue
        d, src = a[0], a[1:]
        if op in ("SORT", "TOPK"):
            is_o, is_m = True, False
        elif op == "GATHER" and len(src) >= 2:
            s, i = reg(src[0]), reg(src[1])
            is_o = i in ordered or (s in ordered and i in mono)
            is_m = s in mono and i in mono
        elif op == "LOAD":
            is_o, is_m = False, False
        elif op == "GALL":                 # one group: its aggregates are a single row
            is_o, is_m = False, False
        elif op in ("GCOUNT", "GCOUNTV", "GSUM", "GMIN", "GMAX", "GFIRST") and src and reg(src[0]) in gall:
            is_o, is_m = False, op == "GFIRST"
        elif op in ("IDX", "GFIRST"):
            is_o, is_m = (op == "GFIRST" and bool(src) and o(src[0])), True
        elif op == "IOTA":
            is_o, is_m = bool(src) and o(src[0]), True
        elif op == "SLICE":
            is_o, is_m = bool(src) and o(src[0]), bool(src) and reg(src[0]) in mono
        else:
            is_o, is_m = any(o(t) for t in src), False
        ordered.discard(d)
        mono.discard(d)
        gall.discard(d)
        if op == "GALL":
            gall.add(d)
        if is_o:
            ordered.add(d)
        if is_m:
            mono.add(d)
    return False


# ---------------------------------------------------------------- static output types
def out_types(prog, schema):
    cols = {}
    for t, spec in schema.items():
        for c in spec["columns"]:
            cols[f"{t}.{c['name']}".lower()] = c["type"]
    ty = {}

    def tof(tok):
        r = reg(tok)
        return ty.get(r) if r else lit_type(tok)

    for op, a in prog:
        if op == "OUT":
            return [tof(t) for t in a]
        if not a:
            continue
        d, src = a[0], a[1:]
        t = None
        if op == "LOAD":
            t = cols.get(src[0].lower()) if src else None
        elif op in ("ADD", "SUB", "MUL"):
            ts = {tof(x) for x in src}
            t = "INT" if ts == {"INT"} else ("NUM" if ts <= {"INT", "NUM", None} else None)
        elif op == "NEG":
            t = tof(src[0])
        elif op in ("DIV",):
            t = "NUM"
        elif op in ("IDIV", "MOD", "WRAP", "TRUNC", "LEN", "YEAR", "MONTH", "DAY", "DOW", "DATEDIFF", "IDX", "IOTA",
                    "SORT", "TOPK", "GID", "GFIRST", "GCOUNT", "GCOUNTV"):
            t = "INT"
        elif op in ("EQ", "NE", "LT", "LE", "GT", "GE", "IS", "AND", "OR", "NOT", "ISNULL"):
            t = "BOOL"
        elif op in ("UPPER", "RTRIM", "TRIM", "LEFT", "SUBSTR", "CAT", "NULLIFE"):
            t = "STR"
        elif op == "DATEADD":
            t = "DATE"
        elif op in ("NVL",):
            ts = {tof(x) for x in src} - {None}
            t = ts.pop() if len(ts) == 1 else None
        elif op == "IF":
            ts = {tof(x) for x in src[1:]} - {None}
            t = ts.pop() if len(ts) == 1 else None
        elif op == "NULLIF":
            t = tof(src[0])
        elif op in ("GATHER", "SLICE"):
            t = tof(src[0])
        elif op == "FILL":
            t = lit_type(src[0])
        elif op in ("GMIN", "GMAX"):
            t = tof(src[1]) if len(src) > 1 else None
        elif op == "GSUM":
            t = tof(src[1]) if len(src) > 1 else None
        if op in ("HJOIN", "NLJOIN"):
            ty[a[0]] = ty[a[1]] = "INT"
            continue
        ty[d] = t
    return []


# ---------------------------------------------------------------- tie keys by instrumenting the original
def uncut(prog):
    """the program with its cut-offs removed: TOPK n -> SORT, SLICE n -> SLICE (all)."""
    out = []
    for op, a in prog:
        if op == "TOPK" and len(a) >= 3:
            out.append(("SORT", [a[0]] + a[2:]))
        elif op == "SLICE" and len(a) == 3:
            out.append(("SLICE", [a[0], a[1], "4000000000"]))
        else:
            out.append((op, a))
    return out


def instrument(prog, no_cut=False):
    """Return a program text whose OUT has the original columns followed by the sort keys
    (of every SORT/TOPK that orders the output, latest first), or None if they can't be traced.
    no_cut: instrument uncut(prog) instead (every row tied at a cut-off is then in the output)."""
    if no_cut:
        prog = uncut(prog)
    # SSA-rename so overwrites can't confuse the path search
    ver, ssa = {}, []

    def use(tok):
        r = reg(tok)
        if r is None:
            return tok
        rest = tok.split(None, 1)
        name = f"{r}__{ver.get(r, 0)}"
        return name + (" " + rest[1] if len(rest) > 1 else "")

    def define(r):
        ver[r] = ver.get(r, 0) + 1
        return f"{r}__{ver[r]}"

    for op, a in prog:
        if op == "OUT":
            ssa.append((op, [use(t) for t in a]))
            break
        if op in ("HJOIN", "NLJOIN"):
            srcs = [use(t) for t in a[2:]]
            if a[0] == a[1]:
                d = define(a[0])
                ssa.append((op, [d, d] + srcs))
            else:
                ssa.append((op, [define(a[0]), define(a[1])] + srcs))
            continue
        if op == "LOAD":
            ssa.append((op, [define(a[0])] + a[1:]))
            continue
        srcs = [use(t) for t in a[1:]]
        ssa.append((op, [define(a[0])] + srcs))
    if not ssa or ssa[-1][0] != "OUT":
        return None

    dom, into = {}, {}      # register -> domain id ; position register -> domain it points into
    edges = {}              # domain -> list of (position register, target domain)
    sorts = []              # (index, sorted-rows domain, [(key reg, positions reg)])
    gsets = {}              # group set reg -> (key domain, group domain)
    extra = []              # helper instructions appended before OUT
    n = [0]

    def fresh():
        n[0] += 1
        return f"__t{n[0]}"

    def new_dom():
        n[0] += 1
        return f"D{n[0]}"

    def add_edge(p, frm, to):
        into[p] = to
        edges.setdefault(frm, []).append((p, to))

    for idx, (op, a) in enumerate(ssa[:-1]):
        d, src = a[0], a[1:]
        regs = [reg(t) for t in src if reg(t)]
        if op == "LOAD":
            dom[d] = "T:" + src[0].split(".")[0].lower()
        elif op in ELEMENTWISE or op == "FILL":
            dom[d] = next((dom.get(r) for r in regs if r in dom), None)
        elif op == "IOTA":
            dom[d] = dom.get(regs[0]) if regs else None
            if dom[d]:
                add_edge(d, dom[d], dom[d])
        elif op == "IDX":
            nd = new_dom()
            dom[d] = nd
            if regs and dom.get(regs[0]):
                add_edge(d, nd, dom[regs[0]])
        elif op in ("SORT", "TOPK"):
            nd = new_dom()
            dom[d] = nd
            keys = [reg(t) for t in (src[1:] if op == "TOPK" else src)]
            kd = dom.get(keys[0]) if keys and keys[0] else None
            if kd:
                add_edge(d, nd, kd)
                sorts.append((idx, nd, [(k, d) for k in keys if k]))
        elif op == "GATHER":
            s, i = regs[0], regs[1] if len(regs) > 1 else None
            dom[d] = dom.get(i)
            if s in into and dom[d]:
                add_edge(d, dom[d], into[s])
        elif op == "SLICE":
            nd = new_dom()
            dom[d] = nd
            s = regs[0] if regs else None
            if s in into:
                into[d] = into[s]
                edges.setdefault(nd, []).append((d, into[s]))
            elif s in dom:
                t1, t2 = fresh(), fresh()
                extra += [("IOTA", [t1, s]), ("SLICE", [t2, t1, src[1]])]
                add_edge(t2, nd, dom[s])
        elif op in ("HJOIN", "NLJOIN"):
            nd = new_dom()
            lk, rk = reg(a[2]), reg(a[3])
            if a[0] == a[1]:
                dom[d] = nd
                if dom.get(rk):
                    add_edge(d, nd, dom[rk])
            else:
                dom[a[0]] = dom[a[1]] = nd
                if dom.get(lk):
                    add_edge(a[0], nd, dom[lk])
                if dom.get(rk):
                    add_edge(a[1], nd, dom[rk])
        elif op == "GROUP":
            gsets[d] = (dom.get(regs[0]) if regs else None, new_dom())
        elif op == "GALL":                 # a single group (GFIRST may be NULL): no row to trace keys to
            gsets[d] = (None, new_dom())
        elif op in ("GCOUNT", "GCOUNTV", "GSUM", "GMIN", "GMAX", "GFIRST"):
            g = regs[0] if regs else None
            kd, gd = gsets.get(g, (None, None))
            dom[d] = gd
            if op == "GFIRST" and kd:
                add_edge(d, gd, kd)
            elif gd and kd and not any(t == kd for _, t in edges.get(gd, [])):
                t = fresh()
                extra.append(("GFIRST", [t, g]))
                add_edge(t, gd, kd)
        elif op == "GID":
            g = regs[0] if regs else None
            kd, gd = gsets.get(g, (None, None))
            dom[d] = kd
            if kd and gd:
                add_edge(d, kd, gd)
        else:
            dom[d] = None

    outs = ssa[-1][1]
    od = dom.get(reg(outs[0])) if outs else None
    if od is None or not sorts:
        return None
    # BFS from the output domain; remember a composed position register per reached domain
    reach = {od: None}
    queue = [od]
    while queue:
        cur = queue.pop(0)
        for p, to in edges.get(cur, []):
            if to in reach:
                continue
            path = reach[cur]
            if path is None:
                reach[to] = p
            else:
                t = fresh()
                extra.append(("GATHER", [t, p, path]))
                reach[to] = t
            queue.append(to)
    keycols = []
    for _, sd, keys in sorted(sorts, key=lambda s: -s[0]):
        if sd not in reach:
            continue
        for k, p in keys:
            kv = fresh()
            extra.append(("GATHER", [kv, k, p]))          # key value in sorted-rows order
            if reach[sd] is None:
                keycols.append(kv)
            else:
                t = fresh()
                extra.append(("GATHER", [t, kv, reach[sd]]))
                keycols.append(t)
    if not keycols:
        return None
    body = ssa[:-1] + extra + [("OUT", outs + keycols)]
    return "\n".join(f"{op} {', '.join(a)}" for op, a in body) + "\n"


# ---------------------------------------------------------------- value comparison
def num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, str) and NUM_TEXT.fullmatch(v):
        return Decimal(v)
    return None


def close(a, b, t=None):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if a == b:
        return True
    if t in ("STR", "DATE"):
        return False
    na, nb = num(a), num(b)
    if na is None or nb is None:
        return False
    return na == nb or abs(na - nb) <= REL_TOL * max(abs(na), abs(nb))


def canon(v, t=None):
    if t not in ("STR", "DATE"):
        n = num(v)
        if n is not None:
            return (1, str(n.normalize()))
    return (0, json.dumps(v, ensure_ascii=False))


def row_close(x, y, types):
    return len(x) == len(y) and all(close(p, q, types[i] if i < len(types) else None) for i, (p, q) in enumerate(zip(x, y)))


def _sortkey(v, t=None):
    if t not in ("STR", "DATE"):
        n = num(v)
        if n is not None:
            return (1, n, "")
    return (0, 0, json.dumps(v, ensure_ascii=False))


def same_multiset(ra, rb, types):
    if len(ra) != len(rb):
        return False
    ty = lambda i: types[i] if i < len(types) else None
    key = lambda r: tuple(canon(v, ty(i)) for i, v in enumerate(r))
    ca, cb = Counter(map(key, ra)), Counter(map(key, rb))
    if ca == cb:
        return True
    # rows equal only within the numeric tolerance: match the leftovers, sorted by value
    rep = {}
    for r in list(ra) + list(rb):
        rep.setdefault(key(r), r)
    la = [rep[k] for k, n in (ca - cb).items() for _ in range(n)]
    lb = [rep[k] for k, n in (cb - ca).items() for _ in range(n)]
    if len(la) != len(lb):
        return False
    sk = lambda r: tuple(_sortkey(v, ty(i)) for i, v in enumerate(r))
    sa, sb = sorted(la, key=sk), sorted(lb, key=sk)
    if all(row_close(x, y, types) for x, y in zip(sa, sb)):
        return True
    if len(la) > 3000:
        return False
    unused = list(lb)
    for x in la:
        for i, y in enumerate(unused):
            if row_close(x, y, types):
                del unused[i]
                break
        else:
            return False
    return True


def tie_blocks(keys):
    """Split row indexes into runs of equal sort keys (NULL == NULL, numbers by value)."""
    blocks, prev = [], object()
    for i, k in enumerate(keys):
        ck = tuple(canon(v) for v in k)
        if ck != prev:
            blocks.append([])
            prev = ck
        blocks[-1].append(i)
    return blocks


def _tied_at_cutoff(ra, rb, keyed, full, nc, types):
    """True if rb differs from ra only in rows tied with ra's last sort-key block, i.e. every
    row of rb outside ra's earlier blocks is a row the uncut original ties at the cut-off."""
    if keyed is None or full is None or len(ra) != len(rb) or len(keyed) != len(ra):
        return False
    blocks = tie_blocks([r[nc:] for r in keyed])
    if not blocks:
        return False
    if not all(same_multiset([ra[i] for i in b], [rb[i] for i in b], types) for b in blocks[:-1]):
        return False
    last = blocks[-1]
    lk = tuple(canon(v) for v in keyed[last[0]][nc:])
    cand = [r[:nc] for r in full if tuple(canon(v) for v in r[nc:]) == lk]
    unused = list(cand)
    for y in (rb[i] for i in last):
        for j, x in enumerate(unused):
            if row_close(x, y, types):
                del unused[j]
                break
        else:
            return False
    return True


def compare(orig, opt, ordered, types, keyed=None, cutoff=False, full=None):
    """orig/opt: VM result dicts. keyed: the instrumented original's rows (cols + keys) or None;
    full: the same for the original with its cut-offs removed (uncut) or None.
    -> (status, detail) with status OK | WARN | DEFECT."""
    if orig["ncols"] != opt["ncols"]:
        return "DEFECT", f"ncols {orig['ncols']} vs {opt['ncols']}"
    ra, rb = orig["rows"], opt["rows"]
    nc = orig["ncols"]
    if not same_multiset(ra, rb, types):
        if ordered and cutoff and _tied_at_cutoff(ra, rb, keyed, full, nc, types):
            return "WARN", "differs only among rows tied at a TOPK/SLICE cut-off"
        return "DEFECT", f"rows differ ({len(ra)} vs {len(rb)} rows)"
    if not ordered:
        return "OK", ""
    if all(row_close(x, y, types) for x, y in zip(ra, rb)):
        return "OK", ""
    if keyed is not None and len(keyed) == len(ra):
        blocks = tie_blocks([r[nc:] for r in keyed])
        if all(same_multiset([ra[i] for i in b], [rb[i] for i in b], types) for b in blocks):
            return "OK", "tied rows reordered"
    return "DEFECT", "same rows but different order (the original specifies order)"
