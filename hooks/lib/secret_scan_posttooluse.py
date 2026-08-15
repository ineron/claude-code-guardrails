#!/usr/bin/env python3
"""PostToolUse guard: warn when a tool's completed output contains a live
secret, for the cases PreToolUse can't prevent.

PreToolUse (secret_scan.py) can only pre-scan output it can predict ahead of
time — a file path, a resolvable pm2 log file. Commands like `docker logs`,
`kubectl logs`, `journalctl`, or `curl` against some endpoint can print
anything, including a secret an app logged or returned, with no filename or
keyword in the command text to key off. There is no way to block or redact
that after the fact — by the time PostToolUse fires the tool "already ran"
and its output is already in the model's context — so this hook cannot undo
the exposure. What it can do: detect it immediately and push a warning back
so the user is told to rotate the key without depending on the model
noticing on its own.

Scans the entire hook payload (not just an assumed tool_response.stdout
field) since PostToolUse's exact per-tool output shape isn't guaranteed
stable across Claude Code versions — recursing over every string value is
robust to that in a way hardcoding a field path would not be.
"""
import json
import re
import sys

SECRET_VALUE_RE = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{20,}"
    r"|sk-proj-[A-Za-z0-9_-]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|ANTHROPIC_(API_KEY|AUTH_TOKEN)[\"' ]*[:=][\"' ]*[A-Za-z0-9._-]{16,}"
)


def find_secret(obj):
    if isinstance(obj, str):
        return SECRET_VALUE_RE.search(obj)
    if isinstance(obj, dict):
        for v in obj.values():
            m = find_secret(v)
            if m:
                return m
        return None
    if isinstance(obj, list):
        for v in obj:
            m = find_secret(v)
            if m:
                return m
        return None
    return None


try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

match = find_secret(data.get("tool_response", data))
if not match:
    sys.exit(0)

warning = (
    "SECRET EXPOSURE DETECTED: this tool's output contains what looks like "
    f"a live API key/secret ({match.group(0)[:10]}...redacted). It has "
    "already entered this session's context and transcript history. Tell "
    "the user right now that this key must be treated as compromised and "
    "rotated — do not wait to be asked, and do not repeat the full value "
    "again in your reply."
)

print(json.dumps({"systemMessage": warning}))
print(warning, file=sys.stderr)
sys.exit(2)
