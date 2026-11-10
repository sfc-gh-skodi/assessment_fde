# Prompts sent by the main agent to subagents

## Hand-optimize q0005-q0008 (generalPurpose)

```
You are doing research for a planning document (NOT building the final product). Context: MiniVM is a toy column VM. Docs are in /Users/skodi/Desktop/take-home-assessment/minivm-takehome/docs/ (read README.md, language.md, values.md, running.md, cycles.md and every file in docs/instructions/ first — read them fully, semantics details matter). The VM binary is /Users/skodi/Desktop/take-home-assessment/minivm-takehome/bin/minivm, usage: `bin/minivm PROGRAM.mini TABLES.json` prints {"ncols","rows","cycles"}. Example programs: /Users/skodi/Desktop/take-home-assessment/minivm-takehome/examples/programs/q0005.mini .. q0008.mini, data: examples/data.json, schema with constraints+stats: examples/schema.json.

TASK: For each of q0005, q0006, q0007, q0008, hand-write the fastest program you can that gives IDENTICAL results (same rows, same row order, same printed values incl. NUM scale like "2.0" vs "2.00") on examples/data.json, AND that would remain correct on ANY data satisfying the table constraints in schema.json (key, not_null, refs, check, sorted). You may rely on constraints but NOT on stats (stats describe only this one dataset). You must not introduce errors on data where the original succeeds: e.g. don't evaluate an operation that can error (DIV/IDIV/MOD by possibly-zero, numeric overflow, DATEADD out of range, type errors, GATHER out of range) on rows the original never evaluated it on. Keep the exact output row order of the original (strictest interpretation), including ties.

Notable: q0006 uses a quadratic self-HJOIN + GROUP to compute a per-group max; consider replacing with GROUP + GMAX + GID + GATHER, but check carefully that the result (incl. which rows appear, their order, NULL keys, GROUP's NULL=NULL vs HJOIN's NULL-matches-nothing semantics, and GMAX 'first of equals' printing) is identical in all cases allowed by the constraints. q0005 joins payments onto lines then de-dups with GROUP/GFIRST (a semi-join); consider de-duplicating payments first.

Write files ONLY under /tmp/mvprobe/hand2/ (create it). Name them q0005_opt.mini etc. Do not modify anything in the repo.

For each program verify with bin/minivm that the output rows match the original exactly (compare JSON rows and ncols) and record cycles before/after. Iterate a few times to get the cycles down; use the cost model in docs/cycles.md (NLJOIN vs HJOIN cost depends on sizes; HJOIN = 6 per row of either side + key string bytes + 2 per output pair; NLJOIN = per pair 1 + shorter key bytes, + 2 per output pair; TOPK vs SORT).

Additionally, to check generality, build 2-3 extra small table-set JSON files under /tmp/mvprobe/hand2/ that satisfy the same constraints as examples/schema.json (same tables/columns/constraints) but with adversarial content: NULLs in nullable columns (e.g. o_note, c_credit, k_parent, any non-constrained column), status strings with trailing spaces and mixed case ('Open ', 'OPEN', 'open'), empty strings, ties in sort keys, an empty table or two. Verify your optimized programs still match the originals on those too (where the original doesn't error).

Return a concise report with, for each program:
1. original cycles, optimized cycles, speedup ratio (on examples/data.json)
2. the final optimized program text
3. a bullet list of each rewrite applied, approximate cycles saved, and WHY it is safe on any constraint-satisfying data
4. rewrites considered but rejected as unsafe, and why (valuable!)
5. results on your adversarial datasets (match / mismatch details)
6. any surprising VM behavior observed (verified with bin/minivm).
Be precise; numbers must be measured with bin/minivm.
```

## Hand-optimize q0001-q0004 (generalPurpose)

```
You are doing research for a planning document (NOT building the final product). Context: MiniVM is a toy column VM. Docs are in /Users/skodi/Desktop/take-home-assessment/minivm-takehome/docs/ (read README.md, language.md, values.md, running.md, cycles.md and every file in docs/instructions/ first — read them fully, semantics details matter). The VM binary is /Users/skodi/Desktop/take-home-assessment/minivm-takehome/bin/minivm, usage: `bin/minivm PROGRAM.mini TABLES.json` prints {"ncols","rows","cycles"}. Example programs: /Users/skodi/Desktop/take-home-assessment/minivm-takehome/examples/programs/q0001.mini .. q0004.mini, data: examples/data.json, schema with constraints+stats: examples/schema.json.

TASK: For each of q0001, q0002, q0003, q0004, hand-write the fastest program you can that gives IDENTICAL results (same rows, same row order, same printed values incl. NUM scale like "2.0" vs "2.00") on examples/data.json, AND that would remain correct on ANY data satisfying the table constraints in schema.json (key, not_null, refs, check, sorted). You may rely on constraints but NOT on stats (stats describe only this one dataset). You must not introduce errors on data where the original succeeds: e.g. don't evaluate an operation that can error (DIV/IDIV/MOD by possibly-zero, numeric overflow, DATEADD out of range, type errors, GATHER out of range) on rows the original never evaluated it on. Keep the exact output row order of the original (strictest interpretation), including ties.

Write files ONLY under /tmp/mvprobe/hand/ (create it). Name them q0001_opt.mini etc. Do not modify anything in the repo.

For each program verify with bin/minivm that the output rows match the original exactly (compare JSON rows and ncols) and record cycles before/after. Iterate a few times to get the cycles down; use the cost model in docs/cycles.md to reason (NLJOIN vs HJOIN cost depends on sizes; HJOIN = 6 per row of either side + key string bytes + 2 per output pair; NLJOIN = per pair 1 + shorter key bytes, + 2 per output pair).

Return a concise report with, for each program:
1. original cycles, optimized cycles, speedup ratio
2. the final optimized program text
3. a bullet list of each rewrite applied, the approximate cycles it saved, and WHY it is safe on any constraint-satisfying data (name the constraint or semantic rule relied on, e.g. 'lines sorted by (l_order,l_no) => SORT is identity', 'l_qty not_null + check [1,500] => GE l_qty,1 always TRUE', 'filter before join preserves HJOIN (i,j) order')
4. any rewrite you considered but rejected as unsafe, and why (these are valuable).
5. any surprising VM behavior you observed (verify with bin/minivm, don't guess).
Be precise; numbers must be measured with bin/minivm.
```

## Research agent working model (generalPurpose)

```
Research task (do NOT build anything). Read the problem one-pager /Users/skodi/Desktop/take-home-assessment/minivm-onepager.pdf, skim the docs in /Users/skodi/Desktop/take-home-assessment/minivm-takehome/docs/ (README, running, cycles) and read /Users/skodi/Desktop/take-home-assessment/BUILD_PLAN.md and /Users/skodi/Desktop/take-home-assessment/notes/INITIAL_PROMPT.md.

Context: the user (2–3 hours of their own time) will use AI coding agents (Cortex Code with subagents) to build (a) an optimizer for MiniVM programs and (b) an evaluator that detects wrong optimizers. Grading looks at the whole process: git history, raw agent sessions, logs, prompts.

Questions: (1) How should agents work together in an orchestrator–evaluator (build-and-check) loop: roles (orchestrator, builder, independent checker/red-team, reviewer), what context each gets (e.g. checker must not see builder's rationale), handoff artifacts, iteration cadence, commit/revert discipline, when to escalate to the human, how to avoid agents grading their own homework or overfitting to the 8 examples. (2) How to "test the tester": validating the evaluator itself — mutation testing with known-bad optimizers (seeded defects), identity optimizer for false-alarm rate, golden repro cases, determinism across seeds, measuring recall/precision, keeping the evaluator independent from the optimizer code. (3) Practical guardrails: token/time budget, logging to a progression log, stopping criteria.

Write a SHORT markdown file to /Users/skodi/Desktop/take-home-assessment/notes/research_working_model.md (aim ≤ 80 lines) with sections **Findings**, **Risks**, **Recommendations**; include a tiny ASCII diagram of the loop. Bullets, concrete, no fluff. Don't modify any other file. Return a 5-line summary.
```

## Research optimizer rewrites (generalPurpose)

```
Research task (do NOT build an optimizer). Read the problem one-pager /Users/skodi/Desktop/take-home-assessment/minivm-onepager.pdf and all docs in /Users/skodi/Desktop/take-home-assessment/minivm-takehome/docs/ (README, language, values, running, cycles, instructions/*). Also skim /Users/skodi/Desktop/take-home-assessment/notes/examples.md (per-example cycle profile and waste already measured) and /Users/skodi/Desktop/take-home-assessment/BUILD_PLAN.md §3. The VM is minivm-takehome/bin/minivm (`bin/minivm PROG.mini examples/data.json`); use it to verify any claim you're unsure about (scratch files only under /tmp/research_opt/).

Question: For a MiniVM optimizer that must give identical results on ANY data satisfying the schema constraints (key, not_null, refs, check, sorted — stats are only for cost), which rewrites save the most cycles, which are risky, and how to tackle the risky ones safely?

Write a SHORT markdown file to /Users/skodi/Desktop/take-home-assessment/notes/research_optimizer.md (aim ≤ 80 lines) with three sections: **Findings** (rewrites ranked by cycles saved, cite cost-model reasons and example evidence; mark numbers as measured vs estimate), **Risks** (concrete semantic traps: NULL handling HJOIN vs GROUP, data-dependent errors, row order/ties, NUM scale printing, VM limits, constraint misuse, etc.), **Recommendations** (order to implement, safety rule per rewrite, what to gate/skip). Bullet points, no fluff. Don't modify any other file. Return a 5-line summary of the file.
```

## Research evaluator methods (generalPurpose)

```
Research task (do NOT build an evaluator). Read the problem one-pager /Users/skodi/Desktop/take-home-assessment/minivm-onepager.pdf and all docs in /Users/skodi/Desktop/take-home-assessment/minivm-takehome/docs/ (README, language, values, running, cycles, instructions/*). Also skim /Users/skodi/Desktop/take-home-assessment/BUILD_PLAN.md §4–5. The VM is minivm-takehome/bin/minivm (`bin/minivm PROG.mini DATA.json`, ~42 ms per run measured, 16 cores; `bin/minivm --schema DATA.json` validates constraints and prints schema). Verify any VM behavior claims with it (scratch files only under /tmp/research_eval/).

Questions: (1) What are industry best practices for evaluating/validating optimizations of low-level code (compiler/assembly/query-plan optimizers): e.g. differential testing, translation validation (Alive2, CompCert), superoptimizer verification (STOKE), metamorphic testing, fuzzing (Csmith, SQLancer TLP/NoREC/PQS), test-case reduction (C-Reduce), mutation testing of the test oracle. Use web_fetch only if needed; your own knowledge is fine but be accurate. (2) Concretely, how do we prove an optimizer is WRONG within 2 minutes using bin/minivm (data generation respecting constraints, adversarial values, program generation, budget math, early exit). (3) How do we avoid flagging a CORRECT optimizer (false alarms): order-insensitive comparison only when order is unspecified, 1e-6 relative numeric tolerance, NUM scale '2.0' vs '2.00', skipping inputs where the original errors, timeouts, determinism, flakiness.

Write a SHORT markdown file to /Users/skodi/Desktop/take-home-assessment/notes/research_evaluator.md (aim ≤ 80 lines) with sections **Findings**, **Risks**, **Recommendations**. Bullets, concrete, no fluff. Don't modify any other file. Return a 5-line summary.
```
