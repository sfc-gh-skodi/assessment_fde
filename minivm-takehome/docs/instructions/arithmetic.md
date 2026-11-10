[MiniVM docs](../README.md) › [Instructions](README.md) › Arithmetic

# Arithmetic

Element-wise arithmetic on INT and NUM values. All instructions on this page follow the [element-wise rules](README.md#element-wise-instructions): the result is `NULL` when any operand is `NULL`. Their operands and results are numbers, so they pay no [string bytes](../cycles.md#string-bytes).

| Instruction | Result |
|---|---|
| [`ADD d, a, b`](#add-sub-mul) / `SUB` / `MUL` | INT if both are INT, else NUM |
| [`DIV d, a, b`](#div) | NUM quotient |
| [`IDIV d, a, b`](#idiv) | INT quotient truncated toward zero |
| [`MOD d, a, b`](#mod) | INT remainder with the sign of `a` |
| [`NEG d, a`](#neg) | `-a` |
| [`WRAP d, a`](#wrap) | INT wrapped to 32-bit two's complement |
| [`TRUNC d, a`](#trunc) | INT |

## `ADD`, `SUB`, `MUL`

```text
ADD d, a, b
SUB d, a, b
MUL d, a, b
```

`a + b`, `a - b` and `a * b`. The result is INT if both operands are INT, else NUM, rounded as in [NUM range](../values.md#num-range). A result outside the INT or NUM range is the error `numeric overflow`, as is an INT operand above 2^96 - 1 in magnitude when the other operand is NUM.

**Cycles:** 1 per element.

## `DIV`

```text
DIV d, a, b
```

The NUM quotient `a / b`, rounded as in [NUM range](../values.md#num-range), even when both operands are INT. It is an error if `b` is 0, and `numeric overflow` if the quotient is outside the NUM range or an INT operand is above 2^96 - 1 in magnitude.

**Cycles:** 6 per element.

## `IDIV`

```text
IDIV d, a, b
```

The INT quotient `a / b`, truncated toward zero. Both operands must be INT. It is an error if `b` is 0, or if the quotient is outside the INT range.

**Cycles:** 6 per element.

## `MOD`

```text
MOD d, a, b
```

The INT remainder of `a / b`, with the sign of `a`. Both operands must be INT. It is an error if `b` is 0.

**Cycles:** 6 per element.

## `NEG`

```text
NEG d, a
```

`-a`. A result outside the INT or NUM range is an error.

**Cycles:** 1 per element.

## `WRAP`

```text
WRAP d, a
```

INT `a` wrapped to 32-bit two's complement.

**Cycles:** 1 per element.

## `TRUNC`

```text
TRUNC d, a
```

INT: a NUM `a` truncated toward zero; an INT `a` is unchanged. Any other type is an error.

**Cycles:** 2 per element.
