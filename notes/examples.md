# Example programs: what they compute, cost, waste

How these were measured: `bin/minivm examples/programs/qNNNN.mini examples/data.json`. Every example matched `examples/expected/` rows and cycles exactly. Per-opcode cycles come from running the program cut off after each instruction and taking the difference in cycles.
"Waste" is my reading of each program and has not been rewritten and measured yet. Items marked *(needs proof)* depend on a reasoning step that the evaluator must still confirm.

| Program | Rows out | Instrs | Cycles | Biggest cost |
|---|---|---|---|---|
| q0001 | 4 | 89 | 13,766 | CAT+LEFT 7,124 (52%) |
| q0002 | 7 | 41 | 3,617 | HJOIN 784, GROUP 670 |
| q0003 | 12 | 32 | 8,562 | GROUP 1,888, HJOIN 1,346 |
| q0004 | 1 | 121 | 18,442 | GATHER 6,672 (36%), UPPER 3,120 |
| q0005 | 2 | 79 | 5,518 | GATHER 1,666, HJOIN 664 |
| q0006 | 30 | 34 | 6,338 | GROUP 1,888, HJOIN 1,346 |
| q0007 | 3 | 49 | 2,596 | CAT 650, LEFT 502 |
| q0008 | 3 | 31 | 1,524 | RTRIM/UPPER 540 |

## q0001: line export for big 2024 orders
**Computes:** lines of orders dated 2024 with `o_amt > 750`, giving order, line number, product, and a 40-character "product / category" label, in (order, line) order.
**Waste:**
- The label (NVL, CAT, CAT, NULLIFE, LEFT) is built for every line before the orders filter, which keeps only 4 rows. CAT+LEFT cost 7,124 cycles.
- `SORT r7` on (l_order, l_no) does nothing, because `lines` is declared `sorted` on exactly those columns (860 cycles plus 6 GATHERs).
- 14 columns are gathered through 3 joins, but only 4 are output (GATHER 2,574).
- `GE l_qty, 1` is always TRUE, because `l_qty` is `not_null` with check [1, 500]. The IDX+GATHER filter after it is pointless.
- The orders filter comes last instead of first.

## q0002: discounted-line rank within product
**Computes:** for each discounted line of a 2023 order with `o_amt > 300`, how many discounted lines of the same product (across all orders) sold fewer units. Ordered by (order, line).
**Waste:**
- `l_disc` is loaded twice, and the second load (`t5`) is never used.
- The orders filter is applied after the self-join, group and sum. Only the outer rows can be filtered early, because the count must still range over all discounted lines.
- The quadratic self-HJOIN on `l_prod` followed by GROUP/GSUM (HJOIN 550, GROUP 670, GSUM 226) could become sort- or group-based counting.
- The final SORT may be an identity, because the rows already follow lines order *(needs proof)*.

## q0003: top 4 orders per status
**Computes:** per normalized status (NULLIFE → RTRIM → UPPER), the 4 orders with the highest `o_id`, ordered by id. Outputs id, raw status, id. Orders with an empty or NULL status drop out, because HJOIN never matches NULL keys.
**Waste:**
- A quadratic self-HJOIN on status, then GROUP and GSUM over all pairs, counts the "better" rows for each order (GROUP 1,888, HJOIN 1,346). A sort by (status, id DESC) plus a per-group rank is linear-ish. The rewrite must keep dropping NULL keys.
- Duplicate GATHERs: `r11` = `r9` and `r12` = `r10`.
- Six element-wise ops run on the pair domain, about 318 cycles each.
- `o_cust` is loaded and gathered but never output.

## q0004: Kitchen revenue for central customers in 2023
**Computes:** one row giving the sum of `qty*price*(1-disc)` and the line count, for Kitchen-category products sold to central-region customers in 2023.
**Waste:**
- It joins all 4 tables, carries every column (GATHER 6,672), and only filters at the end.
- The string cleanup (NULLIFE/RTRIM/UPPER on category and region) runs on joined rows (UPPER+RTRIM about 5,100 cycles) instead of on the 4 categories and 12 customers.
- `UPPER t82` is dead (1,108 cycles).
- `SORT t83` (1,126 cycles) is useless before GALL/GSUM/GCOUNT. Per the docs, GSUM's result doesn't depend on row order.
- The categories join uses NLJOIN.

## q0005: card-paid revenue per category
**Computes:** revenue per category name over lines of orders with at least one card payment, ordered by category id.
**Waste:**
- It joins card payments onto lines, then de-duplicates with SORT + GROUP + GFIRST. That is a semi-join, so the payments could be de-duplicated per order first.
- `SORT r29` on (l_order, l_no) is probably an identity, because HJOIN output is ordered by line index and `lines` is sorted *(needs proof)*.
- 9 to 11 columns are gathered through each step, but only category and revenue reach `OUT`.
- The product and category joins use NLJOIN.

## q0006: max quantity within each order's status
**Computes:** for orders dated on or after 2023-01-01, the id, amount, and the largest `o_qty` among orders with the same normalized status, ordered by id. NULL or empty status rows drop out (HJOIN).
**Waste:**
- A quadratic self-HJOIN, then GROUP and GMAX (GROUP 1,888, HJOIN 1,346, GMAX 632), where GROUP + GMAX + GID + GATHER is linear. The rewrite must filter out NULL keys explicitly, because GROUP treats NULL = NULL.
- `IOTA r28` with `GATHER r29` is an identity copy.
- The date and status columns are gathered but unused. The final SORT by id is needed, because `orders` isn't declared sorted.

## q0007: top 5 July-2023 orders by amount
**Computes:** the 5 largest-amount orders dated July 2023, with ties broken by id. Outputs id, amount, and a 40-character "note status" label.
**Waste:**
- The label (NVL, CAT, LEFT) is built for all 30 orders, but only 5 are output (CAT 650, LEFT 502).
- `UPPER r14` and `DOW r15` are dead.
- It SORTs every order before filtering, where filtering first and then using TOPK 5 would do.
- 8 columns are gathered, but 3 are output.

## q0008: count and quantity per status
**Computes:** order count and total `o_qty` per normalized status, for orders with `o_qty >= 5`, biggest count first, then by name.
**Waste:**
- 5 of the 7 loads are never used (only status and qty are), and all 7 are gathered after the filter.
- Otherwise it's already tight, so expect only small gains.

## Cross-cutting patterns (feed BUILD_PLAN §3)
- Dead loads, gathers and ops appear in every example except q0002.
- Every column is carried through every join or filter: q0001, q0004, q0005, q0007, q0008.
- Filters come late: they run after joins, after string building, or after sorting (q0001, q0002, q0004, q0007).
- Sorts are redundant: on a declared-`sorted` table (q0001, probably q0005), before an order-independent aggregate (q0004), or before a filter where TOPK would do (q0007).
- Quadratic self-joins compute per-group statistics (q0002, q0003, q0006); this is the highest gain but also the highest NULL-semantics risk.
- NLJOIN is used where HJOIN may be cheaper (q0004, q0005); the cost depends on input sizes.
