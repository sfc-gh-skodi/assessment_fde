[MiniVM docs](../README.md) › [Instructions](README.md) › Grouping

# Grouping instructions

`GROUP` and `GALL` divide rows into groups and store them as a group set; the other instructions on this page read a group set and return columns. Positions are 0-based INT values ([notation](README.md#notation)).

| Instruction | Result |
|---|---|
| [`GROUP g, k, ...`](#group) | group set: rows with equal keys share a group |
| [`GALL g, s`](#gall) | group set: one group holding every row of `s` |
| [`GID d, g`](#gid) | group number of each row |
| [`GFIRST d, g`](#gfirst) | position of each group's first row |
| [`GCOUNT d, g`](#gcount) | rows per group |
| [`GCOUNTV d, g, s`](#gcountv) | non-NULL values of `s` per group |
| [`GSUM d, g, s`](#gsum) | sum of non-NULL values per group |
| [`GMIN d, g, s` / `GMAX`](#gmin-gmax) | least / greatest non-NULL value per group |

## Group sets

A register holds either a column or a group set ([values](../values.md#columns-and-group-sets)). A group set assigns each of its rows a group number; groups are numbered from 0 in order of first appearance. [`GROUP`](#group) and [`GALL`](#gall) produce a group set. [`GID`](#gid) returns a column with one value per row; the aggregates [`GFIRST`](#gfirst) through [`GMAX`](#gmin-gmax) return a column with one value per group, the value for group `k` at position `k`. The `s` operand of an aggregate is a column over the same rows as the group set; a different length is an error.

Aggregate columns of the same group set line up with each other. To label each group with its key, gather the key at [`GFIRST`](#gfirst). Orders per status:

```text
LOAD   st, orders.o_status
GROUP  g, st
GFIRST f, g
GATHER key, st, f
GCOUNT n, g
OUT    key, n
```

On `examples/data.json` this prints `[["open",7],["closed",12],["shipped",11]]`.

## `GROUP`

```text
GROUP g, k, ...
```

Sets `g` to a group set over the rows of the key columns `k, ...`: rows with equal keys share a group, and NULL equals NULL. All key columns must have the same length. Keys are compared as in [Ordering](../values.md#ordering): INT and NUM mix (`1` and `1.00` share a group), and a key column holding values that can't be compared (e.g. STR and INT) is an error.

**Cycles:** per row: 6 plus the string bytes of its keys ([rules](../cycles.md#string-bytes)).

## `GALL`

```text
GALL g, s
```

Sets `g` to a group set with one group holding every row of `s`, even when `s` is empty.

**Cycles:** 1 per row.

## `GID`

```text
GID d, g
```

Sets `d` to the group number of each row of `g`.

**Cycles:** 1 per row.

## `GFIRST`

```text
GFIRST d, g
```

Sets `d` to the position of each group's first row. The result is NULL for the group of an empty `GALL`.

**Cycles:** 1 per row.

## `GCOUNT`

```text
GCOUNT d, g
```

Sets `d` to the number of rows in each group.

**Cycles:** 2 per row.

## `GCOUNTV`

```text
GCOUNTV d, g, s
```

Sets `d` to the number of non-NULL values of `s` in each group.

**Cycles:** 2 per row.

## `GSUM`

```text
GSUM d, g, s
```

Sets `d` to the sum of the non-NULL values of `s` in each group: INT when all are INT, else NUM. The result is NULL for a group with no non-NULL values. A NUM sum is computed exactly, with as many digits after the point as the value with the most, and rounded once as in [NUM range](../values.md#num-range), so it doesn't depend on the order of the rows. Only each group's total is checked: a total outside the INT or NUM range is the error `numeric overflow`, whatever the running sums along the way.

**Cycles:** 2 per row.

## `GMIN`, `GMAX`

```text
GMIN d, g, s
GMAX d, g, s
```

Sets `d` to the least (`GMIN`) or greatest (`GMAX`) non-NULL value of `s` in each group, the first of equals: of `1`, `1.0` and `1.00`, whichever comes first. Values are compared as in [Ordering](../values.md#ordering). The result is NULL for a group with no non-NULL values.

**Cycles:** 2 per row, plus the bytes of each non-NULL string ([rules](../cycles.md#string-bytes)).
