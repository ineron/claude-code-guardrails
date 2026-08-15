#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "$DIR/scripts/merge_settings.py" uninstall
python3 "$DIR/scripts/merge_claude_md.py" uninstall

echo
read -r -p "Also delete the hook files from ~/.claude/hooks? [y/N] " REPLY
if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    rm -f "$HOME/.claude/hooks/deny-secrets.sh" "$HOME/.claude/hooks/warn-secrets-posttooluse.sh" "$HOME/.claude/hooks/session-heartbeat.sh" "$HOME/.claude/hooks/lib/secret_scan.py" "$HOME/.claude/hooks/lib/secret_scan_posttooluse.py" "$HOME/.claude/hooks/lib/secret_patterns.py"
    rm -rf "$HOME/.claude/hooks/state/heartbeat"
    echo "Removed hook files and heartbeat counter state."
else
    echo "Left hook files in place under ~/.claude/hooks/ (they're inert now, no longer referenced from settings.json)."
fi

echo
echo "Uninstalled. settings.json and CLAUDE.md were backed up before editing"
echo "(look for *.bak.<timestamp> next to each file) in case you want to diff or restore."
