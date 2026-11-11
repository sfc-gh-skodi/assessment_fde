"""Step 1 (parse -> SSA IR) and step 5 (emit).

An Instr has: op (upper case), dests (registers it defines), srcs (operand tokens).
Operand tokens are kept as text; `kind(tok)` classifies them:
  'reg'  register            'lit' literal (42, 1.50, 'x', #2024-01-31#, NULL, TRUE)
  'col'  table.column        'key' sort key "reg ASC NL"      'flag' NULLEQ
In SSA form every register is defined exactly once (overwrites get a fresh name),
so later passes can treat a register name as "this one value".
"""
import re

KEYWORDS = {"NULL", "TRUE", "FALSE", "ASC", "DESC", "NF", "NL", "NULLEQ"}
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
# opcodes whose 2nd/3rd... operands are integer literals, not registers
INT_OPERANDS = {"LEFT": (2,), "SUBSTR": (2, 3), "SLICE": (2,), "TOPK": (1,), "DATEADD": ()}


class Instr:
    __slots__ = ("op", "dests", "srcs")

    def __init__(self, op, dests, srcs):
        self.op, self.dests, self.srcs = op, list(dests), list(srcs)

    def regs_used(self):
        return [key_reg(t) for t in self.srcs if kind(t) in ("reg", "key")]

    def __repr__(self):
        return f"{self.op} {', '.join(self.dests + self.srcs)}"


def kind(tok):
    t = tok.strip()
    if t[:1] in ("'", "#"):
        return "lit"
    if " " in t or "\t" in t:
        return "key"
    if t.upper() == "NULLEQ":
        return "flag"
    if t.upper() in KEYWORDS or re.match(r"-?\d", t):
        return "lit"
    if "." in t:
        return "col"
    return "reg" if IDENT.match(t) else "lit"


def key_reg(tok):
    return tok.split()[0]


def _split_line(line):
    code, q = [], False
    for ch in line:
        if ch == "'":
            q = not q
        if ch == ";" and not q:
            break
        code.append(ch)
    code = "".join(code).strip()
    if not code:
        return None
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
    return parts[0].upper(), ops


def _ndests(op, ops):
    if op == "OUT":
        return 0
    if op in ("HJOIN", "NLJOIN"):
        return 2
    return 1


def parse(text):
    """Program text -> list of Instr (original register names)."""
    prog = []
    for line in text.splitlines():
        s = _split_line(line)
        if s is None:
            continue
        op, ops = s
        nd = _ndests(op, ops)
        srcs = []
        for k, t in enumerate(ops[nd:], start=1):
            if k in INT_OPERANDS.get(op, ()):
                srcs.append(t)            # integer literal operand
            elif kind(t) == "key":       # normalise "r  asc   nl" -> "r ASC NL"
                p = t.split()
                srcs.append(" ".join([p[0]] + [x.upper() for x in p[1:]]))
            elif kind(t) == "lit" and t.upper() in KEYWORDS:
                srcs.append(t.upper())
            else:
                srcs.append(t)
        prog.append(Instr(op, ops[:nd], srcs))
    if not prog or prog[-1].op != "OUT" or sum(i.op == "OUT" for i in prog) != 1:
        raise ValueError("program must end with its only OUT")
    return prog


def to_ssa(prog):
    """Rename so each register is defined once. HJOIN a,a,... (same register twice)
    keeps both dests equal. Reading an unset register raises (the input would error)."""
    cur, count, out = {}, {}, []
    taken = {d for ins in prog for d in ins.dests}

    def use(tok):
        r = key_reg(tok)
        if r not in cur:
            raise ValueError(f"register {r} read before set")
        return tok.replace(r, cur[r], 1)

    def define(r):
        n = count.get(r, 0)
        name = r
        while n > 0:
            name = f"{r}_{n}"
            if name not in taken:
                break
            n += 1
        count[r] = n + 1
        taken.add(name)
        cur[r] = name
        return name

    for ins in prog:
        srcs = [use(t) if kind(t) in ("reg", "key") and i + 1 not in INT_OPERANDS.get(ins.op, ()) else t
                for i, t in enumerate(ins.srcs)]
        if len(ins.dests) == 2 and ins.dests[0] == ins.dests[1]:
            d = define(ins.dests[0])
            dests = [d, d]
        else:
            dests = [define(d) for d in ins.dests]
        out.append(Instr(ins.op, dests, srcs))
    return out


def emit(prog):
    lines = []
    for ins in prog:
        args = ins.dests + ins.srcs
        lines.append(f"{ins.op:<7} {', '.join(args)}".rstrip())
    return "\n".join(lines) + "\n"
