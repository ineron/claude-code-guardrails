#!/bin/bash

INPUT="$(cat)"

SESSION_ID="$(printf '%s' "$INPUT" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get("session_id") or "unknown")
except Exception:
    print("unknown")
')"

STATE_DIR="$HOME/.claude/hooks/state/heartbeat"
mkdir -p "$STATE_DIR"
COUNT_FILE="$STATE_DIR/${SESSION_ID}.count"

N=1
if [ -f "$COUNT_FILE" ]; then
    N=$(( $(cat "$COUNT_FILE") + 1 ))
fi
echo "$N" > "$COUNT_FILE"

TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S %Z')"

N="$N" TIMESTAMP="$TIMESTAMP" python3 -c '
import json, os

n = os.environ["N"]
ts = os.environ["TIMESTAMP"]
ctx = (
    f"session-heartbeat: turn #{n} at {ts}. "
    f"End your reply with the line \"⏱ turn #{n} · {ts}\" verbatim "
    f"(copy these exact values, never invent your own time or number). "
    f"If a recent reply of yours is missing this line, that means context or "
    f"earlier instructions were lost mid-session — say so explicitly instead "
    f"of silently continuing."
)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}))
'
