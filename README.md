# claude-code-guardrails

Three small, independent [Claude Code](https://claude.com/claude-code) hooks:

1. **session-heartbeat** — makes context/instruction loss in a long session
   *visible* instead of silent.
2. **deny-secrets** — blocks Bash commands and Read-tool calls that would
   print or pull into context a live `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`
   (or a file containing one).
3. **deny-cross-project-edit** — blocks Edit/Write/NotebookEdit calls, and
   write-shaped Bash commands, whose target path resolves inside a
   *different* registered Claude Code project (identified by
   `.claude/settings.json`'s `project.slug`) than the one the current
   session is running in.

All three are user-level (`~/.claude/`), so once installed they apply to
every project you open with Claude Code — not just one repo.

## Why

Claude Code sessions can run long enough that earlier instructions get
pushed out by context compaction, and there's normally no visible signal
when that happens — the model just quietly stops following something it
was told two hundred turns ago. Separately, it's easy to have Claude `cat`
or `echo` a config file that happens to contain a live API key, especially
when debugging config issues.

A third, related problem: a session working in one project can have
filesystem access to *other* projects too (they're often sibling
directories), and a model that decides some other project needs a fix can
just go edit it directly instead of routing the request through that
project's own session/owner. Written instructions to not do this ("ask
first", "send a message instead") are exactly as reliable as any other
written instruction the model might have lost track of.

None of these three is solved by asking the model to "be careful" — a model
that has already lost (or never had) the relevant instruction can't be
careful about it. All three problems needed enforcement outside the model:
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
the `PreToolUse` event for the `Bash|Read` matcher and denies the action
before it executes if it looks like it would expose a secret:

- **Known secret-bearing filenames**: `.env` (and `.env.local`/`.production`/
  etc., but not `.env.example`), `.pgpass`, `id_rsa`/`id_ed25519`,
  `credentials.json`, `service-account*.json`, `*.pem`, `*.key`. Checked
  against both the Bash command line and a Read call's `file_path`.
- **Env-var dumps** (Bash only): `echo $ANTHROPIC_API_KEY`,
  `printenv | grep anthropic`, `export | grep ...`, etc. — matched across
  pipes, since the value ends up printed either way.
- **Content-based, filename-agnostic**: if a Bash command references an
  *existing file* on disk, or a Read call targets one, the file's actual
  contents are scanned for something shaped like a live key
  (`sk-ant-...`, `ANTHROPIC_API_KEY=...`, AWS-style `AKIA...`, etc.) and the
  action is denied if found — this is what catches a config file that isn't
  secret *by name* (e.g. `~/.claude/settings.json`) but has ended up with a
  real key pasted into its `env` block.

A plain `grep ANTHROPIC_API_KEY some_source_file.py` (searching code for
where the variable is *referenced*, not dumping its value) is intentionally
left alone — see `hooks/lib/secret_scan.py` for the exact patterns.

**Why Read is covered, not just Bash**: the moment a secret enters the
model's context — as a Read result, same as a Bash command's output — it has
already left the workspace as part of the request sent to the API, whether
or not the model goes on to repeat it in a visible reply. Claude Code has no
hook that can intercept or redact the model's own response text (it's
streamed as it's generated), so a "catch it in the output" gate isn't
buildable even in principle. The only enforceable boundary is upstream: stop
the tool call that would read the secret into context at all. That's what
the `Bash|Read` matcher does; it does not cover typing a key into a chat
reply from a source *other* than a blocked file (e.g. a key the model
already had in context from earlier in the conversation), or any other tool
that might surface file contents (an MCP tool fetching a remote config,
for instance) — for those, `snippets/CLAUDE.md.snippet` adds a standing
instruction ("never paste a live key into a reply, check presence instead of
printing values, treat any exposed key as compromised"). That part is soft
enforcement (a written rule the model follows), not a hard technical block —
the `Bash|Read` hook is the hard block.

### deny-cross-project-edit

`hooks/deny-cross-project-edit.sh` (thin wrapper) →
`hooks/lib/cross_project_guard.py` runs on the `PreToolUse` event for the
`Bash|Edit|Write|NotebookEdit` matcher.

"Registered project" is defined purely by filesystem convention, with no
external state: a directory is a project root if it (or an ancestor) has a
`.claude/settings.json` with a non-empty `project.slug`. The hook walks up
from the session's own `cwd` to find its own project's slug, then for each
tool call's target path(s) walks up from *that* path the same way. If the
two slugs differ, it denies the call. If either side has no such marker —
the session's own directory isn't a registered project, or the target path
isn't inside one — the hook allows the call through (fails open): it only
enforces a boundary it can actually see on disk, never guesses at one.

- **Edit / Write / NotebookEdit**: checked directly against `file_path` /
  `notebook_path`.
- **Bash**: classification-based, not a blanket path check. A command is
  only denied if it's write-shaped — a `>`/`>>` redirect, or one of a fixed
  list of mutating verbs/editors (`sed -i`, `cp`, `mv`, `rm`, `mkdir`,
  `chmod`, `git commit`/`push`/`checkout`/..., `npm install`, `vim`/`nano`/
  `code`, etc.) — *and* it references a path under a foreign project.
  Read-only commands (`cat`, `grep`, `ls`, `git log`/`diff`/`status`, ...)
  are left alone even when they reference another project's files — this
  hook enforces "don't edit it directly", not "don't look at it".

The deny message doesn't just say no — it tells the model what to do
instead: if the repo uses the memory-bank-mcp pattern (an MCP server for
cross-session/cross-project memory that happens to use this same
`.claude/settings.json` `project.slug` convention), send a
`message_send`/`memory_upsert(kind="task", filed_from_project=...)` to the
target project's slug instead of touching its files; otherwise, stop and
ask the user for explicit confirmation first.

**Why filesystem convention instead of a lookup table**: there's no shared
database this generic, standalone hook can assume exists — project ↔
directory mappings live (if anywhere) inside whatever tool a given repo
uses for cross-session memory, and that tool's own schema may not even
store filesystem paths (memory-bank-mcp's doesn't — only slugs). The
`.claude/settings.json` convention is the one thing guaranteed to sit next
to the code itself, so it's the only stable place to key off of without
adding a dependency.

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
entry under `hooks.PreToolUse` (deny-secrets and deny-cross-project-edit
are separate entries there) or `hooks.UserPromptSubmit` (for
session-heartbeat) in `~/.claude/settings.json`. All three are fully
independent — removing one doesn't affect the others.

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
- **deny-secrets** wraps Bash and Read. Other tools that can surface file
  contents (an MCP tool that fetches a remote config file, Grep/Glob results
  that happen to include a matched secret line, etc.) aren't covered by the
  hook — only by the softer CLAUDE.md instruction. Same for a secret the
  model already has in context from earlier in the conversation and pastes
  into a reply — the hook only stops a *new* protected read, not reuse of
  something already in context.
- Pattern matching is heuristic (regex-based), not a full secret scanner —
  it's tuned for Anthropic keys/tokens plus a few common secret-file
  patterns, not a general-purpose tool like `gitleaks` or `trufflehog`. If
  you need broader coverage, run one of those in CI in addition to this.
- **deny-cross-project-edit** only recognizes a project if it (or an
  ancestor of the target path) has a `.claude/settings.json` with
  `project.slug` set — a directory with no such file, or one with only
  `name`/`description` and no `slug`, isn't treated as "another project"
  and edits to it go through unblocked. Its Bash coverage is a fixed list
  of write-shaped verbs/redirects, not a full shell parser — an unusual way
  of writing a file (a script that writes for you, an uncommon tool name)
  can slip through the same way novel secret patterns can slip past
  deny-secrets. It also can't see through indirection: a symlink whose
  target resolves outside the foreign project, or a Bash command that
  writes via a wrapper script rather than a recognized verb directly, is
  not caught.

## License

MIT — see [LICENSE](LICENSE).
