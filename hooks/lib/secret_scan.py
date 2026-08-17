#!/usr/bin/env python3
"""PreToolUse guard for Bash and Read: deny actions that would print secret
material or pull it into the model's context.

Reads a Claude Code hook payload from stdin and, if the Bash command or Read
file_path looks like it would expose a secret, prints a `permissionDecision:
deny` hook response and exits 0 (matching Claude Code's hook contract:
allow/deny is communicated via JSON output, not via exit code). Prints
nothing and exits 0 to allow.

Read is covered for a reason distinct from Bash: by the time a secret value
enters the model's context (as a Read result), it has already left the
workspace as part of the request to the API — whether or not the model goes
on to repeat it in a visible reply. There is no hook that can intercept or
redact the model's own response text (Claude Code streams it), so the only
enforceable boundary is upstream, at the tool call that would read the
secret into context in the first place.

`pm2 logs <app>` gets the same upstream treatment even though it isn't a
file read: it replays a managed process's log files, which the hook
resolves itself via `pm2 jlist` and pre-scans before allowing the command.

`pm2 jlist` / `pm2 describe` / `pm2 show` get similar treatment for a
different reason: their JSON output includes each process's full `pm2_env`
block verbatim, which is however that process was launched — env vars,
secrets included, with no redaction. There's no file to resolve here (the
command's own output *is* the dump), so instead the hook runs `pm2 jlist`
itself (read-only) and pre-scans the resulting JSON before allowing the
original command through.

Other output-dumping commands (docker logs, kubectl logs, curl, journalctl,
...) aren't pre-scanned this way — there's no generic way to resolve "what
file/stream will this print" ahead of running it — so they're instead
covered reactively by secret_scan_posttooluse.py, which can't stop the
output but does surface an immediate warning once it's out.
"""
import json
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from secret_patterns import SECRET_VALUE_RE  # noqa: E402


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


try:
    data = json.load(sys.stdin)
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
except Exception:
    sys.exit(0)

# Secret file names / patterns. .env.example is intentionally NOT protected.
PROTECTED_FILE_RE = re.compile(
    r"""(^|[/\s"'])(\.env($|[^a-zA-Z0-9_.-])"""
    r"""|\.env\.(local|production|prod|development|dev|staging|stage|test)([^a-zA-Z0-9_.-]|$)"""
    r"""|\.pgpass([^a-zA-Z0-9_.-]|$)"""
    r"""|id_rsa([^a-zA-Z0-9_.-]|$)"""
    r"""|id_ed25519([^a-zA-Z0-9_.-]|$)"""
    r"""|credentials\.json([^a-zA-Z0-9_.-]|$)"""
    r"""|service-account[^/\s]*\.json([^a-zA-Z0-9_.-]|$)"""
    r"""|[^/\s]+\.(pem|key)([^a-zA-Z0-9_.-]|$))""",
    re.IGNORECASE,
)

if tool_name == "Read":
    file_path = tool_input.get("file_path", "")
    if not file_path:
        sys.exit(0)
    path = os.path.expanduser(file_path)

    if PROTECTED_FILE_RE.search(path):
        deny(
            f"BLOCKED: '{path}' is a protected secrets file (.env, .pgpass, "
            "private key, credentials, etc.). Do not read it with the Read "
            "tool. Use the application/database client that consumes the "
            "credentials instead."
        )

    if os.path.isfile(path):
        try:
            with open(path, "r", errors="ignore") as f:
                content = f.read(200_000)
        except Exception:
            content = ""
        if content and SECRET_VALUE_RE.search(content):
            deny(
                f"BLOCKED: '{path}' contains what looks like a live API "
                "key/secret (Anthropic key/token or similar). Do not read "
                "it with the Read tool. If you need to edit the file, use "
                "the Edit tool with a targeted old_string/new_string that "
                "never requires the secret value to appear in your context; "
                "to check presence, use 'grep -c PATTERN file' instead."
            )
    sys.exit(0)

command = tool_input.get("command", "")

if not command:
    sys.exit(0)

if PROTECTED_FILE_RE.search(command):
    deny(
        "BLOCKED: This command references a protected secrets file (.env, "
        ".pgpass, private key, credentials, etc.). Do not attempt to read, "
        "grep, cat, copy, encode, parse, or otherwise inspect these files. "
        "Use the application/database client that consumes the credentials "
        "instead."
    )

# `pm2 logs <app>` (and `pm2 log`) replay a managed process's accumulated
# stdout/stderr, which commonly includes DEBUG-level output an app never
# meant to expose (e.g. a credentials dict logged verbatim). Unlike the
# checks above, there's no filename or env-dump keyword in the command text
# to key off — the file pm2 reads from is resolved internally. So instead we
# resolve it ourselves via `pm2 jlist` (read-only) and pre-scan the same log
# files pm2 would print from, before allowing the command through.
PM2_LOGS_RE = re.compile(r"(?:^|[;&|]\s*)pm2\s+(logs|log)\b")

if PM2_LOGS_RE.search(command):
    try:
        cmd_tokens = shlex.split(command, posix=True)
    except ValueError:
        cmd_tokens = command.split()

    app_arg = None
    for i, tok in enumerate(cmd_tokens):
        if tok in ("logs", "log") and i > 0 and cmd_tokens[i - 1] == "pm2":
            for nxt in cmd_tokens[i + 1:]:
                if not nxt.startswith("-"):
                    app_arg = nxt
                break
            break

    try:
        jlist_out = subprocess.run(
            ["pm2", "jlist"], capture_output=True, text=True, timeout=5,
        ).stdout
        procs = json.loads(jlist_out)
    except Exception:
        procs = None  # pm2 unavailable/unparseable: fail open, allow through

    if procs:
        log_paths = set()
        for proc in procs:
            name = proc.get("name", "")
            pm_id = str(proc.get("pm_id", ""))
            if app_arg and app_arg not in (name, pm_id):
                continue
            env = proc.get("pm2_env", {}) or {}
            for key in ("pm_out_log_path", "pm_err_log_path"):
                p = env.get(key)
                if p and os.path.isfile(p):
                    log_paths.add(p)

        for path in log_paths:
            try:
                size = os.path.getsize(path)
                with open(path, "r", errors="ignore") as f:
                    f.seek(max(0, size - 500_000))
                    content = f.read()
            except Exception:
                continue
            if SECRET_VALUE_RE.search(content):
                deny(
                    f"BLOCKED: recent output of pm2-managed log '{path}' "
                    "contains what looks like a live API key/secret. "
                    "'pm2 logs' would print it straight into this session. "
                    "Fix the app to redact secrets before logging them, "
                    "restart the pm2 process so the fix is live, then retry. "
                    "To check without printing the value, use something "
                    "like 'grep -c PATTERN file'."
                )

# `pm2 jlist` / `pm2 describe <app>` / `pm2 show <app>` print each managed
# process's pm2_env block, which is that process's actual environment —
# secrets included — as plain JSON, no redaction. Unlike pm2 logs there's no
# separate log file to pre-scan: the command's own output is the dump. So we
# run `pm2 jlist` ourselves (read-only) and scan it before allowing the
# original command through.
PM2_ENV_DUMP_RE = re.compile(r"(?:^|[;&|]\s*)pm2\s+(jlist|describe|show|env)\b")

if PM2_ENV_DUMP_RE.search(command):
    try:
        jlist_out = subprocess.run(
            ["pm2", "jlist"], capture_output=True, text=True, timeout=5,
        ).stdout
    except Exception:
        jlist_out = ""  # pm2 unavailable: fail open, allow through

    if jlist_out and SECRET_VALUE_RE.search(jlist_out):
        deny(
            "BLOCKED: this pm2 command would print a process's pm2_env "
            "block, which contains what looks like a live API key/secret "
            "in that process's environment. 'pm2 jlist'/'describe'/'show' "
            "dump env vars with no redaction. If you only need process "
            "state, filter to specific safe fields instead, e.g. "
            "\"pm2 jlist | jq '.[] | {name, pm_id, status: .pm2_env.status, "
            "pid}'\"."
        )

# Commands that dump an Anthropic key/token env var directly (echo
# $ANTHROPIC_API_KEY, printenv, env | grep anthropic, export | grep ..., etc.)
# rather than reading a file. Deliberately crosses pipe/&&/; boundaries (e.g.
# "printenv | grep -i anthropic_api_key") since the value still ends up
# printed either way.
ENV_DUMP_RE = re.compile(
    r"\b(echo|printf|printenv|env|export|declare)\b[\s\S]*(anthropic_api_key|anthropic_auth_token)",
    re.IGNORECASE,
)

if ENV_DUMP_RE.search(command):
    deny(
        "BLOCKED: This command would print an Anthropic API key/auth token "
        "env var to output. Never echo/print live keys — check for presence "
        "(e.g. env var is set: yes/no) without printing the value."
    )

# Content-based check: if the command references an existing file, and that
# file's content contains something shaped like a live API key/secret, block
# regardless of filename (catches things like ~/.claude/settings.json that
# aren't secret by name but have ended up with a live key pasted into them).
try:
    tokens = shlex.split(command, posix=True)
except ValueError:
    tokens = command.split()

candidates = set()
for tok in tokens:
    tok = tok.strip("\"'")
    if not tok or tok.startswith("-"):
        continue
    path = os.path.expanduser(tok)
    if os.path.isfile(path):
        candidates.add(path)

for path in candidates:
    try:
        with open(path, "r", errors="ignore") as f:
            content = f.read(200_000)
    except Exception:
        continue
    if SECRET_VALUE_RE.search(content):
        deny(
            f"BLOCKED: '{path}' contains what looks like a live API "
            "key/secret (Anthropic key/token or similar). Do not "
            "cat/print/grep/copy its contents. To edit the file, use the "
            "Edit tool with a targeted old_string/new_string that never "
            "requires printing the secret value; to check presence, use "
            "something like 'grep -c PATTERN file' instead of printing "
            "matches."
        )

sys.exit(0)
