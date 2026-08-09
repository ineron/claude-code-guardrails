#!/usr/bin/env python3
"""Add/remove claude-code-guardrails hook entries in ~/.claude/settings.json.

Merges into the existing hooks structure rather than overwriting it, so any
other PreToolUse/UserPromptSubmit hooks already configured survive untouched.
Idempotent: running install twice does not duplicate entries.
"""
import json
import os
import shutil
import sys
import time

SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")

PRETOOL_ENTRY = {"type": "command", "command": "~/.claude/hooks/deny-secrets.sh"}
USERPROMPT_ENTRY = {"type": "command", "command": "~/.claude/hooks/session-heartbeat.sh"}


def load():
    if not os.path.exists(SETTINGS_PATH):
        return {}
    with open(SETTINGS_PATH) as f:
        return json.load(f)


def backup():
    if os.path.exists(SETTINGS_PATH):
        ts = time.strftime("%Y%m%d-%H%M%S")
        dst = f"{SETTINGS_PATH}.bak.{ts}"
        shutil.copy2(SETTINGS_PATH, dst)
        print(f"Backed up settings.json -> {dst}")


def save(data):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def has_hook(hooks_list, marker):
    return any(marker in h.get("command", "") for h in hooks_list)


def install():
    data = load()
    backup()
    hooks = data.setdefault("hooks", {})

    pretool = hooks.setdefault("PreToolUse", [])
    bash_entry = next((e for e in pretool if e.get("matcher") == "Bash"), None)
    if bash_entry is None:
        bash_entry = {"matcher": "Bash", "hooks": []}
        pretool.append(bash_entry)
    bash_hooks = bash_entry.setdefault("hooks", [])
    if has_hook(bash_hooks, "deny-secrets.sh"):
        print("deny-secrets.sh already registered in PreToolUse, skipping")
    else:
        bash_hooks.append(PRETOOL_ENTRY)
        print("Added deny-secrets.sh to PreToolUse[Bash]")

    userprompt = hooks.setdefault("UserPromptSubmit", [])
    generic_entry = next((e for e in userprompt if "matcher" not in e), None)
    if generic_entry is None:
        generic_entry = {"hooks": []}
        userprompt.append(generic_entry)
    up_hooks = generic_entry.setdefault("hooks", [])
    if has_hook(up_hooks, "session-heartbeat.sh"):
        print("session-heartbeat.sh already registered in UserPromptSubmit, skipping")
    else:
        up_hooks.append(USERPROMPT_ENTRY)
        print("Added session-heartbeat.sh to UserPromptSubmit")

    save(data)
    print(f"Updated {SETTINGS_PATH}")


def uninstall():
    if not os.path.exists(SETTINGS_PATH):
        print("No settings.json found, nothing to do")
        return
    data = load()
    backup()
    hooks = data.get("hooks", {})

    pretool = hooks.get("PreToolUse", [])
    for entry in pretool:
        entry["hooks"] = [h for h in entry.get("hooks", []) if "deny-secrets.sh" not in h.get("command", "")]
    pretool = [e for e in pretool if e.get("hooks")]
    if pretool:
        hooks["PreToolUse"] = pretool
    else:
        hooks.pop("PreToolUse", None)

    userprompt = hooks.get("UserPromptSubmit", [])
    for entry in userprompt:
        entry["hooks"] = [h for h in entry.get("hooks", []) if "session-heartbeat.sh" not in h.get("command", "")]
    userprompt = [e for e in userprompt if e.get("hooks")]
    if userprompt:
        hooks["UserPromptSubmit"] = userprompt
    else:
        hooks.pop("UserPromptSubmit", None)

    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)

    save(data)
    print(f"Removed guardrail hook entries from {SETTINGS_PATH}")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "install":
        install()
    elif action == "uninstall":
        uninstall()
    else:
        print("usage: merge_settings.py [install|uninstall]", file=sys.stderr)
        sys.exit(1)
