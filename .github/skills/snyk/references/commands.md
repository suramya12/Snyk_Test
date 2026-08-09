# Snyk CLI Command Reference

Detailed flags, per-ecosystem notes, and troubleshooting. Load this only when the basic
command from SKILL.md is not enough.

## SCA (open source dependencies) — `snyk test`

```
snyk test --all-projects                     # scan every manifest found (recommended default)
snyk test --all-projects --detection-depth=4 # manifests up to 4 folders deep (covers typical monorepo nesting; raise for deeper trees)
snyk test --file=package.json                # scan one specific manifest
snyk test --file=pom.xml --package-manager=maven
snyk test --file=requirements.txt --package-manager=pip
snyk test --severity-threshold=high          # only high & critical
snyk test --json-file-output=snyk-sca.json   # machine-readable copy (do not print to chat)
snyk test --fail-on=upgradable               # CI: fail only on fixable issues
```

Per-ecosystem prerequisites (if missing, that project is skipped — report it, don't fail the whole scan):
- **Maven/Java**: `mvn` must be on PATH and the project must build (`pom.xml` resolvable).
- **Gradle**: `gradle` or wrapper available.
- **Python**: dependencies should be installed (`pip install -r requirements.txt`) for exact resolution; otherwise Snyk falls back to manifest-only and may be incomplete.
- **npm/yarn/pnpm**: a lockfile improves accuracy; `node_modules` not required.

## Code / SAST — `snyk code test`

```
snyk code test                               # scan current directory
snyk code test path/to/subfolder
snyk code test --severity-threshold=medium
snyk code test --sarif-file-output=snyk-code.sarif
```

- Requires Snyk Code to be enabled on the org. If you get "Snyk Code is not supported for org",
  tell the user to enable it in Snyk org settings → Snyk Code.
- Detects hardcoded secrets/credentials in source (closest CLI equivalent to MCP secret scan).

## IaC — `snyk iac test`

```
snyk iac test                                # scan all IaC files under cwd
snyk iac test iac/                           # scan a folder
snyk iac test main.tf                        # single file
snyk iac test --severity-threshold=high
snyk iac test --report                       # also share results to Snyk platform (ask user first)
```

Supports Terraform, CloudFormation, Kubernetes YAML, ARM templates, Terraform plan JSON.

## Container — `snyk container test`

```
snyk container test <image:tag>                          # e.g. node:18-alpine (no local Docker needed for public registry images — the CLI pulls metadata itself)
snyk container test <image:tag> --file=Dockerfile.node   # include Dockerfile for base-image advice
snyk container test <image:tag> --exclude-app-vulns      # OS-level only
snyk container monitor <image:tag>                       # continuous monitoring
```

- **CRITICAL: an image:tag argument is mandatory.** `snyk container test --file=Dockerfile.node`
  (no image) is an error — a Dockerfile alone cannot be scanned. When the user points at a
  Dockerfile, extract the base image from its `FROM` line and scan THAT with `--file=<Dockerfile>`
  appended (the one-shot scripts do this automatically: `-Dockerfile <path>` on ps1, 6th
  positional arg on sh). The `--file` flag also unlocks Snyk's base-image remediation advice
  ("upgrade base image to X").
- Public registry images need no local Docker — the CLI scans them remotely. A local/private
  image requires a running Docker daemon (`docker images` to confirm). If Docker isn't running
  AND the image isn't public, report that and skip.
- Container scans produce large outputs (a full OS package list — often 100+ findings). In the
  report, summarize by severity and list only Critical/High detail; never dump the full list.

## Monitor — `snyk monitor`

```
snyk monitor --all-projects
snyk monitor --all-projects --org=<org-id>
```

Sends a dependency snapshot to the Snyk platform for continuous alerting. Tell the user where
to view it (URL is printed in output).

## SBOM

```
snyk sbom --format cyclonedx1.5+json --json-file-output=sbom.json   # generate
snyk sbom --format spdx2.3+json --json-file-output=sbom.spdx.json   # SPDX variant
snyk sbom test --experimental --file=sbom.json                      # test an existing SBOM
```

## AI-BOM

```
snyk aibom --experimental                    # inventory of AI models, datasets, tools in repo
snyk aibom --experimental --html-file-output=aibom.html
```

## Package health (MCP `snyk_package_health_check` equivalent)

- Vulnerabilities (npm only): `snyk test lodash@4.17.15` (tests a single public npm package).
- Health score (broad ecosystem coverage): fetch the Snyk Advisor page and extract the health
  score plus maintenance, popularity, security, and community signals — the same data the MCP
  tool returns:

| Ecosystem | URL pattern |
|---|---|
| npm | `https://snyk.io/advisor/npm-package/<package>` |
| Python | `https://snyk.io/advisor/python/<package>` |
| Go | `https://snyk.io/advisor/golang/<module-path>` |
| Docker | `https://snyk.io/advisor/docker/<image>` |

State one caveat: the data is read from the Advisor web page, not Snyk's structured API.
Ecosystems not on Advisor (e.g. Maven, NuGet): search the vuln DB at https://security.snyk.io
and report vulnerability history plus latest-release recency instead.

## Auth details

```
snyk whoami --experimental        # check current user
snyk auth                         # browser-based OAuth login
snyk auth <token>                 # token-based (CI)
snyk config clear                 # "logout" - removes stored credentials (no `snyk logout` command exists)
snyk config set org=<org-id>      # set default org
```

Environment variables: `SNYK_TOKEN` (auth), `SNYK_CFG_ORG` (org override).

## Org selection

Developers are often members of an org rather than admins; scans may fail or land in the wrong
org without an explicit org ID.

```
snyk config get org                   # check configured default
snyk test --all-projects --org=<id>   # per-command override (works on all test commands)
snyk config set org=<id>              # persist for all future runs (ask user before persisting)
```

The org ID is a UUID found at https://app.snyk.io → org Settings → Organization ID.
The one-shot scripts accept it via `-Org <id>` (ps1) / 5th positional arg (sh) and export
`SNYK_CFG_ORG`, which every snyk command honors.

If no org is supplied or configured, the scripts use the account default. For repeatable team
and CI scans, always pass the UUID explicitly so results and quota usage land in the intended org.

## Ignores & the .snyk policy file

```
snyk ignore --id=<ISSUE-ID> --reason="false positive: input validated upstream" --expiry=2026-12-31
```

- Always set `--reason` AND `--expiry`; never ignore silently or indefinitely.
- The command writes to a `.snyk` policy file in the project root. Committing it is preferred
  for teams: the ignore then travels with the repo and applies in CI and for every developer.
- Uncommitted ignores live only on the machine where they were created.

## CI integration

- Add `SNYK_TOKEN` (a service-account API token) as a pipeline secret.
- Gate command: `snyk test --all-projects --severity-threshold=high --fail-on=upgradable`
  (fails the build only on high/critical issues that have an available fix).
- On the main branch also run `snyk monitor --all-projects` for continuous alerting.

## Troubleshooting (exit codes 2 and 3)

| Error text contains | Cause | Action |
|---|---|---|
| `Authentication error` / `Unauthorized` | Not logged in / token expired | Re-run Step 2 (`snyk auth`) |
| `whoami` succeeds but scans return 401/Unauthorized | Stored token stale or revoked | Re-run `snyk auth`, then retry the scan |
| `test limit` / `monthly limit` | Org quota exhausted for private tests | Report it; continue other scan types; user can wait for reset or upgrade plan |
| `Could not detect supported target files` | No manifests found (exit 3) | List what Snyk supports; check you're in the right folder |
| `mvn command not found` / build errors | Ecosystem toolchain missing | Report skipped project; suggest installing the tool |
| `Snyk Code is not supported` | Snyk Code disabled on org | User enables it in org settings |
| Proxy/network errors | Corporate proxy | Set `HTTPS_PROXY` env var |

## Project-side scan failures — explain in plain English

When a scan fails because of the DEVELOPER'S project (not Snyk), match the error below and
reply with the 2–3 line pattern: what failed → why → exact fix. Never just paste the raw error.

| Error text contains | What it means (tell the dev) | Fix to give them |
|---|---|---|
| `Missing required packages` / `Required packages missing` (pip) | Snyk resolves Python deps from installed packages; they aren't installed | `pip install -r requirements.txt` (in a venv), then re-scan. If using python3 explicitly: add `--command=python3` |
| `mvn command not found` | Maven isn't installed/on PATH, so the Java project can't be resolved | Install Maven (or use the project's `mvnw`), verify `mvn -v`, re-scan |
| Maven `Cannot resolve dependencies` / `BUILD FAILURE` | The pom doesn't build — Snyk needs a resolvable build | Run `mvn dependency:tree` to see the real error (bad version, missing repo credential), fix the pom, re-scan |
| `out of sync` / `lockfile` errors (npm/yarn/pnpm) | package.json and the lockfile disagree | Run `npm install` (or `yarn` / `pnpm install`) to regenerate the lockfile, re-scan |
| npm `401`/`403` during resolution | Private registry needs auth | Configure `.npmrc` with the registry token (their team's standard setup), re-scan |
| Gradle `Could not resolve` / daemon errors | Gradle build not resolvable | Run `./gradlew dependencies` to surface the real failure, fix, re-scan |
| `Failed to get dependencies` (generic) | The manifest exists but the ecosystem tooling couldn't produce a dependency graph | Build the project once locally with its normal tool; whatever error appears there is the actual blocker |
| `1/N potential projects failed to get dependencies` | Partial failure — the OTHER projects scanned fine | Report the successful results; explain the failed project separately using this table |

Rule of thumb: Snyk SCA needs the project to be *buildable/resolvable* with its native package
manager. If the native tool (`npm install`, `mvn compile`, `pip install -r`) fails, Snyk fails too
— fixing the native build fixes the scan.
