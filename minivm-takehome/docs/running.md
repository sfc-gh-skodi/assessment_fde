[MiniVM docs](README.md) › Running

# Running

This page gives the rules every program must follow, what happens on an error,
how to run a program with `bin/minivm`, and the JSON format of the tables it
reads.

## Program rules

The last instruction must be the program's only [`OUT`](instructions/columns.md#out).

| Limit | Value |
|---|---|
| instructions per program | at most 20,000 |
| values held by one register | at most 4,000,000 (a join's output counts) |
| values held by all registers together | at most 64,000,000; a long string counts as several values (about 1 per 32 bytes) |
| work per run | roughly 300,000,000 [cycles](cycles.md); see below |
| rows per table | at most 10,000 |
| program file | at most 4 MiB |
| table-set file | at most 32 MiB and 2,000,000 JSON values |

The work limit stops runaway programs. It counts a run's cycles, but `HJOIN`
and `GROUP` and copying long strings use it up faster than their cycles
suggest, so such programs stop somewhat sooner. Exceeding it, like any other
limit, is an error. It has no effect on the cycles reported for a run that
finishes.

## Errors

Any error stops the program. No result is printed; the error goes to stderr
and `bin/minivm` exits with status 1.

## Command line

```sh
bin/minivm PROGRAM.mini TABLES.json
bin/minivm --schema TABLES.json
```

runs the program in `PROGRAM.mini` on the [table set](#table-sets) in
`TABLES.json`. On success it prints one line of JSON to stdout and exits 0:

```json
{"ncols": N, "rows": [...], "cycles": C}
```

- `ncols` is the number of `OUT` operands.
- `rows` is the result, one array of `ncols` values per row.
  `NULL` is `null` and a BOOL is `true` or `false`. An INT is a JSON integer,
  or a string of its digits outside -2^63 .. 2^63-1. A NUM is a string that keeps
  its digits after the point (`"250.00"`), a STR a string, and a DATE a string
  `"YYYY-MM-DD"`.
- `cycles` is the program's cost ([Cycles](cycles.md)).

| Exit status | Meaning |
|---|---|
| 0 | success; the result is on stdout |
| 1 | error; the message is on stderr |
| 2 | wrong number of arguments; a usage line is on stderr |

With the program from [Language](language.md#programs) saved as
`over100.mini` and the [example table set](#example) as `orders.json`:

```sh
$ bin/minivm over100.mini orders.json
{"ncols":2,"rows":[[1,"250.00"]],"cycles":42}
```

`bin/minivm --schema TABLES.json` prints the table set's [schema file](#schema-files)
as one line of JSON instead of running a program.

A program that compares a DATE with an INT stops with an error:

```text
LOAD d, orders.o_date
GT   m, d, 5
OUT  m
```

```sh
$ bin/minivm bad.mini orders.json
error: line 2: GT: expected a number, got DATE
```

## Table sets

A table set is a JSON object mapping each table name to its columns and rows:

```json
{"<table>": {"columns": [{"name": "c", "type": "INT|NUM|STR|DATE"}], "rows": [[...], ...]}}
```

- Table and column names are identifiers (letters, digits and `_`, not starting
  with a digit), compared without regard to case. Duplicate names are an error.
- `columns` lists each column's `name` and `type`, one of `INT`, `NUM`, `STR`, `DATE`.
- `rows` lists each row as an array of values, one per column, in column order.
  A table without `rows` is empty.
- A table may also declare [constraints](#constraints).
- Any key other than those shown or listed there is an error, as is a repeated key.
- A table holds at most 10,000 rows.
- INT values are JSON integers that fit in 32 bits.
- NUM values may be JSON numbers or strings. They must be exact, in the
  [NUM range](values.md#num-range).
- Dates are strings `"YYYY-MM-DD"`, years 0001 to 9999.
- JSON `null` is `NULL`.

A program reads a stored column with `LOAD d, table.column` ([`LOAD`](instructions/columns.md#load)).

### Constraints

A table may declare what its rows guarantee. `bin/minivm` checks every declared
constraint when it reads the table set, and a table set that breaks one is an error.

| Key | Example | Guarantee |
|---|---|---|
| `key` | `["l_order", "l_no"]` | the columns are never `NULL`, and no two rows agree on all of them |
| `not_null` | `["p_price"]` | the columns are never `NULL` |
| `refs` | `{"l_prod": "products.p_id"}` | every non-NULL value of the column is a value of the other column, which must be its table's whole `key` and have the same type (INT and NUM may refer to each other) |
| `check` | `{"l_qty": [1, 500]}` | every non-NULL value lies between the bounds, inclusive; `null` leaves a side open; INT, NUM and DATE columns only |
| `sorted` | `["l_order", "l_no"]` | the rows are stored in ascending order of the columns, as `ASC NF` sorts them |

Values are compared as in [Ordering](values.md#ordering), so NUM keys `1.0` and
`1.00` are the same key. Column names in constraints are compared without regard
to case, and naming a column twice in one constraint is an error. A table may refer to itself.

```json
{
  "orders": {"columns": [{"name": "o_id", "type": "INT"}], "key": ["o_id"], "rows": [[1], [2]]},
  "lines": {
    "columns": [{"name": "l_order", "type": "INT"}, {"name": "l_qty", "type": "INT"}],
    "refs": {"l_order": "orders.o_id"}, "check": {"l_qty": [1, null]}, "sorted": ["l_order"],
    "rows": [[1, 3], [1, 1], [2, 5]]
  }
}
```

### Example

```json
{
  "orders": {
    "columns": [
      {"name": "o_id",     "type": "INT"},
      {"name": "o_amt",    "type": "NUM"},
      {"name": "o_date",   "type": "DATE"},
      {"name": "o_status", "type": "STR"}
    ],
    "rows": [
      [1, 250.00,   "2024-01-31", "shipped"],
      [2, "99.5",   "2024-02-01", ""],
      [3, null,     "2024-02-03", null]
    ]
  }
}
```

## Schema files

`bin/minivm --schema TABLES.json` describes a table set without its rows: each table's
columns and [constraints](#constraints), as in the table set, plus a `stats` object
summarizing its rows:

```json
{"<table>": {"columns": [...], "key": [...], ..., "stats": {"rows": N, "columns": {"<column>": {"nulls": N, "distinct": N, "min": v, "max": v, "common": [[v, N], ...], ...}}}}}
```

The constraints hold for every table set with this schema; the stats describe only this one.

| Stats field | Meaning |
|---|---|
| `rows` | rows in the table |
| `nulls` | `NULL` values in the column |
| `distinct` | distinct non-NULL values, compared as in [Ordering](values.md#ordering) |
| `min`, `max` | least and greatest non-NULL value; `null` if there is none |
| `avg_bytes` | STR only: mean bytes of the non-NULL values, rounded to 2 decimal places; 0 if there are none |
| `common` | up to 8 values that occur more than once, most frequent first (ties in value order), with their counts |
| `histogram` | INT, NUM and DATE only, if any value is non-NULL: 11 bounds of 10 equal-count buckets of the sorted non-NULL values, from `min` to `max` |
