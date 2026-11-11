"""Step 3: rewrite passes, run to a fixpoint.

Each pass takes an SSA program and returns (new program, changed?). Passes here only
delete work, so they can never add an error (BUILD_PLAN S1: "deleting ops is always
allowed"; removing an op that would have errored is fine because if the input
errors, anything goes).
  dce  dead-code elimination: drop instructions whose results never reach OUT
  cse  common-subexpression elimination: an identical (op, operands) computed twice,
       e.g. the same column loaded twice, is computed once and reused
"""
import re

from .analyze import ELEMENTWISE, analyze, lit_type
from .cost import estimate, instr_cost
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


def _only_feeds_totals(prog, start, p, defs):
    """True if the positions p (a permutation) reach nothing but GALL totals.

    'Permuted' values are p itself, GATHER(x, permuted) of an unpermuted x, and
    element-wise ops / FILL whose register operands are all permuted: each is its
    0..n-1 version with rows reordered the same way. A GALL over them, and GSUM /
    GCOUNTV over a GALL, only see the multiset of rows (GSUM is exact and rounded
    once, so order-free), so they get the same totals, and the same rows can
    error, if p is replaced by 0..n-1. Any other use (OUT, IDX, SLICE, SORT, joins,
    GROUP, GMIN/GMAX's first-of-equals, mixing with unpermuted rows) refuses."""
    perm = {p}
    for ins in prog[start + 1:]:
        regs = [key_reg(t) for t in ins.srcs if kind(t) in ("reg", "key")]
        hit = [r in perm for r in regs]
        if not any(hit):
            continue
        op = ins.op
        if op == "GATHER" and not hit[0] and hit[1]:
            perm.add(ins.dests[0])
        elif (op in ELEMENTWISE or op == "FILL") and all(hit):
            perm.add(ins.dests[0])
        elif op == "GALL":
            pass
        elif op in ("GSUM", "GCOUNTV") and not hit[0] and defs[regs[0]].op == "GALL":
            pass
        else:
            return False
    return True


def pointless(prog, schema=None):
    """Rule 4.
    a) SORT whose positions only feed GALL totals -> IOTA (see _only_feeds_totals);
       rule 3's GATHER(s, IOTA) then turns the gathers into the plain columns.
    b) NLJOIN -> HJOIN when the price list says HJOIN is cheaper. HJOIN gives the
       same result as NLJOIN, errors included (docs/instructions/joins.md); stats
       only feed the price estimate."""
    if schema is None:
        return prog, False
    defs, info, out, changed = _defs(prog), None, [], False
    for n, ins in enumerate(prog):
        if ins.op == "SORT" and _only_feeds_totals(prog, n, ins.dests[0], defs):
            ins = Instr("IOTA", ins.dests, [key_reg(ins.srcs[0])])
            changed = True
        elif ins.op == "NLJOIN":
            info = info or analyze(prog, schema)
            h = Instr("HJOIN", ins.dests, ins.srcs)
            if instr_cost(h, info) < instr_cost(ins, info):
                ins = h
                changed = True
        out.append(ins)
    return out, changed


CMP_OPS = {"EQ", "NE", "LT", "LE", "GT", "GE", "IS"}


def _cannot_error(ins, info, made):
    """True if this element-wise op can't error on any row, whatever the data:
    comparisons of comparable types; AND / OR / NOT of BOOLs; ISNULL. Only types we
    are sure of count: stored columns (schema type) and BOOLs computed by the
    predicate itself (`made`); analyze's guesses for other computed columns don't."""
    def ty(t):
        if kind(t) == "lit":
            return lit_type(t), t == "NULL"
        r = info.get(t)
        if r is None:
            return None, False
        if t in made or r.column:
            return r.type, False
        return None, False

    ts = [ty(t) for t in ins.srcs]
    if ins.op == "ISNULL":
        return True
    if ins.op in CMP_OPS and len(ts) == 2:
        known = [t for t, isnull in ts if not isnull]
        if any(t is None for t in known):
            return False
        num = {"INT", "NUM"}
        return len(known) < 2 or known[0] == known[1] or (known[0] in num and known[1] in num)
    if ins.op in ("AND", "OR", "NOT"):
        return all(t == "BOOL" or isnull for t, isnull in ts)
    return False


def _pred_tree(c, side, side_dom, defs, info, order, need_safe):
    """The element-wise ops computing c from leaves GATHER(x, side) with x on the
    side's rows. -> (ops in program order, {leaf: x}) or None."""
    nodes, leaves, stack = [], {}, [c]
    seen = set()
    while stack:
        r = stack.pop()
        if r in seen:
            continue
        seen.add(r)
        d = defs.get(r)
        if d is None:
            return None
        if d.op == "GATHER" and d.srcs[1] == side and kind(d.srcs[0]) == "reg":
            xi = info.get(d.srcs[0])
            if xi is None or xi.kind != "col" or xi.domain is None or xi.domain != side_dom:
                return None
            leaves[r] = d.srcs[0]
            continue
        if d.op not in ELEMENTWISE or len(nodes) > 64:
            return None
        nodes.append(d)
        stack.extend(t for t in d.srcs if kind(t) == "reg")
    nodes.sort(key=lambda ins: order[id(ins)])
    if need_safe:
        made = set()
        for ins in nodes:
            if not _cannot_error(ins, info, made):
                return None
            made.add(ins.dests[0])
    return nodes, leaves


def _pushdown_one(prog, k, info, defs, uses, order, new):
    """Try to move the filter IDX at prog[k] below the SORT / join it reads through.
    -> new program or None."""
    fi = prog[k]
    f, c = fi.dests[0], fi.srcs[0]
    if kind(c) != "reg":
        return None
    fuses = uses.get(f, [])
    if not fuses or any(u.op != "GATHER" or j != 1 for u, j in fuses):
        return None
    # what each use reads through f: GATHER(P, f) or GATHER(GATHER(x, P), f)
    through = []
    for u, _ in fuses:
        z = u.srcs[0]
        dz = defs.get(z)
        if dz is not None and dz.op in ("SORT", "HJOIN", "NLJOIN"):
            through.append((u, None, z))
        elif dz is not None and dz.op == "GATHER" and kind(dz.srcs[0]) == "reg":
            through.append((u, dz.srcs[0], dz.srcs[1]))
        else:
            return None
    src_ins = {id(defs[P]): defs[P] for _, _, P in through if P in defs}
    if len(src_ins) != 1 or len(through) != sum(P in defs for _, _, P in through):
        return None
    S = next(iter(src_ins.values()))
    block, Q = [], {}
    if S.op == "SORT":
        p = S.dests[0]
        tree = _pred_tree(c, p, info[p].into, defs, info, order, need_safe=False)
        if tree is None:
            return None
        nodes, leaves = tree
        keys = S.srcs
        kdom = {info[key_reg(t)].domain for t in keys if key_reg(t) in info}
        if len(kdom) != 1 or kdom != {info[p].into}:
            return None
    elif S.op in ("HJOIN", "NLJOIN") and S.dests[0] != S.dests[1]:
        li, ri = S.dests
        sides = []
        for side in (li, ri):
            t = _pred_tree(c, side, info[side].into, defs, info, order, need_safe=True)
            if t is not None and t[1]:
                sides.append((side, t))
        if len(sides) != 1:
            return None
        side, (nodes, leaves) = sides[0]
    else:
        return None
    if not leaves:
        return None
    # c0: the same predicate on the source rows
    sub = dict(leaves)
    for ins in nodes:
        d = new()
        block.append(Instr(ins.op, [d], [sub.get(t, t) if kind(t) == "reg" else t for t in ins.srcs]))
        sub[ins.dests[0]] = d
    c0 = sub[c]
    f0 = new()
    block.append(Instr("IDX", [f0], [c0]))
    if S.op == "SORT":
        nk = []
        for t in S.srcs:
            r = key_reg(t)
            g = new()
            block.append(Instr("GATHER", [g], [r, f0]))
            nk.append(g + t[len(r):])
        p2, q = new(), new()
        block.append(Instr("SORT", [p2], nk))
        block.append(Instr("GATHER", [q], [f0, p2]))
        Q[S.dests[0]] = q
    else:
        li, ri = S.dests
        lk, rk = S.srcs[0], S.srcs[1]
        g, l2, r2, back = new(), new(), new(), new()
        if side == li:
            block.append(Instr("GATHER", [g], [lk, f0]))
            block.append(Instr(S.op, [l2, r2], [g, rk] + S.srcs[2:]))
            block.append(Instr("GATHER", [back], [f0, l2]))
            Q[li], Q[ri] = back, r2
        else:
            block.append(Instr("GATHER", [g], [rk, f0]))
            block.append(Instr(S.op, [l2, r2], [lk, g] + S.srcs[2:]))
            block.append(Instr("GATHER", [back], [f0, r2]))
            Q[li], Q[ri] = l2, back
    repl = {}
    for u, x, P in through:
        if x is None:
            repl[id(u)] = ("sub", u.dests[0], Q[P])
        else:
            repl[id(u)] = ("gather", Instr("GATHER", u.dests, [x, Q[P]]))
    out, ren = [], {}
    for n, ins in enumerate(prog):
        r = repl.get(id(ins))
        if r is not None and r[0] == "sub":
            ren[r[1]] = r[2]
            continue
        if r is not None:
            ins = r[1]
        out.append(Instr(ins.op, ins.dests, [_rename(t, ren) for t in ins.srcs]))
        if n == k:
            out.extend(block)
    return out


def filter_pushdown(prog, schema=None):
    """Rule 5: filter before a SORT or a join instead of after it.

    IDX f, c, where c is element-wise in columns read through one SORT (or one side
    of a join), and every use of f is a GATHER through it. The filter moves to the
    source rows: f0 = IDX c0, with c0 the same predicate on the unsorted / unjoined
    rows; then the SORT (or join) runs on only the kept rows.
      SORT: a stable sort of the kept rows is the kept rows of the stable sort (ties
            stay in stored order either way); c0 sees exactly the rows c saw.
      join: pairs are ordered by left then right row, and filtering one side keeps
            that order. c0 also sees rows the join never matched, so only predicates
            that can't error on any row are moved (_cannot_error).
    Each rewrite is kept only if the program's estimated cost drops."""
    if schema is None:
        return prog, False
    info = analyze(prog, schema)
    defs, uses, new = _defs(prog), _uses(prog), _fresh(prog)
    order = {id(ins): n for n, ins in enumerate(prog)}
    before = None
    for k, ins in enumerate(prog):
        if ins.op != "IDX":
            continue
        cand = _pushdown_one(prog, k, info, defs, uses, order, new)
        if cand is None:
            continue
        cand, _ = dce(cse(cand)[0])
        try:
            if before is None:
                before = estimate(prog, schema, info)
            if estimate(cand, schema) < before:
                return cand, True
        except Exception:
            continue
    return prog, False


def _is_lookup(lk, rk, S):
    """True if every left key row matches exactly one right key row, by the schema:
    lk holds values of stored column L.c (any subset of L's rows), c is never NULL
    (key / not_null), and refs maps c to R.k, R's whole key; rk is R.k on all of R's
    rows (domain T:R). Then each left value is in R.k (refs) exactly once (key)."""
    if lk is None or rk is None or not lk.column or not rk.column or rk.kind != "col":
        return False
    lt, lc = lk.column.split(".", 1)
    rt, rc = rk.column.split(".", 1)
    if lc not in S.nn(lt) or rk.domain != "T:" + rt:
        return False
    refs = {k.lower(): v.lower() for k, v in S.table(lt).get("refs", {}).items()}
    key = [k.lower() for k in S.table(rt).get("key", [])]
    return refs.get(lc) == f"{rt}.{rc}" and key == [rc]


def lookup_join(prog, schema=None):
    """Rule 6: a join that is a lookup -> its left positions are 0..n-1.

    When _is_lookup holds, the pairs are (0, j0), (1, j1), ...: one per left row,
    in left order. So li is IOTA over the left keys; GATHER(x, li) then folds to x
    (rule 3), and if ri is unused the join itself dies (dce). No errors are added:
    refs requires comparable key types, so the join can't error either."""
    if schema is None:
        return prog, False
    from .analyze import Schema
    S, info, new, out, changed = Schema(schema), None, _fresh(prog), [], False
    defs, uses = _defs(prog), _uses(prog)
    for ins in prog:
        if ins.op in ("HJOIN", "NLJOIN") and ins.dests[0] != ins.dests[1] and len(ins.srcs) >= 2 \
                and all(kind(t) == "reg" for t in ins.srcs[:2]) and uses.get(ins.dests[0]) \
                and defs[ins.srcs[1]].op == "LOAD":   # rk exactly R.k as stored
            info = info or analyze(prog, schema)
            if _is_lookup(info.get(ins.srcs[0]), info.get(ins.srcs[1]), S):
                li, ri = ins.dests
                cand = out + [Instr(ins.op, [new(), ri], ins.srcs), Instr("IOTA", [li], [ins.srcs[0]])] \
                    + prog[len(out) + 1:]
                # keep it only if, after rule 3 folds GATHER(x, IOTA), the program is cheaper
                folded, _ = sorted_sort(cand, schema)
                folded, _ = dce(cse(folded)[0])
                try:
                    if estimate(folded, schema) < estimate(prog, schema, info):
                        return folded, True
                except Exception:
                    pass
        out.append(ins)
    return out, changed


def _bound(v, ty):
    """A check bound or literal -> comparable value for column type ty, or None."""
    from decimal import Decimal, InvalidOperation
    if v is None:
        return None
    s = str(v).strip()
    if ty == "DATE":
        s = s.strip("#")
        return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else None
    if ty in ("INT", "NUM"):
        try:
            return Decimal(s)
        except InvalidOperation:
            return None
    return None


def _decide(op, lo, hi, c):
    """Can 'v op c' be decided for every v in [lo, hi] (None = open side)?
    -> True / False / None."""
    ge_c = lo is not None and lo >= c          # every v >= c
    gt_c = lo is not None and lo > c
    le_c = hi is not None and hi <= c
    lt_c = hi is not None and hi < c
    if op == "GE":
        return True if ge_c else False if lt_c else None
    if op == "GT":
        return True if gt_c else False if le_c else None
    if op == "LE":
        return True if le_c else False if gt_c else None
    if op == "LT":
        return True if lt_c else False if ge_c else None
    if op in ("EQ", "NE"):
        never = gt_c or lt_c
        always = lo is not None and hi is not None and lo == hi == c
        r = False if never else True if always else None
        return r if r is None or op == "EQ" else not r
    return None


BOOL_MAKERS = {"EQ", "NE", "LT", "LE", "GT", "GE", "IS", "AND", "OR", "NOT", "ISNULL"}


def range_fold(prog, schema=None):
    """Rule 7: fold comparisons the schema decides, then the logic around them.

    'a op lit' -> FILL TRUE/FALSE when a is a stored column (any subset of its rows)
    that is never NULL (key / not_null) and its check [lo, hi] decides the comparison
    for every value. check alone isn't enough: it only bounds non-NULL values, and
    NULL op lit is NULL. A stored column against a comparable literal can't error, so
    nothing is lost. Then, with t / f a FILL TRUE / FALSE:
      IDX t -> IOTA (every position)        NOT t -> f, NOT f -> t
      AND x, t -> x   OR x, f -> x          (x made by a BOOL op: BOOL or NULL)
      AND x, f -> f   OR x, t -> t          (also x BOOL: three-valued tables)
    Constraints are true of every table set; stats are not used."""
    if schema is None:
        return prog, False
    from .analyze import Schema
    S, info = Schema(schema), analyze(prog, schema)
    defs, out, changed, sub = _defs(prog), [], False, {}

    def fill_of(t):
        d = defs.get(t)
        return d.srcs[0] if d is not None and d.op == "FILL" and d.srcs[0] in ("TRUE", "FALSE") else None

    def is_bool(t):
        d = defs.get(t)
        return d is not None and (d.op in BOOL_MAKERS or fill_of(t) is not None)

    for ins in prog:
        ins = Instr(ins.op, ins.dests, [_rename(t, sub) for t in ins.srcs])
        op, srcs = ins.op, ins.srcs
        new_ins = None
        if op in ("EQ", "NE", "LT", "LE", "GT", "GE") and len(srcs) == 2:
            a, c, o = srcs[0], srcs[1], op
            if kind(a) == "lit" and kind(c) == "reg":
                a, c, o = c, a, FLIP.get(op, op)
            r = info.get(a) if kind(a) == "reg" else None
            if r is not None and kind(c) == "lit" and r.column and r.kind == "col" and r.type in ("INT", "NUM", "DATE"):
                tab, col = r.column.split(".", 1)
                lt = lit_type(c)
                comparable = (lt == "DATE") if r.type == "DATE" else lt in ("INT", "NUM")
                checks = {k.lower(): v for k, v in S.table(tab).get("check", {}).items()}
                if comparable and col in S.nn(tab) and col in checks:
                    lo, hi = (_bound(x, r.type) for x in checks[col])
                    cv = _bound(c, r.type)
                    v = _decide(o, lo, hi, cv) if cv is not None else None
                    if v is not None:
                        new_ins = Instr("FILL", ins.dests, ["TRUE" if v else "FALSE", a])
        elif op == "IDX" and fill_of(srcs[0]) == "TRUE":
            new_ins = Instr("IOTA", ins.dests, [srcs[0]])
        elif op == "NOT" and fill_of(srcs[0]) is not None:
            new_ins = Instr("FILL", ins.dests, ["FALSE" if fill_of(srcs[0]) == "TRUE" else "TRUE", srcs[0]])
        elif op in ("AND", "OR") and len(srcs) == 2 and all(kind(t) == "reg" for t in srcs):
            for x, t in ((srcs[0], srcs[1]), (srcs[1], srcs[0])):
                fv = fill_of(t)
                if fv is None or not is_bool(x):
                    continue
                if (op, fv) in (("AND", "TRUE"), ("OR", "FALSE")):
                    sub[ins.dests[0]] = x
                    new_ins = "drop"
                else:
                    new_ins = Instr("FILL", ins.dests, [fv, x])
                break
        if new_ins is None:
            out.append(ins)
            continue
        changed = True
        if new_ins != "drop":
            out.append(new_ins)
            defs[ins.dests[0]] = new_ins
    return out, changed


def sort_slice_topk(prog, schema=None):
    """Rule 8: SORT + SLICE -> TOPK.

    a) SLICE(GATHER(x, i), n) -> GATHER(x, SLICE(i, n)): both are the first n of
       x[i[k]]; the new form reads fewer entries of i, so it only drops errors.
    b) SLICE(SORT(keys), n) -> TOPK(n, keys): TOPK is defined as the first n
       positions of the order SORT gives for the same keys (docs/instructions/
       sorting.md), ties included. Kept only if the estimated cost drops (the SORT
       may still be needed elsewhere)."""
    if schema is None:
        return prog, False
    defs, new, out, changed = _defs(prog), _fresh(prog), [], False
    for ins in prog:
        if ins.op == "SLICE" and kind(ins.srcs[0]) == "reg":
            d = defs.get(ins.srcs[0])
            if d is not None and d.op == "GATHER" and all(kind(t) == "reg" for t in d.srcs) \
                    and getattr(defs.get(d.srcs[1]), "op", None) == "SORT":   # only to expose (b)
                t = new()
                out.append(Instr("SLICE", [t], [d.srcs[1], ins.srcs[1]]))
                out.append(Instr("GATHER", ins.dests, [d.srcs[0], t]))
                changed = True
                continue
        out.append(ins)
    if changed:
        return out, True
    for k, ins in enumerate(prog):
        if ins.op == "SLICE" and kind(ins.srcs[0]) == "reg":
            d = defs.get(ins.srcs[0])
            if d is not None and d.op == "SORT" and re.match(r"^\d+$", ins.srcs[1]) and int(ins.srcs[1]) >= 1:
                cand = prog[:k] + [Instr("TOPK", ins.dests, [ins.srcs[1]] + d.srcs)] + prog[k + 1:]
                cand, _ = dce(cand)
                try:
                    if estimate(cand, schema) < estimate(prog, schema):
                        return cand, True
                except Exception:
                    pass
    return prog, False


# Element-wise ops whose result is NULL exactly when an operand is NULL: every op on
# the arithmetic, strings and dates pages, plus the comparisons and NOT
# (docs/instructions/README.md#element-wise-instructions). Logic ops with their own
# NULL rules are left out.
NULL_IN_NULL_OUT = ELEMENTWISE - {"IS", "ISNULL", "NVL", "IF", "NULLIF", "NULLIFE", "AND", "OR"}


def idx_tautology(prog, schema=None):
    """Rule 9: OR(x, NOT x) read only by IDX -> NOT ISNULL(x).

    For a BOOL x, OR(x, NOT x) is TRUE when x is TRUE or FALSE and NULL when x is
    NULL (three-valued logic, docs/instructions/logic.md#and-or). NOT ISNULL(x) is
    TRUE / TRUE / FALSE. IDX keeps only TRUE positions and drops FALSE and NULL alike
    (columns.md#idx), so both select the same rows. Only when every use is an IDX:
    elsewhere NULL and FALSE differ. A non-BOOL x made the original error; dropping
    an error is allowed."""
    defs, uses, new, out, changed = _defs(prog), _uses(prog), _fresh(prog), [], False

    def negates(n, x):
        d = defs.get(n)
        return d is not None and d.op == "NOT" and d.srcs == [x]

    for ins in prog:
        if ins.op == "OR" and len(ins.srcs) == 2 and all(kind(t) == "reg" for t in ins.srcs):
            a, b = ins.srcs
            x = a if negates(b, a) else b if negates(a, b) else None
            us = uses.get(ins.dests[0], [])
            if x is not None and us and all(u.op == "IDX" and k == 0 for u, k in us):
                t = new()
                out.append(Instr("ISNULL", [t], [x]))
                out.append(Instr("NOT", ins.dests, [t]))
                changed = True
                continue
        out.append(ins)
    return out, changed


def isnull_push(prog, schema=None):
    """Rule 10: ISNULL(E(a, lits...)) -> ISNULL(a), for E in NULL_IN_NULL_OUT with one
    register operand and only non-NULL literals.

    E is NULL exactly where a is NULL; elsewhere it gives a value or errors. So
    ISNULL(E(...)) and ISNULL(a) agree on every row E doesn't error on, and dropping
    E can only remove errors. E then dies (dce) if nothing else reads it."""
    defs, out, changed = _defs(prog), [], False
    for ins in prog:
        if ins.op == "ISNULL" and kind(ins.srcs[0]) == "reg":
            d = defs.get(ins.srcs[0])
            if d is not None and d.op in NULL_IN_NULL_OUT and len(d.dests) == 1:
                regs = [t for t in d.srcs if kind(t) == "reg"]
                if len(regs) == 1 and all(t != "NULL" for t in d.srcs):
                    out.append(Instr("ISNULL", ins.dests, regs))
                    changed = True
                    continue
        out.append(ins)
    return out, changed


# cheap clean-up first, so the analysis-based rules see a smaller program
PASSES = [cse, dce, gather_chain, filter_first, sorted_sort, pointless, filter_pushdown, range_fold,
          sort_slice_topk, idx_tautology, isnull_push]
# second phase: lookup joins rewrite the gathers that filter pushdown matches on,
# so they run only once the first phase has settled
LATE_PASSES = PASSES + [lookup_join]


def run(prog, schema=None, deadline=None):
    """Apply PASSES until none changes anything, then LATE_PASSES the same way
    (or stop at the deadline: every pass output is a correct program)."""
    import time
    for passes in (PASSES, LATE_PASSES):
        for _ in range(50):
            changed = False
            for p in passes:
                if deadline and time.monotonic() > deadline:
                    return prog
                prog, c = p(prog, schema)
                changed |= c
            if not changed:
                break
    return prog
