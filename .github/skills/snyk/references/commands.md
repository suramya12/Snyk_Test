# Snyk CLI Command Reference

Detailed flags, per-ecosystem notes, and troubleshooting. Load this only when the basic
command from SKILL.md is not enough.

## SCA (open source dependencies) — `snyk test`

```
snyk test --all-projects                     # scan every manifest found (recommended default)
snyk test --all-projects --detection-depth=4 # search deeper folder trees
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
snyk container test <image:tag>                          # e.g. node:18-alpine
snyk container test <image:tag> --file=Dockerfile.node   # include Dockerfile for base-image advice
snyk container test <image:tag> --exclude-app-vulns      # OS-level only
snyk container monitor <image:tag>                       # continuous monitoring
```

- The image must exist locally (`docker images`) or be pullable. If Docker isn't running,
  report that and skip.
- A Dockerfile alone cannot be scanned; an image reference is required. If the user points at a
  Dockerfile, extract the base image from its `FROM` line and scan that with `--file=<Dockerfile>`.

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

- npm package: `snyk test lodash@4.17.15` (tests a single public npm package).
- Other ecosystems: no direct CLI equivalent — point the user to https://snyk.io/advisor/
  for health scores (maintenance, popularity, security).

## Auth details

```
snyk whoami --experimental        # check current user
snyk auth                         # browser-based OAuth login
snyk auth <token>                 # token-based (CI)
snyk config clear                 # "logout" - removes stored credentials (no `snyk logout` command exists)
snyk config set org=<org-id>      # set default org
```

Environment variables: `SNYK_TOKEN` (auth), `SNYK_CFG_ORG` (org override).

## Troubleshooting (exit code 2)

| Error text contains | Cause | Action |
|---|---|---|
| `Authentication error` / `Unauthorized` | Not logged in / token expired | Re-run Step 2 (`snyk auth`) |
| `test limit` / `monthly limit` | Org quota exhausted for private tests | Report it; continue other scan types; user can wait for reset or upgrade plan |
| `Could not detect supported target files` | No manifests found (exit 3) | List what Snyk supports; check you're in the right folder |
| `mvn command not found` / build errors | Ecosystem toolchain missing | Report skipped project; suggest installing the tool |
| `Snyk Code is not supported` | Snyk Code disabled on org | User enables it in org settings |
| Proxy/network errors | Corporate proxy | Set `HTTPS_PROXY` env var |
