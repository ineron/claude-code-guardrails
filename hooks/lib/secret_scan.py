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
"""
import json
import os
import re
import shlex
import sys


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

# Content-based check, shared by both the Bash and Read paths below: flags
# anything shaped like a live key regardless of which file it's sitting in.
SECRET_VALUE_RE = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{20,}"
    r"|sk-proj-[A-Za-z0-9_-]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|ANTHROPIC_(API_KEY|AUTH_TOKEN)[\"' ]*[:=][\"' ]*[A-Za-z0-9._-]{16,}"
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
