"""Shared live-secret detection pattern, used by both the PreToolUse guard
(secret_scan.py) and the PostToolUse detector (secret_scan_posttooluse.py).

Single source of truth on purpose: this used to be defined separately in
each script, which is exactly the kind of duplication that silently drifts
out of sync (see the merge_claude_md.py staleness bug fixed alongside the
PostToolUse hook — same lesson, applied here before it could repeat).

Scoped to high-confidence, well-known provider formats (distinctive
prefixes, fixed-ish lengths) to keep false positives low. Deliberately does
NOT attempt generic high-entropy-string detection (that needs a proper
scanner like gitleaks/trufflehog, not a hand-rolled regex) — secrets with no
distinctive prefix (a bare AWS secret access key, a plain password) are
outside what this pattern can catch by design.
"""
import re

SECRET_VALUE_RE = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{20,}"                                # Anthropic
    r"|sk-proj-[A-Za-z0-9_-]{20,}"                              # OpenAI (project-scoped)
    r"|sk-[A-Za-z0-9]{20,}"                                     # OpenAI (classic) / other sk-prefixed
    r"|AKIA[0-9A-Z]{16}"                                        # AWS access key ID
    r"|AIza[0-9A-Za-z_-]{35,}"                                  # Google API key
    r"|gh[pousr]_[A-Za-z0-9]{36,}"                              # GitHub token (classic: ghp_/gho_/ghu_/ghs_/ghr_)
    r"|github_pat_[A-Za-z0-9_]{22,}"                            # GitHub fine-grained PAT
    r"|xox[baprs]-[A-Za-z0-9-]{10,48}"                          # Slack token
    r"|(?:sk|rk)_(?:live|test)_[0-9a-zA-Z]{24,}"                # Stripe secret/restricted key
    r"|SK[0-9a-fA-F]{32}"                                       # Twilio API Key SID
    r"|SG\.[\w-]{16,32}\.[\w-]{16,64}"                          # SendGrid
    r"|-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"  # PEM private key
    r"|ANTHROPIC_(?:API_KEY|AUTH_TOKEN)[\"' ]*[:=][\"' ]*[A-Za-z0-9._-]{16,}"
    r"|OPENAI_API_KEY[\"' ]*[:=][\"' ]*[A-Za-z0-9._-]{16,}"
)
