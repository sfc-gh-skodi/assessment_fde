'm starting a take-home assignment. Before we write any code, help me build a solid plan.

## 1. Read first

Problem statement: `../minivm-onepager.pdf`
Assessment package: this folder. Start with `docs/README.md`, then read all of `docs/`, `examples/` and `bin/minivm`.
Use `bin/minivm` to check facts. Don't guess.


## 2. The goal

Build `./optimize program.mini schema.json`. It prints a faster program that gives the same results on any data that fits the schema's constraints, in under 1 second.
Build `./evaluate OPTIMIZER`. It exits non-zero if the optimizer ever changes results, and finishes in under 2 minutes.


## 3. What the plan must cover

**Requirements:** every rule in the one-pager, how we meet it, and how we prove it.
**Open questions:** anything the one-pager leaves unclear, with the default we'll use for each.
**Optimizer design:** the rewrites, ranked by speed gain vs. risk, plus the safety rules that keep results identical.
**Evaluator design:** how it generates test programs and data, how it compares results, and how it stays within 2 minutes.
**Eval rubric:** clear rules for comparing an original program with its optimized version:
outputs: same rows, same order where it matters, numbers within 1e-6
the programs themselves: cycles, instruction count, VM limits
the evaluator: defects caught, false alarms

**Stopping criteria:** when the build-and-test(orchestrator-evaluator) loop should stop. Cover success, no more improvement, budget used up, and when to ask me.
**Failure modes:** what could go wrong, how we'd detect it, and how we'd fix or prevent it.
**Test suite:** easy, medium and complex cases, so we can iterate quickly.
**Runners:** scripts that run the test suite and print an eval and performance report at the end of every run.
**Progression log:** a document that records every approach we try, what we learned, and the key takeaways.
**Timeline:** fits 2/3 hours of my time, with checkpoints and what to cut if we run late.
**Submission:**
git history from the start
no binaries
raw AI session files
models and token spend
a "few days, unlimited compute" plan



## 4. How to work

Use subagents for research where it helps.
Measure numbers with `bin/minivm`, or mark them as estimates.
Write the plan to `BUILD_PLAN.md`. Don't build the optimizer or evaluator yet.
Correctness comes first. A wrong answer is worse than a slow one.
Feel free to save temp artifacts in notes folder 
Do no save any binary files in the repo
Do no overcomplicate, go step by step and save the relevant/important outputs