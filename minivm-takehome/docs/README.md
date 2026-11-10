# MiniVM

MiniVM is a toy column virtual machine. It runs straight-line programs whose
instructions each operate on whole columns of values, and it reports how many
cycles each run costs.

## Example

```text
LOAD    a, orders.o_amt
GT      m, a, 100.00
IDX     i, m
GATHER  big, a, i
OUT     big
```

- `LOAD` reads the stored column `orders.o_amt` into register `a`.
- `GT` sets `m` to a BOOL column: `a > 100.00` at each row.
- `IDX` sets `i` to the positions where `m` is TRUE.
- `GATHER` sets `big` to the values of `a` at the positions in `i`.
- `OUT` makes `big` the program's result.

Saved as `big.mini`, run it from the bundle root:

```sh
bin/minivm big.mini examples/data.json
```

which prints `{"ncols": 1, "rows": [...], "cycles": C}` as one line of JSON; on
`examples/data.json` that is 26 rows and 136 cycles. See [Running](running.md).

## Contents

- [Language](language.md): program syntax: lines, comments, opcodes, registers, operands, literals.
- [Values](values.md): types, NULL, the NUM range, columns and group sets, ordering and comparison.
- [Running](running.md): program rules and limits, errors, the command line, the table-set JSON format.
- [Cycles](cycles.md): the cost model: base cost, string bytes, comparison cost, the full cost table.
- [Instructions](instructions/README.md): conventions shared by all instructions, and an index of every opcode.
  - [Arithmetic](instructions/arithmetic.md): `ADD` `SUB` `MUL` `DIV` `IDIV` `MOD` `NEG` `WRAP` `TRUNC`.
  - [Logic](instructions/logic.md): `EQ` `NE` `LT` `LE` `GT` `GE` `IS` `AND` `OR` `NOT` `ISNULL` `NVL` `IF` `NULLIF` `NULLIFE`.
  - [Strings](instructions/strings.md): `UPPER` `RTRIM` `TRIM` `LEFT` `SUBSTR` `LEN` `CAT`.
  - [Dates](instructions/dates.md): `YEAR` `MONTH` `DAY` `DOW` `DATEADD` `DATEDIFF`.
  - [Columns](instructions/columns.md): `LOAD` `FILL` `IOTA` `IDX` `GATHER` `SLICE` `OUT`.
  - [Sorting](instructions/sorting.md): `SORT` `TOPK`, and sort keys.
  - [Joins](instructions/joins.md): `NLJOIN` `HJOIN`.
  - [Grouping](instructions/grouping.md): `GROUP` `GALL` `GID` `GFIRST` `GCOUNT` `GCOUNTV` `GSUM` `GMIN` `GMAX`.
