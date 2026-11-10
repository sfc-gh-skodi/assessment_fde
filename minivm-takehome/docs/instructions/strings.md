[MiniVM docs](../README.md) › [Instructions](README.md) › Strings

# Strings

Element-wise operations on STR values. All instructions on this page follow the [element-wise rules](README.md#element-wise-instructions): the result is `NULL` when any operand is `NULL`. Lengths and positions count characters; string-byte costs count bytes ([rules](../cycles.md#string-bytes)).

| Instruction | Result |
|---|---|
| [`UPPER d, s`](#upper) | upper case (Unicode) |
| [`RTRIM d, s`](#rtrim-trim) / [`TRIM d, s`](#rtrim-trim) | without trailing / leading and trailing spaces |
| [`LEFT d, s, n`](#left) | first `n` characters |
| [`SUBSTR d, s, start, len`](#substr) | `len` characters from 1-based `start` |
| [`LEN d, s`](#len) | number of characters |
| [`CAT d, a, b`](#cat) | concatenation |

## `UPPER`

```text
UPPER d, s
```

`s` in upper case, by Unicode's full case mapping, which can change the number of characters: `UPPER('straße')` is `'STRASSE'`.

**Cycles:** 1 per element, plus 1 per byte of `s` and of the result ([rules](../cycles.md#string-bytes)).

## `RTRIM`, `TRIM`

```text
RTRIM d, s
TRIM  d, s
```

`s` without trailing spaces (`RTRIM`), or without leading and trailing spaces (`TRIM`). Only `' '` counts as a space.

**Cycles:** 1 per element, plus 1 per byte of `s` and of the result ([rules](../cycles.md#string-bytes)).

## `LEFT`

```text
LEFT d, s, n
```

The first `n` characters of `s` (all of `s` if it is shorter). `n` is a non-negative [integer literal](../language.md#integer-operands).

**Cycles:** 1 per element, plus 1 per byte of `s` and of the result ([rules](../cycles.md#string-bytes)).

## `SUBSTR`

```text
SUBSTR d, s, start, len
```

`len` characters of `s`, starting at the 1-based position `start` (fewer if `s` ends first). `start` (at least 1) and `len` are [integer literals](../language.md#integer-operands).

**Cycles:** 1 per element, plus 1 per byte of `s` and of the result ([rules](../cycles.md#string-bytes)).

## `LEN`

```text
LEN d, s
```

INT: the number of characters in `s`.

**Cycles:** 1 per element, plus 1 per byte of `s` ([rules](../cycles.md#string-bytes)).

## `CAT`

```text
CAT d, a, b
```

The concatenation of `a` and `b`.

**Cycles:** 1 per element, plus 1 per byte of `a`, of `b` (literals included) and of the result ([rules](../cycles.md#string-bytes)).

## Example

Given a table `t` whose STR column `s` holds `' ab '`, `''` and `'Zoë'`:

```text
LOAD  s, t.s
TRIM  u, s
CAT   c, u, '!'
LEN   l, c
OUT   c, l
```

prints `{"ncols":2,"rows":[["ab!",3],["!",1],["Zoë!",4]],"cycles":73}`. `'Zoë!'` has 4 characters but 5 bytes: `CAT` costs 1 + 4 + 1 + 5 = 11 cycles on that row, and `LEN` costs 1 + 5.
