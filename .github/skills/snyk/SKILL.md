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
- Never print JSON/SARIF to chat. Writing JSON/SARIF to a FILE for post-processing (e.g. the
  secret scan) is allowed — extract from it with filtered commands, never dump it.
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
`-Image <image:tag>` (required for container), `-Dockerfile <path>` (container: base image
extracted automatically), `-Org <org-id>`, `-SeverityThreshold high`.
For the .sh script the positional order is: `<scan> [target] [image] [severity] [org-id] [dockerfile]`.
Run the script from the **workspace root** so scans cover the whole project.

**Org ID (right after auth):**
- If the user provided an org ID (or one is set in their environment/CLI config), always pass it: `-Org <org-id>`.
- If no org is known, run without it — the CLI uses the account's default org.
- If a scan then fails with 401/403/"not provisioned"/"org" errors, ASK the user for their org ID
  (visible at https://app.snyk.io → org Settings → Organization ID) and re-run with `-Org <org-id>`.
- Once a working org ID is known, offer to persist it so it's never needed again: `snyk config set org=<org-id>`.

The script automatically: installs the CLI via npm if missing → updates to latest (checked at
most once per day) → checks auth (if a browser opens, tell the user to complete the login; the
script waits) → runs the scans with progress-spinner noise stripped → prints one `RESULT:` line
per scan. `-Scan all` auto-discovers `Dockerfile*` files outside common build/vendor folders and
scans the final base image from each one. `FROM --platform=...` and default `ARG` values are
supported. If an image variable cannot be resolved, pass `-Image <image:tag>` explicitly.

**Exit codes — critical:** `0` = clean, `1` = **issues found, scan SUCCEEDED** (summarize the
findings — this is not an error), `2` = setup/scan error (read the ERROR lines; troubleshooting
table in [references/commands.md](./references/commands.md)), `3` = no supported targets found
(verify the working directory and `-Target` path). For multi-scan runs, error/incomplete coverage
takes precedence over findings so CI cannot report a false success.

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
| "scan Dockerfile.X" / container scan of a Dockerfile | Step 1 script with `-Scan container -Dockerfile <path>` — the script extracts the FROM image and adds `--file=` for base-image remediation advice. NEVER run `snyk container test --file=...` without an image argument — a Dockerfile alone cannot be scanned |
| `snyk_secret_scan` / secret scan | **Special procedure — see "Secret scan" below. Do NOT run `snyk secret scan` (not a real command).** |
| `snyk_sbom_scan` / test an SBOM | `snyk sbom test --experimental --file=<sbom-file>` |
| Generate SBOM | `snyk sbom --format cyclonedx1.5+json --json-file-output=sbom.json` |
| `snyk_aibom` / AI-BOM | `snyk aibom --experimental` |
| `snyk_package_health_check` / "is package X safe" | Vulns: `snyk test <pkg>@<version>` (npm only). Health score for ANY ecosystem: fetch the Snyk Advisor page — URL patterns in [commands reference](./references/commands.md) |
| `snyk_breakability_check` / "will upgrading X break things" | **See "Breakability check" below — evidence-based procedure.** |
| `snyk_auth` | `snyk auth` (browser login) |
| `snyk_logout` | `snyk config clear` (removes stored token) — there is NO `snyk logout` command |
| `snyk_version` | `snyk --version` |
| `snyk_trust` / `snyk_send_feedback` | MCP-only concepts; not needed with the CLI — say so and continue |
| Continuous monitoring | `snyk monitor --all-projects` |

### Secret scan (dedicated procedure — follow exactly)

The CLI has no standalone secrets command; Snyk Code performs the secrets detection. Use SARIF
output so the filtering is deterministic (rule IDs are stable; display titles are not):

1. Run: `snyk code test <target> --sarif-file-output=<temp-dir>\snyk-code.sarif`
   Write the SARIF to the system temp dir ($env:TEMP / ${TMPDIR:-/tmp}), NOT the repo — the
   file contains code snippets around each finding and must never be committed. Reuse a SARIF
   already produced in this conversation if one exists.
2. Extract secret findings with ONE filtered command — never read or print the whole file:
   - PowerShell: `(Get-Content <sarif> -Raw | ConvertFrom-Json).runs | ForEach-Object { $_.results } | Where-Object { $_.ruleId -match 'Hardcoded' } | ForEach-Object { "$($_.level) $($_.ruleId) $($_.locations[0].physicalLocation.artifactLocation.uri):$($_.locations[0].physicalLocation.region.startLine)" }`
   - bash (jq): `jq -r '.runs[].results[] | select(.ruleId|test("Hardcoded"; "i")) | "\(.level) \(.ruleId) \(.locations[0].physicalLocation.artifactLocation.uri):\(.locations[0].physicalLocation.region.startLine)"' <sarif>`
   - bash without jq (grep/sed fallback): `grep -o '"ruleId":"[^"]*"' <sarif> | grep -i 'Hardcoded' | sort -u`
     (rule IDs only — report them plus the total count; for file:line detail use a targeted grep
     around each matched ruleId, still never dumping the whole file.)
3. Report under the heading **"Secret Scan Results (via Snyk Code secrets detection)"** —
   never present the full SAST result set as a "secret scan".
4. Delete the SARIF file afterwards.
5. State the coverage caveat: working tree only — git history, ignored files (e.g. `.env` in
   `.gitignore`), and binaries are NOT covered (the MCP secret scan has the same limits). For
   git-history secrets recommend a dedicated tool (e.g. gitleaks) — do not attempt it with snyk.

### Breakability check (dedicated procedure — exceeds MCP: it tests THIS repo)

Assess "will upgrading <pkg> from A to B break my app" with evidence, step by step:

1. **Semver delta** — major bump = High baseline risk; minor = Medium; patch = Low;
   pre-1.0 minor bump = treat as major.
2. **Changelog evidence** — locate the repo (`npm view <pkg> repository.url` or the registry
   page) and read the release notes between A and B; list changed/removed APIs.
3. **Workspace impact** — search this repo for each changed/removed API. Zero usages →
   downgrade the risk one level; cite the searches as evidence.
4. **Dry run (only with user approval)** — never modify the user's working tree. Use an
   isolated git worktree (`$env:TEMP\snyk-break` on PowerShell or
   `${TMPDIR:-/tmp}/snyk-break` on bash) → apply the upgrade THERE → run the project's build and
   tests → report the result → ALWAYS remove that worktree, even on failure (wrap cleanup so a
   failed build cannot skip it). Green = Low residual risk; failures = the concrete break list.
   If the project is not a git repo: copy the project dir to temp and work there instead.
5. **Verdict** — Low/Medium/High with one line of evidence per step.

## Step 3 — Report results (structured — MANDATORY FORMAT)

The report MUST follow [references/output-template.md](./references/output-template.md) EXACTLY —
free-form bullet summaries are NOT acceptable. All three sections, every time:

1. **Scan Summary table** — one row per scan (including skipped/failed with the reason),
   with Critical/High/Medium/Low counts per row. No counts = non-compliant report.
   Use the scanner's complete summary or structured output as the source of truth. Never count
   severity strings in a truncated terminal buffer or infer missing values. Follow the count
   procedure in [references/output-template.md](./references/output-template.md).
2. **Findings** grouped by severity, Critical first: title/CVE, package or file:line, and the fix
   Snyk reported ("Upgrade X to Y"). Max ~10 detailed findings per scan; roll the rest up as counts.
3. **Recommended Next Actions** — REQUIRED, never omit. Use the recommendation rules in the
   template: severity first, cluster by ecosystem/file, highest-leverage single upgrades,
   missing scan types, missing toolchain coverage, monitoring.
    - If a container scan was skipped because no concrete base image could be resolved, the FIRST
       next action must be: rerun with `-Scan container -Image <image:tag> -Dockerfile <path>`.

## Step 4 — Offer and perform remediation (MCP parity)

After reporting, ask: *"Want me to fix these? I can apply the dependency upgrades and code
fixes, then rescan to verify."*

On approval, follow [references/remediation.md](./references/remediation.md) exactly:
apply fixes (deps → code → IaC) → rescan ONLY the affected scan type via the Step 1 script →
verify fixed + no new issues → repeat, max 3 rounds → final fixed/remaining/files-changed report.

Never modify any file without explicit approval. Never run `snyk fix` unprompted.

## Step 5 — Disputed findings and ignores

If the user disputes a finding or wants to suppress it:

1. Verify it is genuinely non-exploitable in this code path (state why in one line).
2. Ask the user for a reason and an expiry date — NEVER ignore silently or indefinitely.
3. Run: `snyk ignore --id=<ISSUE-ID> --reason="<user reason>" --expiry=<YYYY-MM-DD>`
   This writes to the `.snyk` policy file — recommend committing it so the ignore travels with
   the repo (details in [commands reference](./references/commands.md)).
4. List every active ignore in the next report so suppressions stay visible.

## Known limitations vs the Snyk MCP server (disclose when relevant)

- **Secret scan** covers the working tree only — no git history (the MCP secret scan has the same limitation).
- **Dockerfile-only container scans** analyze the final base image and provide base-image advice;
   build and scan the application image when application-layer coverage is required.
- **Breakability check** is evidence-based (semver/changelog/dry-run on THIS repo) rather than backed by Snyk's API dataset.
- **Package health** metrics are read from the Snyk Advisor web page, not the structured API.
- **Org test limits** apply to CLI the same as MCP; quota errors are reported, not fatal — continue other scans.

## Guardrails

- Read-only by default; remediation only via Step 4 with approval.
- If a scan hits an org quota/limit error, report it plainly and continue with the remaining scan types.
- On Windows use PowerShell syntax (no `&&` chaining).
