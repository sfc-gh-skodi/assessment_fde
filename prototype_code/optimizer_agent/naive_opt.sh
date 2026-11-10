#!/bin/sh
# Known-bad test optimizer: prints the wrong-but-fast qNNNN.naive.mini, else the input.
d=$(dirname "$0"); q=$(basename "$1" .mini)
[ -f "$d/$q.naive.mini" ] && cat "$d/$q.naive.mini" || cat "$1"
