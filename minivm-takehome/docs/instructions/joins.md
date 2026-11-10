[MiniVM docs](../README.md) › [Instructions](README.md) › Joins

# Join instructions

`NLJOIN` and `HJOIN` pair up the rows of two key columns whose keys are equal and return the pairs as two position columns. Positions are 0-based INT values ([notation](README.md#notation)).

| Instruction | Result |
|---|---|
| [`NLJOIN li, ri, lk, rk [, NULLEQ]`](#nljoin-hjoin) | positions of all pairs with `lk[i] = rk[j]` |
| [`HJOIN li, ri, lk, rk [, NULLEQ]`](#nljoin-hjoin) | same result as `NLJOIN` |

## `NLJOIN`, `HJOIN`

```text
NLJOIN li, ri, lk, rk [, NULLEQ]
HJOIN  li, ri, lk, rk [, NULLEQ]
```

Finds all pairs `(i, j)` with `lk[i] = rk[j]`, ordered by `i` then `j`. Sets `li` to the positions into `lk` and `ri` to the positions into `rk`, one entry per pair; if `li` and `ri` are the same register, it holds the positions into `rk`. Keys are compared as in [Ordering](../values.md#ordering): a non-NULL left key that can't be compared with a non-NULL right key (e.g. STR with INT) is an error. A NULL key matches no key, unless the optional `NULLEQ` flag is given, in which case NULL keys match each other. `HJOIN` gives the same result as `NLJOIN`, errors included; only the cost differs.

**Cycles (`NLJOIN`):** per pair of rows: 1 plus the bytes of the shorter string key ([rules](../cycles.md#string-bytes)); plus 2 per output pair.

**Cycles (`HJOIN`):** per row of either side: 6 plus its key's string bytes ([rules](../cycles.md#string-bytes)); plus 2 per output pair.

### Example

[`GATHER`](columns.md#gather) through `li` picks columns of the left rows and through `ri` columns of the right rows, giving one row per pair. Customers with their region's name:

```text
LOAD   reg, customers.c_region
LOAD   code, regions.r_code
HJOIN  li, ri, reg, code
LOAD   cname, customers.c_name
LOAD   rname, regions.r_name
GATHER c, cname, li
GATHER r, rname, ri
OUT    c, r
```

On `examples/data.json` this prints `[["Cy","Southern"],["Dee","West Coast"],["Eve","Southern"], ...]`.
