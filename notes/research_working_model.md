# Research: working model for the build ↔ check loop

Sources: `minivm-onepager.pdf`, `minivm-takehome/docs/{README,running,cycles}.md`, `BUILD_PLAN.md`, `notes/INITIAL_PROMPT.md`.

```
 human (CP gates, ambiguity, destructive git)
   ^ escalate                         | approve
 ORCHESTRATOR -- task card --> BUILDER -- diff + commit --> fast tier (regressions+examples)
   ^   |                                                      | green
   |   +-- spec only --> RED-TEAM (mutants, adversarial data)  v
   |                         |                      CHECKER: ./evaluate ./optimize (3 seeds)
   +---- verdict + repro <---+---- REVIEWER (diff vs §3 safety rule) <----+
         green: keep + log   red: git revert, repro -> tests/regressions/
```

## Findings
- Grading is on process (git history, raw sessions, prompts, logs), so the loop itself is a deliverable: every role's prompt and verdict must land in the repo.
- The oracle is free: `bin/minivm` on the *original* program is ground truth, so the evaluator never needs to reimplement semantics. That makes black-box independence possible.
- Real defects depend on the data (per-row type errors, NULL keys in HJOIN vs GROUP, ties, NUM scale, stats ≠ constraints). Evaluator recall comes mostly from the **data generator**, not the comparer.
- The grader will run `./evaluate` on *their* wrong optimizers. These are likely subtle and depend on the data, so our meta-eval mutants have to look like that, not like trivial breakage.
- Two traps hurt precision: legal changes that look wrong (row reorder when order isn't specified, HJOIN↔NLJOIN, `2.0` vs `2.00`, whatever the optimizer does when the original errors) and timing flakiness (1 s limit under a 16-worker load).
- `BUILD_PLAN.md` §4/§6 already defines the mutant list, identity check and stopping rules. What's missing: role separation, held-out mutants, a regression corpus, determinism checks, and per-iteration logging.

## Risks
- **Self-grading:** the same agent writes a rewrite and the test data that "proves" it. Its blind spots end up in both.
- **Overfitting:** an optimizer tuned to q1–q8, or an evaluator tuned to the mutants its own author wrote. Both get 100% at home and fail on hidden cases.
- **Shared code:** if the evaluator imports the optimizer's parser/IR, one bug hides itself on both sides.
- **Flaky verdicts:** seed-dependent or load-dependent results. The evaluator exits 1 on a correct optimizer, and the grader sees a false alarm.
- **History damage:** `git reset`/squash on red builds erases the process the graders want to read. Binaries in history (BUILD_PLAN §11) are still an open item.
- **Budget overrun:** a full eval with 3 seeds and the meta-eval on every small edit burns both wall time and tokens.

## Recommendations
**Roles and context (who sees what)**
- *Orchestrator* (main session): owns BUILD_PLAN, writes one **task card** per iteration (`notes/tasks/NN.md`: goal, rewrite rank, safety rule, done-definition). It doesn't write optimizer code.
- *Builder* subagent: gets the task card, `optimizer/`, docs. Output: diff, unit test, one commit `opt: <pass> (task NN)`.
- *Red-team* subagent: gets **only** the one-pager, docs, rubric §5 and the CLI. It never sees `optimizer/` or the builder's rationale. It writes mutant optimizers and adversarial data/programs under `evaluator/`.
- *Checker* = the `./evaluate` script, not an LLM. Verdicts are numbers and repro files, not opinions.
- *Reviewer* subagent (fresh context): gets the diff, the safety rule it claims, and the doc pages for the touched opcodes. It answers: "name the dataset that breaks this". Run it for rank ≥5 rewrites only.

**Handoff artifacts:** task card → commit SHA → `eval_out/report.json` (defects, recall, false alarms, geomean, wall time) → reviewer note → `PROGRESSION_LOG.md` entry. Agents talk through files, not chat summaries.

**Cadence and git discipline**
- One rewrite per iteration. Tier 1 (<15 s: regressions + 8 examples) on every edit. Tier 2 (full eval, 1 seed) before each commit. Tier 3 (3 seeds + meta-eval) at each CP.
- Red build → `git revert` (keep history) or turn the pass off with a flag. Never amend or reset. Tag green checkpoints `cp1`…`cp5`. Ship the last tag.
- Escalate to the human per BUILD_PLAN §6, plus: the red-team and the builder disagree on the rubric (Q1/Q2), or recall drops after an evaluator change.

**Testing the tester**
- *Seeded mutants:* about 12 optimizers that wrap `cat` + one sed-style mutation. Each one's failure needs specific data: drop `NULLEQ`, `IS`→`EQ`, drop the last sort key (ties), `ASC`→`DESC`, push a filter below a DIV (introduces an error), trust `stats.min` to drop a check, GATHER off-by-one on the last row, swap 1.0/1.00, drop a dead-looking instruction whose error matters (should *not* be flagged).
- *Held-out mutants:* a second red-team session writes 4–6 mutants that the evaluator's builder never sees. Report recall on those separately. This is the honest number.
- *Equivalent mutants (precision):* identity, an unsorted-output shuffle, HJOIN↔NLJOIN, a NUM rescale, and garbage output when the original errors. All must exit 0. Target 0 false alarms over 10 seeds.
- *Recall/precision table* in each report: caught/total mutants (seeded and held-out), false alarms per run, median and max time-to-detect.
- *Golden repros:* each defect found (from a mutant or the real optimizer) is shrunk to the smallest (program, data) and saved under `tests/regressions/`. They replay first on every run, and each one must still fail on its mutant.
- *Determinism:* same seed gives an identical report hash. 10 seeds on the real optimizer give the same verdict. Run once with `-j1` and once with `-j16` to catch timeouts caused by load (allow a timing margin, e.g. re-time once before flagging a timeout).
- *Independence:* the evaluator never imports `optimizer/` (enforce with a grep check in `run_eval.sh`). It has its own small parser for its program mutator. Only bin/minivm and the CLI cross the boundary.

**Anti-overfitting**
- Score the optimizer on generated held-out programs separately from q1–q8. Ban matching on literal register or table names.
- Data generator: base its distributions on the constraints and deliberately ignore stats (wider ranges, other distinct counts).

**Budget, logging, stopping**
- Budget for each iteration: ≤15 min wall time and ≤1 token-budget unit (track with `/usage` per session in `notes/AI_USAGE.md`). If an iteration overruns twice, cut down per BUILD_PLAN §10.
- `notes/runs.jsonl`: one line per eval run (sha, seed, defects, recall, false alarms, geomean, wall time). `PROGRESSION_LOG.md`: one entry per iteration (tried / result / learned / keep-revert).
- Stop when the BUILD_PLAN §6 success criteria are met **and** held-out mutant recall is 100%, false alarms are 0 over 10 seeds, and the evaluator runs in under 60 s with `-j4` (the grader's machine may be smaller).
- Save the raw session files of every subagent role (orchestrator, builder, red-team, reviewer) to `ai-sessions/`, and their prompts to `prompts/`.
