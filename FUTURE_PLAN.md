# What I would do with a few days and unlimited compute and tokens

## Where things stand

- **Optimizer** (`optimizer/`): reads the program, gives every register a unique name, applies safe rewrites, and keeps the result only if the price list says it's cheaper. On any doubt it prints the input unchanged. Suite speedup 1.30×, `./evaluate` speedup 1.75×, 0 wrong answers (`progress.md`).
- **Evaluator** (`evaluator/`, `./evaluate`): makes lots of random but legal tables and programs, runs the original and the optimized program, and compares the answers. It caught 36/36 planted bugs with 0 false alarms (`runs/meta_report.md`).
- **Held-out check** (10 trap cases built outside the build sessions; not in this package): 10/10 correct, cycles ratio 0.730. Three cases came back at 1.000 (no speedup), because no rule matched them.

**Lesson so far:** correctness is solid. The remaining speed is in rules that handle NULLs carefully and in rewrites that span several instructions.

## 1. Optimizer

- **Choose the join order by cost, and say why.** Try the possible join orders, price each one, and pick the cheapest. Write a short note next to the output explaining the choice, e.g. "filter `lines` first: 86 → 12 rows before the join, saves ~1,400 cycles". The note goes to a side file, not the program output.
- **Let all rewrites compete at once.** Today the rules run one after another, so an early rule can block a better one later. Instead, keep every equal version of the program the rules produce and pick the cheapest at the end (an "e-graph"). There is a time limit, and the program is printed unchanged if anything goes wrong.
- **More rules, each with a buggy twin.** Every new rule comes with a deliberately wrong version: the tempting shortcut that breaks on NULLs, ties, empty tables or errors. The evaluator must pass the rule and catch the twin, or the rule doesn't go in. First rules to add:
  - A NULL-aware filter simplifier: `x OR NOT x` becomes "x is not NULL", and comparisons that the schema guarantees fold away.
  - Self-join + group → drop NULL keys, then group.
  - Sort + slice → TOPK, keeping every tie-breaker.
  - Remove a join only when the schema's keys and refs prove it's safe, never because of stats.
  - Push unused columns out before joins.
- **The optimizer checks its own work.** Before printing, it checks its output against the input in two ways: a solver proof for the parts it can model, and a quick run on small tricky tables (all NULL, empty, duplicate keys, edge values). If either fails, it drops that rewrite.
- **A real price list.** Fit the cost model to cycles measured with `bin/minivm` on thousands of programs, so "is this cheaper?" uses real numbers.

## 2. Evaluator

- **Data that aims at the gaps.** Write a small Python version of MiniVM (checked against `bin/minivm`; today `evaluator/vm.py` only runs the binary). Use it to record which tricky situations each dataset reaches: NULL inputs per instruction, empty groups, ties at a cut-off, NULL join keys, divide by zero, `''` vs `'  '`, Unicode. Then generate data aimed at the situations nothing has reached yet.
- **An automated red team.** A separate agent writes believable but wrong optimizers. Any one that slips past the evaluator shows a hole, so we fix the evaluator and keep that fake as a permanent test.
- **More golden-style traps.** More cases like the held-out set, each with friendly data where the trap passes, tricky data where it fails, a control dataset, a wrong rewrite that must be flagged, and a correct rewrite that must pass.
- **Nightly runs at scale.** Every night, run thousands of seeds over the whole suite, all traps and the fake-optimizer tests. Each failure is shrunk to the smallest example that still fails, and a report tracks wrong answers, speedup, coverage and red-team catch rate over time.

## 3. Extreme scale tests

`BUILD_PLAN.md` calls for separate near-limit stress cases, kept out of the normal test run. I'd build them out fully:

- **Very long programs:** programs near the instruction limit (20k+ lines). The optimizer must finish within its time limit (under 1 s) or fall back cleanly.
- **Big tables:** row counts near the VM's limits, to check rewrites don't push a program over the work limit. For example, swapping a hash join for a nested-loop join can blow the limit even though it gives the same answer.
- **Many registers:** programs that use a very large number of registers at once.
- **Worst-case fan-out:** joins and groups where one key matches huge numbers of rows.
- **Evaluator under load:** check that a full evaluator run still finishes within its 2-minute budget at these sizes, and that its watchdog stops a stuck run.

Each stress case records size, optimizer time, cycles before and after, and whether it fell back.

## 4. Cost analysis

- **Cycles:** per program and per rule, how many cycles each rule saves. Rules that save almost nothing get removed to keep the optimizer simple.
- **Optimizer time:** time per pass on small, normal and huge programs, so we know which rules get slow as programs grow.
- **Evaluator time:** time per check, so the 2-minute budget is spent where bugs are most likely.
- **AI spend:** credits per phase and per agent, from Snowflake's Cortex Code usage history (see `AI_USAGE.md`). Planning used extra-high thinking where medium would have done, so the next round sets thinking effort per task: high only for hard reasoning, medium or low for routine work.

## 5. Failure-mode tests

Each failure from `BUILD_PLAN.md` §10 gets its own test that must keep passing:

| What can go wrong | Test that catches it |
|---|---|
| A rewrite breaks NULL handling | NULL-heavy data and NULL-bug fakes |
| A rewrite adds an error (e.g. divide by zero) | fakes that move a division above its filter |
| Row order or ties get lost | order- and tie-aware comparison, and fakes that reverse or drop tie-breakers |
| The evaluator is too lenient | the planted-bug fakes must all be caught |
| The evaluator is too strict | the honest fakes must all pass |
| Types get confused (BOOL vs INT, 1.0 vs 1.00) | strict typed comparison tests |
| Stats get used for correctness | data that deliberately breaks the stats |
| A rewrite blows the VM work limit | near-limit stress cases (section 3) |
| The optimizer is too slow on huge programs | 20k-line stress programs with a time limit |
| The evaluator runs past 2 minutes | wall time in every report, plus a watchdog |
| Overfitting to the 8 examples | held-out generated programs and the rotating held-out set |
| The same bug in both optimizer and evaluator | separate code, and a check that they share none |

## 6. The three loops

1. **Optimizer against evaluator.** Agents build one group of rules each. Every change runs the evaluator and the traps. A wrong answer sends it back with the smallest failing example. A pass is kept only if the speedup holds.
2. **Evaluator against the validation set.** The evaluator is itself tested: it must catch every buggy fake (including every rule's twin and the red team's new fakes) and pass every honest one. If the evaluator misses bugs, loop 1 means nothing.
3. **Held-out set rebuilt when a case is burnt.** The held-out set is only run at checkpoints, and the agents building rules never see it. Once anyone studies a case (as three were in the test session), it is "burnt": it moves into the public tests, and a fresh agent with no memory of the build writes a new case for the same kind of trap. That keeps the headline number honest.

Fresh-context reviewer agents check each rule against the docs before it goes in.

## 7. Rules for merging a change

- 0 wrong answers on `./evaluate` (several seeds), the test suite, every trap and the stress cases.
- Every new rule's buggy twin is caught, and the self-check is on.
- Fake-optimizer tests: every buggy one caught, no false alarms.
- No test group gets slower; the optimizer stays within its time limit.
- One commit per rule, with a plain-English row in `progress.md`.

## What I would not do

- Hard-code answers for known programs. It would raise the held-out score but prove nothing about new programs.
- Use table stats for anything but cost. Stats describe friendly data, and the traps show that rules relying on them break on legal data.
