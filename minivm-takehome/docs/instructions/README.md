[MiniVM docs](../README.md) › Instructions

# Instructions

This page states the conventions shared by all instructions and indexes every opcode. Cycle costs are summarized in [Cycles](../cycles.md).

## Notation

Each instruction is shown as `OP` followed by its operands:

- `d` is the destination register (`li`, `ri` for joins, `g` for group sets).
- `a`, `b`, `c`, `s`, `x`, `y` are source operands: `c` is a condition, `s` usually a string or source column, `x` and `y` dates.
- `n`, `start` and `len` are integer literals; `lit` is a literal.
- `i` is a column of positions, `g` a group set, `key` a [sort key](sorting.md#sort-keys), `table.column` a stored column.

Where an element-wise instruction takes a register operand, a literal may be used instead; it stands for that value at every row ([literals](../language.md#literals)).

Positions are 0-based INT values.

An operand that expects a column can't name a group set, and the reverse; either
is an error, as is reading a register that hasn't been set.

## Element-wise instructions

The instructions on the [arithmetic](arithmetic.md), [logic](logic.md), [strings](strings.md) and [dates](dates.md) pages compute one result value per row:

- All register operands must have the same length, which is the result's length.
- At least one operand must be a register.
- Unless noted, the result is `NULL` when any operand is `NULL`. That comes first: `DIV` of NULL by 0 is NULL, not division by zero, and `ADD` of NULL and a STR is NULL, not a type error.
- Types are checked row by row: an operand of the wrong type is an error only at a row where the instruction uses it, so whether a program fails can depend on its data. An empty column, or one of NULLs, never gives a type error.

Given a table `t` whose INT column `x` holds `1`, `NULL`, `3`:

```text
LOAD  x, t.x
ADD   y, x, 10      ; the literal 10 stands for 10 at every row
OUT   y
```

prints `{"ncols":1,"rows":[[11],[null],[13]],"cycles":18}`.

## Index

### Arithmetic

| Instruction | Summary |
|---|---|
| [`ADD`](arithmetic.md#add-sub-mul) | sum |
| [`SUB`](arithmetic.md#add-sub-mul) | difference |
| [`MUL`](arithmetic.md#add-sub-mul) | product |
| [`DIV`](arithmetic.md#div) | NUM quotient |
| [`IDIV`](arithmetic.md#idiv) | INT quotient truncated toward zero |
| [`MOD`](arithmetic.md#mod) | INT remainder with the sign of `a` |
| [`NEG`](arithmetic.md#neg) | negation |
| [`WRAP`](arithmetic.md#wrap) | INT wrapped to 32-bit two's complement |
| [`TRUNC`](arithmetic.md#trunc) | NUM truncated toward zero to INT |

### Logic

| Instruction | Summary |
|---|---|
| [`EQ`](logic.md#eq-ne-lt-le-gt-ge) | equal |
| [`NE`](logic.md#eq-ne-lt-le-gt-ge) | not equal |
| [`LT`](logic.md#eq-ne-lt-le-gt-ge) | less than |
| [`LE`](logic.md#eq-ne-lt-le-gt-ge) | less than or equal |
| [`GT`](logic.md#eq-ne-lt-le-gt-ge) | greater than |
| [`GE`](logic.md#eq-ne-lt-le-gt-ge) | greater than or equal |
| [`IS`](logic.md#is) | equal, or both NULL; never NULL |
| [`AND`](logic.md#and-or) | three-valued conjunction |
| [`OR`](logic.md#and-or) | three-valued disjunction |
| [`NOT`](logic.md#not) | BOOL negation |
| [`ISNULL`](logic.md#isnull) | whether the value is NULL |
| [`NVL`](logic.md#nvl) | `a`, or `b` when `a` is NULL |
| [`IF`](logic.md#if) | `a` where `c` is TRUE, else `b` |
| [`NULLIF`](logic.md#nullif) | NULL where `a IS b`, else `a` |
| [`NULLIFE`](logic.md#nullife) | NULL where `a` is the empty string, else `a` |

### Strings

| Instruction | Summary |
|---|---|
| [`UPPER`](strings.md#upper) | upper case |
| [`RTRIM`](strings.md#rtrim-trim) | without trailing spaces |
| [`TRIM`](strings.md#rtrim-trim) | without leading and trailing spaces |
| [`LEFT`](strings.md#left) | first `n` characters |
| [`SUBSTR`](strings.md#substr) | `len` characters from 1-based `start` |
| [`LEN`](strings.md#len) | number of characters |
| [`CAT`](strings.md#cat) | concatenation |

### Dates

| Instruction | Summary |
|---|---|
| [`YEAR`](dates.md#year-month-day) | year |
| [`MONTH`](dates.md#year-month-day) | month |
| [`DAY`](dates.md#year-month-day) | day of month |
| [`DOW`](dates.md#dow) | day of week, 1 = Monday ... 7 = Sunday |
| [`DATEADD`](dates.md#dateadd) | date plus `n` days |
| [`DATEDIFF`](dates.md#datediff) | days from `y` to `x` |

### Columns

| Instruction | Summary |
|---|---|
| [`LOAD`](columns.md#load) | a stored column |
| [`FILL`](columns.md#fill) | a literal repeated once per value of `s` |
| [`IOTA`](columns.md#iota) | positions `0 .. len(s)-1` |
| [`IDX`](columns.md#idx) | positions where a BOOL column is TRUE |
| [`GATHER`](columns.md#gather) | `d[k] = s[i[k]]` |
| [`SLICE`](columns.md#slice) | the first `n` values |
| [`OUT`](columns.md#out) | the program's result |

### Sorting

| Instruction | Summary |
|---|---|
| [`SORT`](sorting.md#sort) | positions of the rows in stable sorted order |
| [`TOPK`](sorting.md#topk) | the first `n` positions of that order |

Sort keys are described in [Sort keys](sorting.md#sort-keys).

### Joins

| Instruction | Summary |
|---|---|
| [`NLJOIN`](joins.md#nljoin-hjoin) | positions of all pairs with equal keys |
| [`HJOIN`](joins.md#nljoin-hjoin) | same result as `NLJOIN` |

### Grouping

| Instruction | Summary |
|---|---|
| [`GROUP`](grouping.md#group) | group set of rows with equal keys |
| [`GALL`](grouping.md#gall) | one group holding every row |
| [`GID`](grouping.md#gid) | group number of each row |
| [`GFIRST`](grouping.md#gfirst) | position of each group's first row |
| [`GCOUNT`](grouping.md#gcount) | rows per group |
| [`GCOUNTV`](grouping.md#gcountv) | non-NULL values per group |
| [`GSUM`](grouping.md#gsum) | sum of non-NULL values per group |
| [`GMIN`](grouping.md#gmin-gmax) | least non-NULL value per group |
| [`GMAX`](grouping.md#gmin-gmax) | greatest non-NULL value per group |
