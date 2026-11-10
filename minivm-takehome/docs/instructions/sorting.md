[MiniVM docs](../README.md) › [Instructions](README.md) › Sorting

# Sorting instructions

`SORT` and `TOPK` order the rows of one or more key columns and return positions, which [`GATHER`](columns.md#gather) applies to any column of the same rows. Positions are 0-based INT values ([notation](README.md#notation)).

| Instruction | Result |
|---|---|
| [`SORT d, key, ...`](#sort) | positions of the rows in stable sorted order |
| [`TOPK d, n, key, ...`](#topk) | the first `n` positions of the same order |

## `SORT`

```text
SORT d, key, ...
```

Sets `d` to the positions of the rows in stable sorted order by the [sort keys](#sort-keys).

**Cycles:** 2 per row, plus every comparison of a stable top-down merge sort ([comparison cost](../cycles.md#comparisons)).

## `TOPK`

```text
TOPK d, n, key, ...
```

Sets `d` to the first `n` positions of the order `SORT` would produce for the same keys (all of them if there are fewer rows). `n` is an integer literal.

**Cycles:** 2 per row, plus every comparison of a bounded insertion buffer (each row is compared with the current `n`-th, then placed by binary search) ([comparison cost](../cycles.md#comparisons)), plus 1 per buffered row shifted.

## Sort keys

```text
reg ASC|DESC NF|NL
```

A sort key is a register followed by a direction and a NULL placement, separated by spaces or tabs; all three parts are required. All key columns must have the same length. Rows are ordered by the first key, then by each following key among rows the earlier keys leave equal.

- `ASC` orders values from least to greatest, `DESC` reverses the order of values. Values are compared as in [Ordering](../values.md#ordering).
- `NF` puts NULLs first and `NL` puts them last, whatever the direction.
- Ties keep their input order.

Customers by credit, highest first with NULLs last, then by name:

```text
LOAD   name, customers.c_name
LOAD   credit, customers.c_credit
SORT   p, credit DESC NL, name ASC NF
GATHER n, name, p
GATHER c, credit, p
OUT    n, c
```
