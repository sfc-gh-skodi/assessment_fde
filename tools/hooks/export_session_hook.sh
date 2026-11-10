#!/usr/bin/env bash
# Cortex Code hook (Stop + SessionEnd): export the current session's record into this repo.
#
# Registered in ~/.snowflake/cortex/hooks.json. Cortex Code pipes a JSON payload on stdin
# with session_id and cwd. The hook only acts when the session's working directory is
# inside this repo, so sessions for other projects are never touched. Exports are keyed
# by session id (see tools/export_session.py), so each session gets its own files and
# nothing is overwritten. It skips git-history/ (--no-git) so commits don't create churn;
# refresh that by running the exporter yourself before the final commit. It never commits
# or pushes, prints nothing to stdout, and always exits 0, so it cannot block or alter a turn.

REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
LOG="$HOME/.snowflake/cortex/logs/export_session_hook.log"
LOCK="${TMPDIR:-/tmp}/export_session_hook.lock"
mkdir -p "$(dirname "$LOG")"

INPUT=$(cat)
read -r SID CWD EVENT < <(printf '%s' "$INPUT" | python3 -c '
import json, sys
try: d = json.load(sys.stdin)
except Exception: d = {}
print(d.get("session_id") or "-", d.get("cwd") or "-", d.get("hook_event_name") or "-")' 2>/dev/null)

[ -z "$SID" ] || [ "$SID" = "-" ] && exit 0
CWD_REAL="$(cd "$CWD" 2>/dev/null && pwd -P)" || exit 0
case "$CWD_REAL/" in "$REPO"/*) ;; *) exit 0 ;; esac

# one export at a time (two sessions may end turns together); skip if busy
mkdir "$LOCK" 2>/dev/null || exit 0
trap 'rmdir "$LOCK"' EXIT
{
  echo "[$(date -u +%FT%TZ)] $EVENT $SID"
  python3 "$REPO/tools/export_session.py" --no-git "$SID" 2>&1 | tail -1
} >> "$LOG" 2>&1
exit 0
