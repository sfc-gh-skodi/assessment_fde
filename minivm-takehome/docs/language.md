[MiniVM docs](README.md) › Language

# Language

This page gives the syntax of MiniVM programs: lines, comments, opcodes,
registers, operands and literals.

## Programs

A program is straight-line: its instructions run once each, in order. Each
line holds one instruction. A `;` starts a comment, which runs to the end of
the line; a line may hold only a comment, or be blank. Spaces and tabs are
interchangeable: they separate the opcode from its operands, and may indent a
line or surround an operand.

```text
; Ids and amounts of orders over 100.
load   id, orders.o_id
load   amt, orders.o_amt
gt     m, amt, 100      ; NULL where o_amt is NULL
idx    i, m
gather a, id, i
gather b, amt, i
out    a, b
```

The program must end with its only `OUT`; see [Program rules](running.md#program-rules).

## Instructions

An instruction is an opcode followed by comma-separated operands:

```text
OP dest, operand, ...
```

Opcodes are case-insensitive: `gt`, `Gt` and `GT` are the same instruction.
So are the keywords `NULL`, `TRUE`, `FALSE`, `ASC`, `DESC`, `NF`, `NL` and
`NULLEQ`.
Each opcode's operands are given on its page in the
[instruction reference](instructions/README.md).

## Registers

Register names are identifiers, such as `r1`, `amt` or `_t0`: a letter or `_`,
followed by letters, digits and `_`. Register names are case-sensitive, and a
keyword can't be a register name. A register holds a column or a group set
([Values](values.md#columns-and-group-sets)) and can be overwritten.

## Operands

An operand is one of:

| Operand | Example | Used by |
|---|---|---|
| register | `amt` | every instruction |
| literal | `100.00` | element-wise instructions, `FILL`, integer operands such as `LEFT`'s `n` |
| `table.column` | `orders.o_amt` | [`LOAD`](instructions/columns.md#load) |
| sort key | `amt DESC NL` | [`SORT`, `TOPK`](instructions/sorting.md#sort-keys) |
| `NULLEQ` | `NULLEQ` | [`NLJOIN`, `HJOIN`](instructions/joins.md#nljoin-hjoin) |

## Literals

| Literal | Type | Notes |
|---|---|---|
| `42`, `-7` | INT | must fit in 128 bits |
| `12.50` | NUM | must be exact, in the [NUM range](values.md#num-range) |
| `'it''s'` | STR | a quote inside the string is written twice |
| `#2024-01-31#` | DATE | years 0001 to 9999 |
| `NULL` | NULL | |
| `TRUE`, `FALSE` | BOOL | |

A literal stands for that value at every row.

## Integer operands

Some operands must be integer literals rather than registers: `n` and `len`
(`LEFT`, `SUBSTR`, `SLICE`, `TOPK`) are non-negative, and `SUBSTR`'s `start` is
at least 1. They may be arbitrarily large; a count larger than the input means
all of it.
