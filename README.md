# claude-code-guardrails

Two small, independent [Claude Code](https://claude.com/claude-code) hooks:

1. **session-heartbeat** — makes context/instruction loss in a long session
   *visible* instead of silent.
2. **deny-secrets** — blocks Bash commands that would print a live
   `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` (or a file containing one) to
   the terminal or chat.

Both are user-level (`~/.claude/`), so once installed they apply to every
project you open with Claude Code — not just one repo.

## Why

Claude Code sessions can run long enough that earlier instructions get
pushed out by context compaction, and there's normally no visible signal
when that happens — the model just quietly stops following something it
was told two hundred turns ago. Separately, it's easy to have Claude `cat`
or `echo` a config file that happens to contain a live API key, especially
when debugging config issues.

Neither of these is solved by asking the model to "be careful" — a model
that has already lost the relevant instruction can't be careful about the
instruction it lost. Both problems needed enforcement outside the model:
a hook that runs regardless of what the model currently believes.

## How it works

### session-heartbeat

`hooks/session-heartbeat.sh` runs on the `UserPromptSubmit` event — right
before each of your prompts reaches the model. It keeps a per-session turn
counter (`~/.claude/hooks/state/heartbeat/<session_id>.count`) and injects
the real wall-clock time and turn number into context as
`additionalContext`, along with an instruction to echo both back verbatim
at the end of the reply, e.g.:

```
⏱ turn #7 · 2026-08-09 14:16:11 CEST
```

The model has no reliable clock of its own — this hook is the only source
of ground truth for the time/number, so it can't fabricate a plausible-
looking marker. The instruction to echo it (in `snippets/CLAUDE.md.snippet`,
merged into `~/.claude/CLAUDE.md`) survives or doesn't survive context
compaction exactly like any other standing instruction, which is the point:
if the marker disappears from a reply, that's your signal something upstream
got dropped and the session may be worth restarting rather than trusting.

This is informational only — nothing blocks the model from replying without
the marker. It's a smoke detector, not a fire suppressor.

### deny-secrets

`hooks/deny-secrets.sh` (thin wrapper) → `hooks/lib/secret_scan.py` runs on
the `PreToolUse` event for the `Bash` matcher and denies the command before
it executes if it looks like it would expose a secret:

- **Known secret-bearing filenames**: `.env` (and `.env.local`/`.production`/
  etc., but not `.env.example`), `.pgpass`, `id_rsa`/`id_ed25519`,
  `credentials.json`, `service-account*.json`, `*.pem`, `*.key`.
- **Env-var dumps**: `echo $ANTHROPIC_API_KEY`, `printenv | grep anthropic`,
  `export | grep ...`, etc. — matched across pipes, since the value ends up
  printed either way.
- **Content-based, filename-agnostic**: if the command references an
  *existing file* on disk, the file's actual contents are scanned for
  something shaped like a live key (`sk-ant-...`, `ANTHROPIC_API_KEY=...`,
  AWS-style `AKIA...`, etc.) and the command is denied if found — this is
  what catches a config file that isn't secret *by name* (e.g.
  `~/.claude/settings.json`) but has ended up with a real key pasted into
  its `env` block.

A plain `grep ANTHROPIC_API_KEY some_source_file.py` (searching code for
where the variable is *referenced*, not dumping its value) is intentionally
left alone — see `hooks/lib/secret_scan.py` for the exact patterns.

This only covers Bash. It cannot stop the model from reading a key with the
Read tool or typing it into a chat reply — for that, `snippets/CLAUDE.md.snippet`
adds a standing instruction ("never paste a live key into a reply, check
presence instead of printing values, treat any exposed key as compromised").
That part is soft enforcement (a written rule the model follows), not a hard
technical block — the Bash hook is the hard block.

## Install

```bash
git clone <this-repo> claude-code-guardrails
cd claude-code-guardrails
./install.sh
```

This:
- copies `hooks/*` into `~/.claude/hooks/` (merging into an existing
  `hooks/` directory, not replacing it),
- merges the two hook registrations into `~/.claude/settings.json` —
  **merges**, not overwrites: any hooks you already have configured (other
  `PreToolUse` matchers, other `UserPromptSubmit` hooks) are left in place,
- appends the CLAUDE.md section between
  `<!-- BEGIN claude-code-guardrails -->` / `<!-- END ... -->` markers to
  `~/.claude/CLAUDE.md` (creating the file if it doesn't exist yet).

Both `settings.json` and `CLAUDE.md` are backed up (`*.bak.<timestamp>`)
before being touched. The install is idempotent — running it again detects
what's already present and skips it, so re-running after a `git pull` is
safe.

Restart any Claude Code session that's already running so it picks up the
new hook registrations.

## Disable / uninstall

**Turn off just one hook** without uninstalling: comment out or delete its
entry under `hooks.PreToolUse` (for deny-secrets) or `hooks.UserPromptSubmit`
(for session-heartbeat) in `~/.claude/settings.json`. The two are fully
independent — removing one doesn't affect the other.

**Turn off the CLAUDE.md instructions only**: delete the block between
`<!-- BEGIN claude-code-guardrails -->` and `<!-- END claude-code-guardrails -->`
in `~/.claude/CLAUDE.md`. The heartbeat hook will keep injecting the
timestamp/counter into context either way — without the instruction, the
model just won't be told to echo it back.

**Remove everything**:

```bash
cd claude-code-guardrails
./uninstall.sh
```

This removes the hook entries from `settings.json`, removes the CLAUDE.md
section, and optionally (asks first) deletes the copied hook files and the
heartbeat counter state directory. `settings.json`/`CLAUDE.md` are backed up
before editing, same as install.

## Limitations

- **session-heartbeat** is a visibility tool, not a guarantee — it tells you
  when something *might* have gone wrong (marker missing), it doesn't fix
  the underlying context loss or force the model to keep following
  instructions it no longer has.
- **deny-secrets** only wraps the Bash tool. Other tools that can surface
  file contents (Read, an MCP tool that fetches a config file, etc.) aren't
  covered by the hook — only by the softer CLAUDE.md instruction.
- Pattern matching is heuristic (regex-based), not a full secret scanner —
  it's tuned for Anthropic keys/tokens plus a few common secret-file
  patterns, not a general-purpose tool like `gitleaks` or `trufflehog`. If
  you need broader coverage, run one of those in CI in addition to this.

## License

MIT — see [LICENSE](LICENSE).
