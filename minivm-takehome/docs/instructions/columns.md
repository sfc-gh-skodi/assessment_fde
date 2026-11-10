[MiniVM docs](../README.md) › [Instructions](README.md) › Columns

# Column instructions

These instructions load table columns, build columns, select and reorder values by position, and produce the program's result. They are not element-wise. Positions are 0-based INT values ([notation](README.md#notation)).

| Instruction | Result |
|---|---|
| [`LOAD d, table.column`](#load) | the column as stored |
| [`FILL d, lit, s`](#fill) | `lit` repeated once per value of `s` |
| [`IOTA d, s`](#iota) | positions `0 .. len(s)-1` |
| [`IDX d, s`](#idx) | positions where `s` is TRUE |
| [`GATHER d, s, i`](#gather) | `d[k] = s[i[k]]` |
| [`SLICE d, s, n`](#slice) | the first `n` values of `s` |
| [`OUT s, ...`](#out) | the program's result |

## `LOAD`

```text
LOAD d, table.column
```

Sets `d` to the column `column` of table `table` as stored. An empty string stays `''`; it is not NULL.

**Cycles:** 1 per value produced.

## `FILL`

```text
FILL d, lit, s
```

Sets `d` to the literal `lit` repeated once per value of `s`. `lit` must be a literal.

**Cycles:** 1 per value produced.

## `IOTA`

```text
IOTA d, s
```

Sets `d` to the positions `0 .. len(s)-1` of `s`.

**Cycles:** 1 per value produced.

## `IDX`

```text
IDX d, s
```

Sets `d` to the positions, in order, where the BOOL column `s` is TRUE. FALSE and NULL positions are left out.

**Cycles:** 1 per input value.

## `GATHER`

```text
GATHER d, s, i
```

Sets `d[k] = s[i[k]]` for every position `k` of `i`; `d` has the length of `i`. Every index must be an INT in range for `s`, or the instruction is an error. Use it with the positions from [`IDX`](#idx), [`SORT`](sorting.md#sort), [`TOPK`](sorting.md#topk), the [joins](joins.md#nljoin-hjoin) and [`GFIRST`](grouping.md#gfirst) to filter, reorder, pair up or pick rows.

**Cycles:** 1 per value produced.

## `SLICE`

```text
SLICE d, s, n
```

Sets `d` to the first `n` values of `s` (all of `s` if it has fewer). `n` is an integer literal.

**Cycles:** 1 per value produced.

## `OUT`

```text
OUT s, ...
```

Produces the program's result: one column per operand, all the same length. `OUT` must be the last instruction and the program's only `OUT` ([program rules](../running.md#program-rules)).

**Cycles:** nothing beyond the base cost.
