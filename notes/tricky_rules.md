# Tricky rules: what bin/minivm does and how the evaluator handles it

Every item was checked with `bin/minivm`. They are encoded as 56 repeatable checks in
`prototype_code/evaluator_agent/tricky_checks.py` (56/56 pass).

## Parsing
- **Case:** opcodes and keywords ignore case (`sort` = `SORT` = `SoRt`, `asc nf` = `ASC NF`). Register names are case-sensitive (`a` ≠ `A`, `s` ≠ `S`). The order detector upper-cases opcodes only.
- **Literals:** `;` and `,` inside a string literal are data, not a comment or a separator. `''` is an escaped quote.
- **Layout:** CRLF line endings, blank lines and comments after `OUT` are all fine. `OUT` with no operands is an error.

## Output JSON has no types
- **Text looks alike:** STR `"2.00"`, `"2024-01-31"` and `"1e5"` print exactly like NUM, DATE and plain text. Only BOOL is distinct, because it prints unquoted `true`/`false`.
- **Number formats:** minivm prints numbers only as `-?\d+(\.\d+)?` (JSON integers, or strings beyond ±2^63). The comparator therefore treats only that exact text as a number. **Bug fixed:** it used to parse `'1.0 '` and `'1e5'` as numbers, which hid TRIM-style bugs.
- **BOOL vs INT:** Python has `True == 1`. **Bug fixed:** `true` vs `1` and `false` vs `0` used to compare as equal.
- **Negative zero:** `NEG 0.0` prints `"-0.0"` but `MUL 0.0, -1` prints `"0"`. The two are equal by value, so this is not a defect.
- **Remaining ambiguity:** STR `'1.0'` vs STR `'1.00'` compares as equal numbers. This can't be fixed without column types (documented).

## Tolerance (one-pager: numbers within 1e-6 relative)
- **Large INTs:** this tolerance applies to INTs too. `10000000` vs `10000001` passes. That follows the spec, but it means off-by-one errors on very large counts go undetected.
- **Zero:** the tolerance is purely relative, so `0` vs `0.0000001` is a defect. A correct optimizer doesn't change arithmetic, so this is fine.

## Row order
- **When order counts:** rows are compared **in order** whenever the original's output order comes from a SORT or TOPK, and as a multiset otherwise.
- **Order detector:** decided by a data-flow pass over the original program. It covers filters, the right side of a join, GROUP numbering after a sort, register overwrites, sorts whose result is never output, and comments.
- **Effect:** before this rule, the reversed-rows bug was missed and the sort-flip and dropped-tie-break bugs were barely caught (4 and 2 defects). Now all three are caught (172, 134 and 19 defects), with 0 false alarms on the 8 honest fakes.
- **Known limit:** rows that tie on the sort keys are also compared in order. SORT is stable, so ties keep their input order. An optimizer that legally reorders ties would be flagged. None of the honest fakes do this. It's open question Q1 in the plan.

## Empty and degenerate data
- **Empty tables:** GROUP gives **0 rows**, but GALL gives **1 row `[0, NULL]`**. An optimizer that swaps them is wrong on empty data only.
- **Errors on empty columns:** `DIV` by 0 and type errors never fire on empty or all-NULL columns, so whether a program errors depends on its data.
- **Empty GALL:** GFIRST gives NULL, and GATHER with a NULL index is an error.

## Speed
- **Platform binary:** calling `bin/minivm-macos-aarch64` directly takes 8.3 ms per run, against 38.6 ms through the `bin/minivm` wrapper. The wrapper spawns a shell and runs `xattr` every time. Output is identical on all examples.
- **Evaluator:** it now resolves the platform binary itself, the same way the wrapper does, and clears the quarantine flag once. A full evaluation dropped from 8.4 s to **1.7 s**. `MINIVM=...` overrides the choice.
- **Determinism:** the same program and data give byte-identical output across runs.
