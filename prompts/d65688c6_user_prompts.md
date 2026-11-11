# User prompts (in order)

Session `d65688c6-2dd5-4500-a93d-ca38d871240b` · MiniVM Program Optimizer

prompts: 1

## 1. 2026-11-11 01:38:47 UTC

You're continuing a build in /Users/skodi/Desktop/take-home-assessment.

THE GAME
We have a tool, ./optimize, that takes a MiniVM program and prints a faster version of it.
"Faster" means it costs fewer cycles. The answer must always stay exactly the same,
on any data that fits the schema. A wrong answer is much worse than a slow one.

WHAT'S ALREADY THERE
- optimizer/ir.py       reads the program and gives every value its own name
- optimizer/analyze.py  puts a label on every value (which table, which rows, its type, can it be NULL, is it sorted)
- optimizer/passes.py   the rewrite rules. So far: throw away unused work, and do repeated work once
- optimizer/cost.py     a price list, so we can tell whether a change made things cheaper
- optimizer/main.py     runs it all. If anything looks wrong, it prints the original program unchanged
Today: 0 wrong answers, about 1.1x faster. Hand-made fast versions reach about 3x.
Read minivm-takehome/docs/ for how each instruction works and what it costs.
prototype_code/optimizer_agent/*.opt.mini are good examples; *.naive.mini are examples of mistakes.

YOUR JOB: add ONLY these 4 rules to optimizer/passes.py, one at a time
1. Don't carry every column through every step.
   GATHER(GATHER(s,i),j) becomes GATHER(s, GATHER(i,j)); the leftover gathers then get thrown away.
2. Filter first, then do the work.
   If a label or string is built for every row and then most rows are filtered out,
   build it after the filter instead. Only do this when the filter keeps each row at most once.
3. Don't sort what's already sorted.
   If the table says it's stored sorted by those columns, and the rows are still in stored order, the SORT does nothing.
4. Don't do pointless work.
   Remove a SORT that only feeds GALL totals (GSUM / GCOUNT / GCOUNTV).
   Use HJOIN instead of NLJOIN when the price list says it's cheaper.
Stop after these 4. Don't start anything else.

SAFETY RULES
- Never make the program do something that could crash (for example DIV) on rows it didn't touch before.
- Keep the output rows in exactly the same order.
- Use table stats only to guess cost. Never use them to decide what's correct.
- Never match on program names. The rules must work on programs we've never seen.
- Python standard library only; must run on Python 3.8.

HOW TO WORK (repeat for each rule)
1. Write the rule.
2. Run:  python3 tools/loop.py
   About 20 seconds. It checks all our test programs and prints any wrong answers.
3. If there's a wrong answer, fix the rule or switch it off before doing anything else.
   Copy the failing program into tests/regressions/ so it gets checked forever.
4. When it's clean, run:
   python3 tools/loop.py --gate 1 --log <N> "<what you did, in words a 5-year-old gets>" "<what you learned, under 5 sentences>"
   This runs the full check and adds a row to progress.md.
5. Commit that one rule by itself.

WHEN YOU'RE DONE
Run:  python3 tools/loop.py --gate 1,2,3
Then tell me: wrong answers (should be 0), speedup per test tier, and the slowest optimizer time.
