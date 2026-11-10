[MiniVM docs](README.md) › Values

# Values

This page describes MiniVM's values and types, what a register holds, and how
values are ordered and compared.

## Types

| Type | Values | Literal |
|---|---|---|
| INT | exact 128-bit integer; a result outside -2^127 .. 2^127-1 is an error | `42` |
| NUM | decimal: see [NUM range](#num-range) | `12.50` |
| STR | string | `'it''s'` |
| DATE | calendar date | `#2024-01-31#` |
| BOOL | `FALSE` or `TRUE` | `TRUE` |

`NULL` is a value of its own, written `NULL`. Unless an instruction says
otherwise, an element-wise result is `NULL` when any operand is `NULL`
([element-wise instructions](instructions/README.md#element-wise-instructions)).

Literal syntax is in [Literals](language.md#literals). Stored columns have
type INT, NUM, STR or DATE ([table sets](running.md#table-sets)).

## NUM range

A NUM is below 1e28 in magnitude and has at most 28 digits after the point,
and its digits without the point, read as an integer, are at most
2^96 - 1 = 79228162514264337593543950335: 28 or 29 significant digits.
A NUM keeps its digits after the point, so `1.0` and `1.00` are equal but
print differently.

A NUM literal or stored value must be such a number exactly; trailing zeros
after the point are dropped as far as needed. A NUM result is rounded half to
even to the most digits after the point that fit, and a result of magnitude
1e28 or more is the error `numeric overflow`. Where an INT meets a NUM in
arithmetic, and in `DIV`, an INT operand above 2^96 - 1 in magnitude is that
error too, even if the result would fit.

## Columns and group sets

A register holds either:

- a **column**: a vector of values; or
- a **group set**: a grouping of rows, made by
  [`GROUP`](instructions/grouping.md#group) or [`GALL`](instructions/grouping.md#gall)
  and read by the other [grouping instructions](instructions/grouping.md).

Registers can be overwritten.

## Ordering

These instructions compare values:

- [`EQ`, `NE`, `LT`, `LE`, `GT`, `GE`](instructions/logic.md#eq-ne-lt-le-gt-ge) and [`IS`](instructions/logic.md#is)
- [`SORT`](instructions/sorting.md#sort) and [`TOPK`](instructions/sorting.md#topk)
- the joins [`NLJOIN`, `HJOIN`](instructions/joins.md#nljoin-hjoin)
- [`GMIN`, `GMAX`](instructions/grouping.md#gmin-gmax)

They order values as follows:

| Values | Order |
|---|---|
| INT and NUM | by numeric value, exactly at any magnitude; INT and NUM mix |
| STR | by bytes |
| DATE | by date |
| BOOL | `FALSE < TRUE` |

Comparing any other mix of types, such as STR with INT or DATE with NUM, is an
error.

String comparison is exact: there is no case folding, and trailing spaces
count, so `'ab'` and `'ab '` differ, as do `'ab'` and `'AB'`.

How each instruction treats `NULL` is given on its page; for sorts, see
[sort keys](instructions/sorting.md#sort-keys).
