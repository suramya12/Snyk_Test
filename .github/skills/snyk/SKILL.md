---
name: snyk
description: 'Run Snyk security scans and fix the findings via the Snyk CLI — no Snyk MCP server needed. Use when the user asks for: security scan, vulnerability scan, SCA scan, dependency scan, open source scan, code scan, SAST, static analysis, secret scan, hardcoded credentials, IaC scan, Terraform scan, container scan, Docker image scan, SBOM, AI-BOM, package health check, breakability check, snyk test, snyk monitor, "scan this workspace/project/repo", "is this code secure", "fix the vulnerabilities", or "remediate the findings". Auto-installs and updates the CLI, authenticates, runs the right scans, reports structured results with prioritized next actions, and remediates findings with user approval.'
argument-hint: 'e.g. "scan the workspace", "SCA scan", "iac scan iac/", "container scan img:tag", "fix the findings"'
---

# Snyk Security Scanning & Remediation (CLI-based, no MCP required)

Replicates the Snyk MCP server using only the Snyk CLI. Follow the steps in order.

## Efficiency rules (always apply)

- Prefer the one-shot script in Step 1: ONE terminal command handles install + update + auth + all scans.
- Never re-run a scan whose results you already have in this conversation.
- Never request or print JSON output; work from the default human-readable output.
- Do not paste raw scanner output into chat — summarize per Step 3.

## Command whitelist — NEVER invent snyk commands

The ONLY snyk commands that exist are: `snyk auth`, `snyk whoami --experimental`, `snyk test`,
`snyk monitor`, `snyk code test`, `snyk iac test`, `snyk container test|monitor`, `snyk sbom`,
`snyk sbom test`, `snyk aibom`, `snyk config`, `snyk ignore`, `snyk policy`, `snyk log4shell`.

These do **NOT** exist — do not run them: `snyk secret scan`, `snyk secrets`, `snyk logout`,
`snyk scan`, `snyk sast`. If a request doesn't map to a whitelisted command, use the MCP parity
map below — every capability has a defined action there.

## Step 1 — Run the one-shot scan script (preferred)

The scripts live next to this file in `./scripts/`. Use the absolute path to this skill's folder.

Windows (PowerShell):
```
powershell -ExecutionPolicy Bypass -File "<skill-folder>\scripts\snyk-scan.ps1" -Scan all
```
macOS/Linux:
```
bash "<skill-folder>/scripts/snyk-scan.sh" all
```

Scan values: `all` | `sca` | `code` | `iac` | `container`.
If the user just says "scan", use `all`. Optional args: `-Target <path>` (code/iac scope),
`-Image <image:tag>` (required for container), `-Org <org-id>`, `-SeverityThreshold high`.
For the .sh script the positional order is: `<scan> [target] [image] [severity] [org-id]`.
Run the script from the **workspace root** so scans cover the whole project.

**Org ID (right after auth):**
- If the user provided an org ID (or one is set in their environment/CLI config), always pass it: `-Org <org-id>`.
- If no org is known, run without it — the CLI uses the account's default org.
- If a scan then fails with 401/403/"not provisioned"/"org" errors, ASK the user for their org ID
  (visible at https://app.snyk.io → org Settings → Organization ID) and re-run with `-Org <org-id>`.
- Once a working org ID is known, offer to persist it so it's never needed again: `snyk config set org=<org-id>`.

The script automatically: installs the CLI via npm if missing → updates to latest → checks auth
(if a browser opens, tell the user to complete the login; the script waits) → runs the scans
with progress-spinner noise stripped → prints one `RESULT:` line per scan.

**Exit codes — critical:** `0` = clean, `1` = **issues found, scan SUCCEEDED** (summarize the
findings — this is not an error), `2` = setup/scan error (read the ERROR lines; troubleshooting
table in [references/commands.md](./references/commands.md)).

**When a scan fails or a project is skipped — never relay the raw error.** Diagnose it with the
failure table in [references/commands.md](./references/commands.md) and give the developer 2–3
plain lines: (1) what failed, (2) why — in terms of THEIR project (missing deps, broken build,
out-of-sync lockfile), (3) the exact command or change that fixes it. Example:

> SCA couldn't analyze `python-service` — Snyk resolves exact dependency versions from the
> installed packages, and they aren't installed here.
> Fix: `pip install -r python-service/requirements.txt`, then re-run the scan.

**Fallback** — only if the script cannot run (execution policy blocked, no shell): run the manual
sequence from [references/commands.md](./references/commands.md): `snyk --version` →
`snyk whoami --experimental` → `snyk auth` if needed → the individual scan commands.

## Step 2 — MCP tool parity map (every Snyk MCP capability → CLI action)

Auth is already verified if the script ran. Otherwise check `snyk whoami --experimental` first.
Match the request to EXACTLY ONE row and do what the row says — nothing else.

| MCP tool / user request | Action in this skill |
|---|---|
| `snyk_sca_scan` / dependency scan | Step 1 script with `-Scan sca` |
| `snyk_code_scan` / SAST | Step 1 script with `-Scan code` |
| `snyk_iac_scan` / Terraform/K8s config | Step 1 script with `-Scan iac -Target <path>` |
| `snyk_container_scan` / Docker image | Step 1 script with `-Scan container -Image <image:tag>` |
| `snyk_secret_scan` / secret scan | **Special procedure — see "Secret scan" below. Do NOT run `snyk secret scan` (not a real command).** |
| `snyk_sbom_scan` / test an SBOM | `snyk sbom test --experimental --file=<sbom-file>` |
| Generate SBOM | `snyk sbom --format cyclonedx1.5+json --json-file-output=sbom.json` |
| `snyk_aibom` / AI-BOM | `snyk aibom --experimental` |
| `snyk_package_health_check` / "is package X safe" | `snyk test <package>@<version>` (npm only); other ecosystems → https://snyk.io/advisor/ — details in [commands reference](./references/commands.md) |
| `snyk_breakability_check` / "will upgrading X break things" | No CLI equivalent. Assess manually: compare semver (major = likely breaking), read the package changelog/release notes between versions, and grep the workspace for APIs the changelog says changed. Report a risk level with evidence. |
| `snyk_auth` | `snyk auth` (browser login) |
| `snyk_logout` | `snyk config clear` (removes stored token) — there is NO `snyk logout` command |
| `snyk_version` | `snyk --version` |
| `snyk_trust` / `snyk_send_feedback` | MCP-only concepts; not needed with the CLI — say so and continue |
| Continuous monitoring | `snyk monitor --all-projects` |

### Secret scan (dedicated procedure — follow exactly)

The CLI has no standalone secrets command; Snyk Code performs the secrets detection. Steps:

1. Run the Step 1 script with `-Scan code` (or reuse existing code-scan results from this conversation).
2. From the output keep ONLY findings whose title contains: `Hardcoded Credentials`,
   `Hardcoded Passwords`, `Hardcoded Secret`, `Hardcoded Non-Cryptographic Secret`, or `Cleartext`.
3. Report them under the heading **"Secret Scan Results (via Snyk Code secrets detection)"** —
   never present the full SAST result set as a "secret scan".
4. State the coverage caveat: it scans source/config files in the working tree only — git
   history, ignored files (e.g. `.env` in `.gitignore`), and binaries are NOT covered. If the
   user needs git-history secret detection, recommend a dedicated tool (e.g. gitleaks) — do not
   attempt it with snyk.

## Step 3 — Report results (structured)

Format exactly per [references/output-template.md](./references/output-template.md):

1. **Scan Summary** table — one row per scan: type, target, Critical/High/Medium/Low counts, status
   (include skipped/failed scans with the reason).
2. **Findings** grouped by severity, Critical first: title/CVE, package or file:line, and the fix
   Snyk reported ("Upgrade X to Y"). Max ~10 detailed findings per scan; roll the rest up as counts.
3. **Recommended Next Actions** — REQUIRED, never omit. Use the recommendation rules in the
   template: severity first, cluster by ecosystem/file, highest-leverage single upgrades,
   missing scan types, missing toolchain coverage, monitoring.

## Step 4 — Offer and perform remediation (MCP parity)

After reporting, ask: *"Want me to fix these? I can apply the dependency upgrades and code
fixes, then rescan to verify."*

On approval, follow [references/remediation.md](./references/remediation.md) exactly:
apply fixes (deps → code → IaC) → rescan ONLY the affected scan type via the Step 1 script →
verify fixed + no new issues → repeat, max 3 rounds → final fixed/remaining/files-changed report.

Never modify any file without explicit approval. Never run `snyk fix` unprompted.

## Known limitations vs the Snyk MCP server (disclose when relevant)

- **Secret scanning**: no dedicated CLI command; covered via the Secret scan procedure above (Snyk Code secrets detection, working tree only).
- **Breakability check**: no CLI equivalent; use the manual semver/changelog assessment from the parity map.
- **Package health** beyond npm: point the user to https://snyk.io/advisor/.
- **Org test limits** apply to CLI the same as MCP; quota errors are reported, not fatal — continue other scans.

## Guardrails

- Read-only by default; remediation only via Step 4 with approval.
- If a scan hits an org quota/limit error, report it plainly and continue with the remaining scan types.
- On Windows use PowerShell syntax (no `&&` chaining).
