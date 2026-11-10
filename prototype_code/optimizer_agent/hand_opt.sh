#!/bin/sh
# Test optimizer: prints the hand-optimized qNNNN.opt.mini for a known example, else the input.
d=$(dirname "$0"); q=$(basename "$1" .mini)
[ -f "$d/$q.opt.mini" ] && cat "$d/$q.opt.mini" || cat "$1"
