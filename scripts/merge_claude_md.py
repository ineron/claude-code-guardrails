#!/usr/bin/env python3
"""Add/remove the guardrails section in ~/.claude/CLAUDE.md.

The section is wrapped in HTML-comment markers so it can be found and
removed cleanly on uninstall without touching anything else the user has
written in that file. Idempotent: running install twice does not duplicate
the section.
"""
import os
import shutil
import sys
import time

CLAUDE_MD_PATH = os.path.expanduser("~/.claude/CLAUDE.md")
SNIPPET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "snippets",
    "CLAUDE.md.snippet",
)
BEGIN_MARKER = "<!-- BEGIN claude-code-guardrails -->"
END_MARKER = "<!-- END claude-code-guardrails -->"


def backup():
    if os.path.exists(CLAUDE_MD_PATH):
        ts = time.strftime("%Y%m%d-%H%M%S")
        dst = f"{CLAUDE_MD_PATH}.bak.{ts}"
        shutil.copy2(CLAUDE_MD_PATH, dst)
        print(f"Backed up CLAUDE.md -> {dst}")


def install():
    existing = ""
    if os.path.exists(CLAUDE_MD_PATH):
        with open(CLAUDE_MD_PATH) as f:
            existing = f.read()

    if BEGIN_MARKER in existing:
        print("guardrails section already present in CLAUDE.md, skipping")
        return

    with open(SNIPPET_PATH) as f:
        snippet = f.read().strip()

    backup()
    block = f"{BEGIN_MARKER}\n{snippet}\n{END_MARKER}\n"
    if existing.strip():
        new_content = existing.rstrip("\n") + "\n\n" + block
    else:
        new_content = block

    os.makedirs(os.path.dirname(CLAUDE_MD_PATH), exist_ok=True)
    with open(CLAUDE_MD_PATH, "w") as f:
        f.write(new_content)
    print(f"Added guardrails section to {CLAUDE_MD_PATH}")


def uninstall():
    if not os.path.exists(CLAUDE_MD_PATH):
        print("No CLAUDE.md found, nothing to do")
        return
    with open(CLAUDE_MD_PATH) as f:
        content = f.read()
    if BEGIN_MARKER not in content or END_MARKER not in content:
        print("guardrails section not found in CLAUDE.md, nothing to remove")
        return

    backup()
    start = content.index(BEGIN_MARKER)
    end = content.index(END_MARKER) + len(END_MARKER)
    new_content = (content[:start].rstrip("\n") + "\n" + content[end:].lstrip("\n")).strip("\n")
    new_content = (new_content + "\n") if new_content else ""

    with open(CLAUDE_MD_PATH, "w") as f:
        f.write(new_content)
    print(f"Removed guardrails section from {CLAUDE_MD_PATH}")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "install":
        install()
    elif action == "uninstall":
        uninstall()
    else:
        print("usage: merge_claude_md.py [install|uninstall]", file=sys.stderr)
        sys.exit(1)
