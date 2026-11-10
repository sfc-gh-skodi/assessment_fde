[MiniVM docs](README.md) › Cycles

# Cycles

This page defines how many cycles a program costs. A program's cost is the sum
of its instructions' costs, and `bin/minivm` reports it as `cycles`
([Running](running.md#command-line)).

## Base cost

Every instruction costs 4, plus the cost given for it in the
[cost table](#cost-table). `OUT` costs only the 4.

A run is stopped with an error if it does too much work; see the
[work limit](running.md#program-rules).

## String bytes

The string bytes of a value are the number of bytes in it if it is a STR, and
0 otherwise (including `NULL`).

An [element-wise instruction](instructions/README.md#element-wise-instructions)
costs, for each element of its result, a base amount plus string bytes:

| Instructions | Base per element |
|---|---|
| `DIV` `IDIV` `MOD` | 6 |
| `TRUNC` `YEAR` `MONTH` `DAY` `DOW` `DATEADD` `DATEDIFF` | 2 |
| every other element-wise instruction | 1 |

| Instructions | String bytes per element |
|---|---|
| comparisons: `EQ` `NE` `LT` `LE` `GT` `GE` `IS` | the bytes of the shorter operand |
| `LEN` | the bytes of its operand |
| `ISNULL` `NVL` `IF` `NULLIF` `NULLIFE` | nothing |
| every other element-wise instruction | 1 per byte of each string operand (literals included) and of its result |

A literal operand counts at every element, like the value it stands for.

## Comparisons

`SORT` and `TOPK` compare rows on their sort keys
([sort keys](instructions/sorting.md#sort-keys)). One comparison of two rows
costs, for each key examined until one differs, 2 plus the bytes of the
shorter string.

For example, on a table `t` whose STR column `s` and INT column `n` hold the
rows `('ab', 5)` and `('ab', 7)`, comparing the two rows on keys
`s ASC NL, n ASC NL` costs 2 + 2 for the first key, which is equal, and 2 + 0
for the second, which differs: 6 in all. Sorting the two rows takes that one
comparison:

```text
LOAD s, t.s
LOAD n, t.n
SORT o, s ASC NL, n ASC NL
OUT  o
```

costs (4 + 2) + (4 + 2) + (4 + 2 x 2 rows + 6) + 4 = 30 cycles.

## Cost table

Cycles beyond the base 4 of each instruction:

| Instruction | Cycles |
|---|---|
| [`ADD`](instructions/arithmetic.md#add-sub-mul) [`SUB`](instructions/arithmetic.md#add-sub-mul) [`MUL`](instructions/arithmetic.md#add-sub-mul) [`NEG`](instructions/arithmetic.md#neg) [`WRAP`](instructions/arithmetic.md#wrap) | 1 per element, plus 1 per byte of each string operand (literals included) and of its result |
| [`DIV`](instructions/arithmetic.md#div) [`IDIV`](instructions/arithmetic.md#idiv) [`MOD`](instructions/arithmetic.md#mod) | 6 per element, plus 1 per byte of each string operand (literals included) and of its result |
| [`TRUNC`](instructions/arithmetic.md#trunc) | 2 per element, plus 1 per byte of each string operand (literals included) and of its result |
| [`EQ`](instructions/logic.md#eq-ne-lt-le-gt-ge) [`NE`](instructions/logic.md#eq-ne-lt-le-gt-ge) [`LT`](instructions/logic.md#eq-ne-lt-le-gt-ge) [`LE`](instructions/logic.md#eq-ne-lt-le-gt-ge) [`GT`](instructions/logic.md#eq-ne-lt-le-gt-ge) [`GE`](instructions/logic.md#eq-ne-lt-le-gt-ge) [`IS`](instructions/logic.md#is) | 1 per element, plus the bytes of the shorter operand |
| [`AND`](instructions/logic.md#and-or) [`OR`](instructions/logic.md#and-or) [`NOT`](instructions/logic.md#not) | 1 per element, plus 1 per byte of each string operand (literals included) and of its result |
| [`ISNULL`](instructions/logic.md#isnull) [`NVL`](instructions/logic.md#nvl) [`IF`](instructions/logic.md#if) [`NULLIF`](instructions/logic.md#nullif) [`NULLIFE`](instructions/logic.md#nullife) | 1 per element |
| [`UPPER`](instructions/strings.md#upper) [`RTRIM`](instructions/strings.md#rtrim-trim) [`TRIM`](instructions/strings.md#rtrim-trim) [`LEFT`](instructions/strings.md#left) [`SUBSTR`](instructions/strings.md#substr) [`CAT`](instructions/strings.md#cat) | 1 per element, plus 1 per byte of each string operand (literals included) and of its result |
| [`LEN`](instructions/strings.md#len) | 1 per element, plus the bytes of its operand |
| [`YEAR`](instructions/dates.md#year-month-day) [`MONTH`](instructions/dates.md#year-month-day) [`DAY`](instructions/dates.md#year-month-day) [`DOW`](instructions/dates.md#dow) [`DATEADD`](instructions/dates.md#dateadd) [`DATEDIFF`](instructions/dates.md#datediff) | 2 per element, plus 1 per byte of each string operand (literals included) and of its result |
| [`LOAD`](instructions/columns.md#load) [`FILL`](instructions/columns.md#fill) [`IOTA`](instructions/columns.md#iota) [`GATHER`](instructions/columns.md#gather) [`SLICE`](instructions/columns.md#slice) | 1 per value produced |
| [`IDX`](instructions/columns.md#idx) | 1 per input value |
| [`SORT`](instructions/sorting.md#sort) | 2 per row, plus every [comparison](#comparisons) of a stable top-down merge sort |
| [`TOPK`](instructions/sorting.md#topk) | 2 per row, plus every [comparison](#comparisons) of a bounded insertion buffer (each row is compared with the current `n`-th, then placed by binary search), plus 1 per buffered row shifted |
| [`NLJOIN`](instructions/joins.md#nljoin-hjoin) | per pair of rows: 1 plus the bytes of the shorter string key; plus 2 per output pair |
| [`HJOIN`](instructions/joins.md#nljoin-hjoin) | per row of either side: 6 plus its key's string bytes; plus 2 per output pair |
| [`GROUP`](instructions/grouping.md#group) | per row: 6 plus the string bytes of its keys |
| [`GALL`](instructions/grouping.md#gall) [`GID`](instructions/grouping.md#gid) [`GFIRST`](instructions/grouping.md#gfirst) | 1 per row |
| [`GCOUNT`](instructions/grouping.md#gcount) [`GCOUNTV`](instructions/grouping.md#gcountv) [`GSUM`](instructions/grouping.md#gsum) | 2 per row |
| [`GMIN`](instructions/grouping.md#gmin-gmax) [`GMAX`](instructions/grouping.md#gmin-gmax) | 2 per row, plus the bytes of each non-NULL string |
| [`OUT`](instructions/columns.md#out) | nothing |

## Example

On a table `t` whose STR column `s` holds `'ab'`, `'cde'`, `NULL`:

```text
LOAD  x, t.s
UPPER u, x
EQ    e, u, 'AB'
OUT   e
```

| Instruction | Cost | Cycles |
|---|---|---|
| `LOAD x, t.s` | 4 + 3 values | 7 |
| `UPPER u, x` | 4 + (1 + 2 + 2) + (1 + 3 + 3) + (1 + 0 + 0) | 17 |
| `EQ e, u, 'AB'` | 4 + (1 + 2) + (1 + 2) + (1 + 0) | 11 |
| `OUT e` | 4 | 4 |
| total | | 39 |

`UPPER` pays for the bytes of its operand and of its result; `EQ` pays for the
shorter of `u` and the literal `'AB'` at each row. `bin/minivm` prints
`{"ncols":1,"rows":[[true],[false],[null]],"cycles":39}`.
