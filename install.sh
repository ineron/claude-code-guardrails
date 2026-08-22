#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$HOME/.claude/hooks/lib"
cp "$DIR/hooks/deny-secrets.sh" "$HOME/.claude/hooks/deny-secrets.sh"
cp "$DIR/hooks/warn-secrets-posttooluse.sh" "$HOME/.claude/hooks/warn-secrets-posttooluse.sh"
cp "$DIR/hooks/session-heartbeat.sh" "$HOME/.claude/hooks/session-heartbeat.sh"
cp "$DIR/hooks/deny-cross-project-edit.sh" "$HOME/.claude/hooks/deny-cross-project-edit.sh"
cp "$DIR/hooks/lib/secret_scan.py" "$HOME/.claude/hooks/lib/secret_scan.py"
cp "$DIR/hooks/lib/secret_scan_posttooluse.py" "$HOME/.claude/hooks/lib/secret_scan_posttooluse.py"
cp "$DIR/hooks/lib/secret_patterns.py" "$HOME/.claude/hooks/lib/secret_patterns.py"
cp "$DIR/hooks/lib/cross_project_guard.py" "$HOME/.claude/hooks/lib/cross_project_guard.py"
chmod 755 "$HOME/.claude/hooks/deny-secrets.sh" "$HOME/.claude/hooks/warn-secrets-posttooluse.sh" "$HOME/.claude/hooks/session-heartbeat.sh" "$HOME/.claude/hooks/deny-cross-project-edit.sh"
chmod 644 "$HOME/.claude/hooks/lib/secret_scan.py" "$HOME/.claude/hooks/lib/secret_scan_posttooluse.py" "$HOME/.claude/hooks/lib/secret_patterns.py" "$HOME/.claude/hooks/lib/cross_project_guard.py"
echo "Copied hook scripts to ~/.claude/hooks/"

python3 "$DIR/scripts/merge_settings.py" install
python3 "$DIR/scripts/merge_claude_md.py" install

echo
echo "Installed. Verify the secret guard with:"
echo '  echo "{\"tool_input\":{\"command\":\"echo \$ANTHROPIC_API_KEY\"}}" | ~/.claude/hooks/deny-secrets.sh'
echo "  (should print a deny JSON)"
echo
echo "Verify the cross-project guard with (only denies if both dirs are"
echo "registered Claude Code projects with distinct .claude/settings.json"
echo "project.slug values -- swap in two real project paths):"
echo '  echo "{\"cwd\":\"/path/to/project-a\",\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"/path/to/project-b/file\"}}" | ~/.claude/hooks/deny-cross-project-edit.sh'
echo
echo "Restart any running Claude Code sessions to pick up the new hooks."
echo "To remove everything later, run ./uninstall.sh from this directory."
