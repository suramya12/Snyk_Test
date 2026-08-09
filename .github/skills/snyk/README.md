# Snyk Skill - CLI-based security scanning

Current release: **1.0.0**

A self-contained agent skill that gives GitHub Copilot / any agent full Snyk capability using
only the Snyk CLI. Replaces the Snyk MCP server in environments where MCP servers are not
allowed. Covers: SCA (dependencies), Code (SAST), secrets (via Snyk Code), IaC, Container,
SBOM, AI-BOM, monitoring — plus guided remediation (fix → rescan → verify) and plain-English
explanations when a scan fails because of the project (missing deps, broken build).

## Install a release

Use `snyk-skill-v1.0.0.zip` for a versioned release or `snyk-skill.zip` for the
latest stable alias. Verify the adjacent `.sha256` file before extracting:

```powershell
(Get-FileHash .\snyk-skill-v1.0.0.zip -Algorithm SHA256).Hash.ToLowerInvariant()
Get-Content .\snyk-skill-v1.0.0.zip.sha256
```

The archive has one top-level `snyk/` folder. Extract that folder into one of:

Unzip so you get a `snyk` folder in one of:

| Location | Scope |
|---|---|
| `<repo>/.github/skills/snyk/` | This repository (recommended for teams; verified) |
| `<repo>/.claude/skills/snyk/` | This repository — Claude Code (per documented skill locations) |
| `~/.copilot/skills/snyk/` | Personal — all repositories (per documented skill locations) |

No other skill setup is required. The first scan installs/updates the Snyk CLI itself (Node.js/npm needed for
auto-install) and walks you through browser login on first use. If your Snyk account belongs
to multiple orgs, have your Organization ID handy (app.snyk.io → org Settings) — the agent
will ask for it only if a scan needs it.

## Requirements

- A Snyk account (free tier works) — first run opens a browser to log in
- Node.js + npm (only needed if the Snyk CLI isn't already installed)
- VS Code with GitHub Copilot (or any agent that supports SKILL.md folders)

## Usage — just ask in chat

- `/snyk scan the workspace` (or plain: "run a security scan on this project")
- "Run SCA and code scans"
- "Run a secret scan"
- "IaC scan the terraform folder"
- "Container scan node:18-alpine"
- "Container scan Dockerfile.node" (the script extracts the FROM image and includes
  base-image upgrade advice)
- "Is upgrading express to v5 safe?" (breakability assessment — evidence-based, optionally
  test-verified in an isolated git worktree)
- "Fix the vulnerabilities you found"

`all` runs SCA, SAST, IaC, and auto-discovers each `Dockerfile*` for final-base-image scans.
To scan application layers, build the image first and pass its tag with `-Image`.

## Script exit contract

| Exit | Meaning |
|---:|---|
| 0 | Scan completed with no findings |
| 1 | Scan completed and found issues |
| 2 | Setup or scan error; coverage is incomplete |
| 3 | No supported targets were found |

Exit code `1` is a successful security scan, not a tool failure. In multi-scan runs, an error
or unsupported target takes precedence over findings to prevent false-green CI results.

## What's inside

```
snyk/
├── SKILL.md                      # Agent workflow (scan → report → recommend → fix)
├── README.md                     # This file
├── VERSION                       # Semantic release version
├── CHANGELOG.md                   # Release notes
├── scripts/
│   ├── snyk-scan.ps1             # One-shot install+update+auth+scan (Windows)
│   ├── snyk-scan.sh              # Same for macOS/Linux
│   └── package-skill.ps1          # Validated release packager
├── tests/                         # Quota-free launcher contract tests
└── references/
    ├── commands.md               # Full CLI command reference + troubleshooting
    ├── output-template.md        # Structured report + recommendation rules
    └── remediation.md            # Fix → rescan → verify workflow
```

## Validate and package

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .github\skills\snyk\tests\test-snyk-scan.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .github\skills\snyk\scripts\package-skill.ps1
```

The packager runs both PowerShell and Bash tests when Git Bash is available, validates required
files and frontmatter, writes an internal `MANIFEST.sha256`, and creates versioned and stable ZIPs
under `dist/` with an external SHA-256 file.

## Notes

- Scan results count against your Snyk org's monthly test limits (same as MCP).
- Exit code 1 from a scan means "issues found", not failure — the scripts label this clearly.
- Multi-org accounts: pass your org ID once and the agent can persist it (`snyk config set org=<id>`).
- The agent never modifies your code without asking first.
