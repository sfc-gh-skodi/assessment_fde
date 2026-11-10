# Optimizer research: what pays, what bites, in what order

Sources: one-pager, `docs/*`, `notes/examples.md`, BUILD_PLAN §3. **[M]** = measured with `bin/minivm` on `examples/data.json`
(scratch files in `/tmp/research_opt/`); **[E]** = estimate from the cost table.

## Findings (ranked by cycles saved)
1. **Late materialization + filter-first (move filters up, run element-wise ops only on surviving rows).** Cost is per element plus
   per string byte, so string ops (CAT/LEFT/UPPER/RTRIM) on wide row sets dominate. q7: run the filter, then TOPK 5, then build the label
   on 3 rows: **2596 → 637 (4.1x) [M]**, identical rows. q1 CAT+LEFT is 7,124 of 13,766 cycles, but the filter keeps only 4 rows, so most of that goes away **[E]**.
   q4 runs UPPER/RTRIM (about 5,100) on joined rows instead of on 4 categories and 12 customers **[E: ~25%]**.
2. **Replace a quadratic self-join with a GROUP aggregate.** `HJOIN k,k` costs 2 per output pair (n² for each group) and then GROUPs the pairs.
   q6 becomes `GROUP key → GMAX → GID → GATHER` with an explicit `NOT ISNULL(key)` filter: **6338 → 2091 (3.0x) [M]**, identical rows.
   q3 and q2 (count of better rows, top-n per group) have the same shape: GROUP+HJOIN ≈ 3,200 of 8,562 in q3 **[M profile]**, about 2–3x **[E]**.
3. **Dead-code elimination and GATHER sinking.** Every GATHER costs 1 per value, and legacy plans re-gather 7–14 columns after every join
   or filter. q4 GATHER is 6,672 (36%) **[M profile]**. Carry index vectors, compose them (`GATHER(GATHER(s,i),j)` → `GATHER(s,GATHER(i,j))`),
   and gather only columns that reach OUT: 20–50% on q1/q4/q5 **[E]**. Dead ops: q4 `UPPER t82` 1,108 **[M]**; q7 UPPER and DOW.
4. **Push filters below joins.** HJOIN costs (n+m)·(6+bytes) + 2·pairs. Filtering a side first shrinks both terms and every
   downstream GATHER. q4 joins 4 tables and filters last: 30–70% **[E]**.
5. **Sort reduction.** SORT costs 2/row plus about n·log n comparisons at (2+bytes) each. Options: SORT+filter+SLICE → filter+TOPK (part of q7's 4.1x);
   SORT on a `sorted` table → identity (q1, 860 + 6 GATHERs **[M profile]**); SORT before GSUM/GCOUNT/GALL is dead (q4, 1,126) **[M profile]**.
6. **Constraint rewrites.** Cheap but small: drop an always-TRUE predicate (`l_qty` not_null + check [1,500] → `GE l_qty,1`, q1).
   Join elimination when the FK is `not_null` + `refs` to a `key` and no right-side columns are used, so each left row matches exactly once **[E: one HJOIN + its GATHERs]**.
7. **Choose the join algorithm.** NLJOIN costs n·m·(1+bytes). That is cheaper than HJOIN only when one side is tiny
   (INT keys: n·m < 6(n+m), e.g. m ≤ 5). So q4/q5 NLJOIN against 4 categories may already be optimal. Pick using stats. Small gain **[E]**.
8. **CSE** (q2 loads `l_disc` twice; q3 `r11`=`r9`): tiny but free.

## Risks (concrete traps)
- **NULL keys differ between HJOIN and GROUP.** HJOIN never matches NULL (unless `NULLEQ`); GROUP makes one NULL group **[M: n1/n2 probes]**.
  `''` is not NULL and HJOIN matches it **[M]**. Any join→group rewrite must add `ISNULL` filtering, or the reverse.
- **Introducing errors.** `DIV x,d` after `IDX d≠0` succeeds. Moving it before the filter errors with *division by zero* **[M: n3 vs n4]**.
  The same applies to IDIV/MOD, DATEADD range, overflow (ADD/MUL/NEG/GSUM totals), NUM×INT>2^96, type errors on mixed NVL/IF columns,
  and comparisons of STR with INT. Filter pushdown below a join evaluates the predicate on *unmatched* rows the original never saw.
- **Row order and ties.** OUT order is the contract when the program sorts. HJOIN orders by (i, j), so swapping sides changes the order.
  GROUP numbers groups by first appearance, so reordering its input changes the group order, which GFIRST row is picked, and which "first of equals" GMIN/GMAX returns.
  SORT is stable, so dropping a tie-break key or substituting an unstable order changes the rows. `sorted` holds only for the *stored* order: it
  survives IDX/ascending GATHER and the left side of a join, **not** the right side of HJOIN, GROUP output, or a SORT on other keys.
- **NUM scale printing.** `1.0`≠`1.00` as text. GMAX keeps the first-of-equals scale (`"1.0"`). GSUM uses the max scale in the group (`"2.00"`).
  `MUL v,1.000` re-scales (`"1.0000"`), and DIV keeps the dividend's scale **[M: n1, n5]**. Algebraic identities (x*1, x+0.0) change the printed text.
  They are equal by value (1e-6 rule), but a strict grader might compare the strings, so avoid them.
- **Unicode.** `UPPER('straße')`='STRASSE' changes length, so UPPER does not commute with LEFT/SUBSTR/LEN, and string bytes ≠ characters.
- **Misusing constraints.** customers/regions have **no key**, so joins there can fan out. `refs` allows NULL FKs (inner join drops them) unless the FK is also `not_null`.
  `check` without `not_null` doesn't make a predicate TRUE (NULL → IDX drops the row). Stats describe one dataset, so never base correctness on them.
- **VM limits.** 4M values per register, 64M total, about 300M work, where HJOIN/GROUP use it up faster than their cycles. A rewrite that grows any
  intermediate (join reordering, an op moved onto a join-expanded domain) can make the optimized program fail where the original passed.
  The 20k-instruction limit and the 1 s optimizer limit rule out super-linear passes.
- **Dead code that errors** may be removed (if the original errors, anything goes), but never *add* an op that may error.

## Recommendations
1. **Order:** DCE+CSE → GATHER composition/sinking → late materialization of element-wise ops → sort reduction (TOPK, dead SORT,
   `sorted` identity) → filter pushdown below joins → constraint rewrites → join choice → idioms (self-join→GROUP, semi-join dedup).
2. **Global safety rule:** an op may be evaluated only on a **subset** of the rows it ran on originally (never a superset), in the same
   relative order. Otherwise the rewrite must prove the op is *total*: typed by the schema, no DIV/IDIV/MOD/DATEADD, no possible overflow.
3. **Per rewrite:**
   - DCE/CSE: always safe. Keep OUT and its operand order.
   - GATHER composition: safe (indices come from in-range positions).
   - Filter pushdown: only predicates that use one side and are total. Use IDX on the left side, then re-gather. Never reorder join sides.
   - TOPK: `SORT; IDX; SLICE n` → `IDX; TOPK n` with the same keys (stable), only when the filter doesn't depend on sort position.
   - Drop SORT: only if it is followed by order-insensitive aggregates (GSUM/GCOUNT/GCOUNTV/GALL, *not* GFIRST/GMIN/GMAX/GID order),
     or if the keys are a prefix of `sorted` (ASC NF) on an index proven ascending.
   - Self-join→GROUP: match the exact pattern (HJOIN k,k without NULLEQ → GROUP on left index → aggregate). Add a `NOT ISNULL(k)` filter
     and keep row order so GMAX "first of equals" and GROUP numbering stay the same.
4. **Gate behind the evaluator:** idioms and join elimination. Enable each only after 0 defects on NULL-, tie-, scale- and empty-table-heavy
   generated data. **Skip:** arithmetic re-association/simplification, join reordering, anything that uses stats for correctness.
5. **Guard:** if the estimated cost is not lower, or any intermediate would be larger than the original's (VM limits), emit the input program unchanged.
