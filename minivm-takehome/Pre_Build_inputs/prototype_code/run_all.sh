#!/bin/sh
# Regenerate test data and run every prototype check. Usage: prototype_code/run_all.sh
set -e
cd "$(dirname "$0")"
echo "== generate data (deterministic seeds)"
python3 optimizer_agent/make_adv_data.py 6 >/dev/null
python3 optimizer_agent/gen_data.py | tail -1
echo "== check.py: hand-optimized programs vs originals on every dataset"
python3 optimizer_agent/check.py | tail -1
echo "== tricky_checks.py: comparator / order / VM rules"
python3 evaluator_agent/tricky_checks.py | tail -1
echo "== eval-proto.py on identity, hand-optimized, known-bad optimizers"
for o in ../tools/identity_opt.sh optimizer_agent/hand_opt.sh optimizer_agent/naive_opt.sh; do
  printf '%-34s ' "$o"; python3 evaluator_agent/eval-proto.py "$o" --quiet | tail -1 || true
done
echo "== meta_eval.py: evaluator vs 19 fake optimizers"
python3 evaluator_agent/meta_eval.py | tail -1
