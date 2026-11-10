[MiniVM docs](../README.md) › [Instructions](README.md) › Dates

# Dates

Element-wise operations on DATE values. All instructions on this page follow the [element-wise rules](README.md#element-wise-instructions): the result is `NULL` when any operand is `NULL`. Their operands and results are not strings, so they pay no [string bytes](../cycles.md#string-bytes).

| Instruction | Result |
|---|---|
| [`YEAR` `MONTH` `DAY` `d, x`](#year-month-day) | date parts |
| [`DOW d, x`](#dow) | day of week, 1 = Monday ... 7 = Sunday |
| [`DATEADD d, x, n`](#dateadd) | date `x` plus `n` days |
| [`DATEDIFF d, x, y`](#datediff) | INT days from `y` to `x` |

## `YEAR`, `MONTH`, `DAY`

```text
YEAR  d, x
MONTH d, x
DAY   d, x
```

INT: the year, month or day of month of date `x`.

**Cycles:** 2 per element.

## `DOW`

```text
DOW d, x
```

INT: the day of the week of date `x`, 1 = Monday ... 7 = Sunday.

**Cycles:** 2 per element.

## `DATEADD`

```text
DATEADD d, x, n
```

The date `x` plus `n` days. It is an error if the result falls outside years 1..9999.

**Cycles:** 2 per element.

## `DATEDIFF`

```text
DATEDIFF d, x, y
```

INT: the number of days from `y` to `x`.

**Cycles:** 2 per element.
