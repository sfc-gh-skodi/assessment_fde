[MiniVM docs](../README.md) › [Instructions](README.md) › Logic

# Logic

Element-wise comparisons, BOOL logic and NULL handling. All instructions on this page follow the [element-wise rules](README.md#element-wise-instructions); where an instruction's NULL behavior differs from the default (the result is `NULL` when any operand is `NULL`), its section says so.

| Instruction | Result |
|---|---|
| [`EQ` `NE` `LT` `LE` `GT` `GE` `d, a, b`](#eq-ne-lt-le-gt-ge) | BOOL comparison |
| [`IS d, a, b`](#is) | BOOL, never NULL: equal, or both NULL |
| [`AND d, a, b`](#and-or) / `OR` | three-valued logic |
| [`NOT d, a`](#not) | BOOL negation |
| [`ISNULL d, a`](#isnull) | BOOL, never NULL |
| [`NVL d, a, b`](#nvl) | `a`, or `b` when `a` is NULL |
| [`IF d, c, a, b`](#if) | `a` where `c` is TRUE, else `b` |
| [`NULLIF d, a, b`](#nullif) | NULL where `a IS b`, else `a` |
| [`NULLIFE d, a`](#nullife) | NULL where `a` is the empty string, else `a` |

## `EQ`, `NE`, `LT`, `LE`, `GT`, `GE`

```text
EQ d, a, b
NE d, a, b
LT d, a, b
LE d, a, b
GT d, a, b
GE d, a, b
```

BOOL comparison of `a` with `b`: `a = b`, `a <> b`, `a < b`, `a <= b`, `a > b`, `a >= b`. Values are ordered as described in [Ordering](../values.md#ordering); comparing other mixes of types is an error.

**Cycles:** 1 per element, plus the bytes of the shorter operand ([rules](../cycles.md#string-bytes)).

## `IS`

```text
IS d, a, b
```

BOOL, never NULL: TRUE where `a` and `b` are equal, or both NULL, and FALSE where just one is NULL. Values are ordered as described in [Ordering](../values.md#ordering); comparing two non-NULL values of other mixes of types is an error.

**Cycles:** 1 per element, plus the bytes of the shorter operand ([rules](../cycles.md#string-bytes)).

## `AND`, `OR`

```text
AND d, a, b
OR  d, a, b
```

Three-valued logic on BOOL values; a non-BOOL operand is an error: `FALSE AND NULL` is `FALSE`, and `TRUE OR NULL` is `TRUE`; otherwise a NULL operand gives NULL.

| `a` | `b` | `AND` | `OR` |
|---|---|---|---|
| `TRUE` | `TRUE` | `TRUE` | `TRUE` |
| `TRUE` | `FALSE` | `FALSE` | `TRUE` |
| `FALSE` | `FALSE` | `FALSE` | `FALSE` |
| `TRUE` | `NULL` | `NULL` | `TRUE` |
| `FALSE` | `NULL` | `FALSE` | `NULL` |
| `NULL` | `NULL` | `NULL` | `NULL` |

Both instructions are symmetric in `a` and `b`.

**Cycles:** 1 per element.

## `NOT`

```text
NOT d, a
```

BOOL negation of `a`, which must be BOOL.

**Cycles:** 1 per element.

## `ISNULL`

```text
ISNULL d, a
```

BOOL, never NULL: TRUE where `a` is NULL.

**Cycles:** 1 per element; no string bytes.

## `NVL`

```text
NVL d, a, b
```

`a`, or `b` where `a` is NULL. `a` and `b` may have different types.

**Cycles:** 1 per element; no string bytes.

## `IF`

```text
IF d, c, a, b
```

`a` where `c` is TRUE, else `b` (also where `c` is NULL). `c` must be BOOL; `a` and `b` may have any types, and a NULL `a` or `b` is passed through.

**Cycles:** 1 per element; no string bytes.

## `NULLIF`

```text
NULLIF d, a, b
```

NULL where `a IS b` (see [`IS`](#is)), else `a`.

**Cycles:** 1 per element; no string bytes.

## `NULLIFE`

```text
NULLIFE d, a
```

NULL where `a` is the empty string, else `a`, which must be STR.

**Cycles:** 1 per element; no string bytes.
