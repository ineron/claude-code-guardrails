#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$HOME/.claude/hooks/lib"
cp "$DIR/hooks/deny-secrets.sh" "$HOME/.claude/hooks/deny-secrets.sh"
cp "$DIR/hooks/session-heartbeat.sh" "$HOME/.claude/hooks/session-heartbeat.sh"
cp "$DIR/hooks/lib/secret_scan.py" "$HOME/.claude/hooks/lib/secret_scan.py"
chmod 755 "$HOME/.claude/hooks/deny-secrets.sh" "$HOME/.claude/hooks/session-heartbeat.sh"
chmod 644 "$HOME/.claude/hooks/lib/secret_scan.py"
echo "Copied hook scripts to ~/.claude/hooks/"

python3 "$DIR/scripts/merge_settings.py" install
python3 "$DIR/scripts/merge_claude_md.py" install

echo
echo "Installed. Verify the secret guard with:"
echo '  echo "{\"tool_input\":{\"command\":\"echo \$ANTHROPIC_API_KEY\"}}" | ~/.claude/hooks/deny-secrets.sh'
echo "  (should print a deny JSON)"
echo
echo "Restart any running Claude Code sessions to pick up the new hooks."
echo "To remove everything later, run ./uninstall.sh from this directory."
