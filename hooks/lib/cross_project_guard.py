#!/usr/bin/env python3
"""PreToolUse guard for Edit/Write/NotebookEdit/Bash: deny actions whose
target path resolves inside a *different* registered Claude Code project,
so a session working in project A can't reach into project B's files
directly instead of going through B's own session (message/task, or the
user).

"Registered" is defined purely by filesystem convention: a directory is a
project root if it (or an ancestor) contains .claude/settings.json with a
non-empty project.slug. Nothing richer is available to a hook running
outside any particular session's MCP context -- e.g. the memory-bank-mcp
project's own Postgres schema stores slugs but never filesystem paths (see
its schema.sql), so per-project settings.json is the only place slug<->path
is resolvable at all. This also means the guard works standalone for any
project using this settings.json convention, not just memory-bank-mcp
projects: if a path has no such marker anywhere above it, it isn't
considered "another project" and the guard allows it (fails open).

Bash is classification-based, not a blanket path check: a command is only
denied if it looks write-shaped (redirects, or one of a fixed list of
mutating verbs/editors) AND references a path under a foreign project.
Read-only commands (cat, grep, ls, git log/diff/status, ...) are allowed
through even when they reference a foreign project's files -- this guard
enforces "don't edit it directly", not "don't look at it".

Reads a Claude Code PreToolUse payload from stdin. Prints a
permissionDecision: deny JSON and exits 0 if blocked. Prints nothing and
exits 0 to allow.
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


def project_slug_at(path: str):
    """Nearest ancestor (inclusive) of `path` with .claude/settings.json
    carrying a non-empty project.slug. Returns (slug, project_root) or
    (None, None)."""
    cur = os.path.abspath(path)
    if os.path.isfile(cur):
        cur = os.path.dirname(cur)
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        settings_path = os.path.join(cur, ".claude", "settings.json")
        if os.path.isfile(settings_path):
            try:
                with open(settings_path) as f:
                    data = json.load(f)
                slug = (data.get("project") or {}).get("slug")
                if slug:
                    return slug, cur
            except Exception:
                pass
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None, None


try:
    payload = json.load(sys.stdin)
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    session_cwd = payload.get("cwd") or ""
except Exception:
    sys.exit(0)

if session_cwd and os.path.isdir(session_cwd):
    try:
        os.chdir(session_cwd)
    except Exception:
        pass

home_slug, home_root = project_slug_at(os.getcwd())
if not home_slug:
    # This session's own directory isn't a registered project either --
    # nothing to enforce a boundary against.
    sys.exit(0)


def check_path(raw_path: str) -> None:
    if not raw_path:
        return
    resolved = os.path.abspath(os.path.expanduser(raw_path))
    slug, root = project_slug_at(resolved)
    if slug and slug != home_slug:
        deny(
            f"BLOCKED: '{resolved}' belongs to a different registered "
            f"Claude Code project ('{slug}', root {root}) -- this session "
            f"is '{home_slug}'. Do not edit another project's files "
            "directly, even if you have filesystem access to them. If this "
            "repo uses the memory-bank MCP, use message_send(to_project="
            f"\"{slug}\", kind=\"ask\" or \"fyi\", ...) for a question/"
            "notice, or memory_upsert(project=\""
            f"{slug}\", kind=\"task\", filed_from_project=\"{home_slug}\", "
            "...) for an actual work item -- that project's own session "
            "decides what to do with it, the same way this session gets to "
            "decide for itself. Otherwise, stop and ask the user directly "
            "for explicit confirmation before touching that project."
        )


if tool_name in ("Edit", "Write"):
    check_path(tool_input.get("file_path", ""))

elif tool_name == "NotebookEdit":
    check_path(tool_input.get("notebook_path", ""))

elif tool_name == "Bash":
    command = tool_input.get("command", "")
    if command:
        candidate_paths = []

        # Redirect targets (> / >>) are inherently a write, regardless of
        # the command name in front of them.
        for m in re.finditer(r'(?:>>|>)\s*([^\s;&|]+)', command):
            candidate_paths.append(m.group(1).strip("\"'"))

        WRITE_VERB_RE = re.compile(
            r"\b("
            r"sed\s+-i|tee|cp|mv|rm|rmdir|mkdir|touch|chmod|chown|ln|rsync|"
            r"patch|dd|truncate|"
            r"vim|vi|nvim|nano|emacs|code|subl|"
            r"git\s+(?:add|commit|checkout|reset|rebase|merge|push|apply|"
            r"stash|rm|mv)|"
            r"npm\s+(?:install|uninstall|link|ci)|pip3?\s+install|"
            r"yarn\s+(?:add|remove)"
            r")\b",
            re.IGNORECASE,
        )
        if WRITE_VERB_RE.search(command):
            try:
                tokens = shlex.split(command, posix=True)
            except ValueError:
                tokens = command.split()
            for tok in tokens:
                tok = tok.strip("\"'")
                if not tok or tok.startswith("-"):
                    continue
                if "/" in tok or tok in (".", ".."):
                    candidate_paths.append(tok)

        for p in candidate_paths:
            check_path(p)

sys.exit(0)
