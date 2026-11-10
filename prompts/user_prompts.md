# User prompts (in order)

## 1. 2026-11-10T19:50:14.803Z

Can you push this folder into this repository ? https://github.com/sfc-gh-skodi/assessment_fde

## 2. 2026-11-10T19:52:31.471Z

https://github.com/sfc-gh-skodi/assessment_fde the repository is public now, search again

## 3. 2026-11-10T19:55:00.605Z

! gh auth login

## 4. 2026-11-10T19:56:00.888Z

You should be able to push now

## 5. 2026-11-10T19:59:40.777Z

Can we activate PR-Sheperd for this repo as well

## 6. 2026-11-10T20:02:17.347Z

here is a document outlining PR shpered : https://docs.google.com/document/d/1Wp4-6C628I8tFjgH2sji0oPahoEGONsrFJE15quSFGU/edit?tab=t.0#heading=h.23t18gkvusyr. Activate that in this repo

## 7. 2026-11-10T20:05:08.911Z

here is a prompt to achieve our goal : /Users/skodi/Desktop/take-home-assessment/notes/INITIAL_PROMPT.md
Take your time to do the research to come up with a efficient, scalable, easy to test and iterate plan to achieve our goal

## 8. 2026-11-10T20:37:10.845Z

You are overthinking the solution

## 9. 2026-11-10T20:42:27.079Z

let-s force push to remove binaries

## 10. 2026-11-10T20:44:00.090Z

ELi5 in 1-2 sentence if the easy/medium/hard case are from the exmaples folder only. If yes, how do we plan to tackle real life examples because these exampel,s are simple

## 11. 2026-11-10T20:45:27.983Z

Have you run all 8 exmaple programs with bin.minivm? for each you can note what it computes, its cycles and where it wastes work and save in notes/examples.md

## 12. 2026-11-10T20:50:22.442Z

okay now use 3 subagents to research the following : each subagent reads the one-pager and docs/ and returns a short list _ findings, risks and recommendaitons 
Optimizer : Which rewrite would save the most cycles, which are risky, how to tackle them
Evaluator : what the the industry best pracices for eval method for assembly code optimizaitons, how do we prove an optimizer is wrong under 2 minutes and how do we avoid flagging a correct one 
Working model : how should the agents work together in a orchestrator-evaluator loop ( build and check loop) and how to test the tester. 
Save each result to notes/, then commit

## 13. 2026-11-10T21:02:55.492Z

Not yet, did you write a faster version for the 8 exmaples by hand? if yes save them in prototype_code/optimizer_agent/ as opt.mini., also have a cmp.py that runs the two programs on the same data and shows the #cycles and if the results mathc. You could use this cmp.py in the test suite eval runs aswell . use bin/minivm and relative paths

## 14. 2026-11-10T21:09:13.081Z

Now add some tricky cases where you introduce nulls, duplicates, ties, empty tables, weird symbols, randome strings etc. Test with small/medium/large datasets aswell and write a check script to test a faster version against every dataset : if the faster version gives a different answer : save the model as naive.mini and fix the real one : this is provide you baselines as well if you haven't odne that

## 15. 2026-11-10T21:16:51.562Z

Can you build a protoype evaluator eval-proto.py. The evaluator runs the optimiser on each of the examples and ensure all the evl constraints are satisfied : compared numbers within 1e-6, exists 1 if any result differes, 0 if not, compares rows as a multiset, also print out : checked, skipped, defects, time

## 16. 2026-11-10T21:19:07.106Z

now test this evlauator on some fake optimizer programs that are a good mix of buggy and honest ones which should not be flagged. Run the evla on each and output caught/missed with evidence for each miss

## 17. 2026-11-10T21:25:23.893Z

Add this rule : Row order: comparing as a multiset, as you asked, means it won't catch an optimizer that breaks the output order of a program that SORTs. The plan's default is to compare order whenever the original sorts, so that rule still needs adding.

## 18. 2026-11-10T21:27:04.151Z

Now check for more tricky rules tha you can think of like what would have if we see sort and SORT in the program, if date,str and num are all print as text, if calling platofrm binary is faster than bin/minivm wrapper, what happens if the data is empty etc . THink of more on your end

## 19. 2026-11-10T21:32:21.702Z

now package the prototype-code folder and add a readme whch highlights what each file does, how to run it and what we learnt from our quick experiments. Delete any other uneccesary folder. Commit the changes

## 20. 2026-11-10T21:40:01.568Z

Now rewrite the BUILD_PLAN.md using everything in notes/ and prototype_code/ and add the following : 
1. Status tbale : what is build and what still needs to be build 
2. What the examples were hiding : learnings frrom hand optimized cycles 
3. Safety rules : ways in which a rewirite could give wrong outputs : give evidence with citations from docs 
4. Comparison on eval methods : run-compare vs normalize vs math proof or any others you thought of 
5. How to tackle unclear rules/ assumptions made 
6. How the agents talks , results /outputs formats : try using structures like json/xml instead if paragraphs

## 21. 2026-11-10T21:44:32.426Z

Commit this new plan

## 22. 2026-11-10T21:48:17.009Z

Can you create an html file giving me the mental model of what we did step by step in this session and save the prompts, agents' raw session files, and git history for this session . Donot save any binary files
