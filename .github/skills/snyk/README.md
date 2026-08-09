# Snyk Skill — CLI-based security scanning (no MCP server required)

A self-contained agent skill that gives GitHub Copilot / any agent full Snyk capability using
only the Snyk CLI. Replaces the Snyk MCP server in environments where MCP servers are not
allowed. Covers: SCA (dependencies), Code (SAST), IaC, Container, SBOM, AI-BOM, monitoring —
plus guided remediation (fix → rescan → verify).

## Install (pick one)

Unzip this `snyk` folder into one of:

| Location | Scope |
|---|---|
| `<repo>/.github/skills/snyk/` | This repository (recommended for teams) |
| `~/.copilot/skills/snyk/` | Personal — all repositories |

No other setup. The skill installs/updates the Snyk CLI itself (Node.js/npm needed for
auto-install) and walks you through browser login on first use.

## Requirements

- A Snyk account (free tier works) — first run opens a browser to log in
- Node.js + npm (only needed if the Snyk CLI isn't already installed)
- VS Code with GitHub Copilot (or any agent that supports SKILL.md folders)

## Usage — just ask in chat

- `/snyk scan the workspace` (or plain: "run a security scan on this project")
- "Run SCA and code scans"
- "IaC scan the terraform folder"
- "Container scan node:18-alpine"
- "Fix the vulnerabilities you found"

## What's inside

```
snyk/
├── SKILL.md                      # Agent workflow (scan → report → recommend → fix)
├── README.md                     # This file
├── scripts/
│   ├── snyk-scan.ps1             # One-shot install+update+auth+scan (Windows)
│   └── snyk-scan.sh              # Same for macOS/Linux
└── references/
    ├── commands.md               # Full CLI command reference + troubleshooting
    ├── output-template.md        # Structured report + recommendation rules
    └── remediation.md            # Fix → rescan → verify workflow
```

## Notes

- Scan results count against your Snyk org's monthly test limits (same as MCP).
- Exit code 1 from a scan means "issues found", not failure — the scripts label this clearly.
- The agent never modifies your code without asking first.
