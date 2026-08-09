# Snyk Vulnerable Multi-Stack Benchmark

This repository intentionally contains insecure code, vulnerable dependencies,
misconfigured infrastructure, and obsolete container images. It exists to compare
the Snyk VS Code extension, Snyk CLI, and Snyk MCP scan coverage and behavior.

**Do not deploy this project, expose it to a network, or copy these patterns into
production code. Do not remediate findings in this benchmark branch.**

No `.snyk` policy file or ignore rules are included. All severities should remain
visible. Snyk's vulnerability database and detection rules change over time, so
record the scan date, Snyk version, organization, product, and issue IDs with every
comparison.

## Expected Vulnerabilities

The items below are the benchmark's source of truth. One source pattern can produce
multiple Snyk findings, and some patterns may not be supported by every Snyk product
or account plan.

### Node.js API

| Type | Location | Intentionally vulnerable behavior |
| --- | --- | --- |
| Open source | `node-api/package.json` and lockfile | Express 4.16.1, EJS 2.5.5, minimist 0.2.4, and vulnerable transitive packages |
| Code | `GET /?msg=` | Reflected XSS through unescaped EJS output (`<%- msg %>`) |
| Code | `GET /ping?host=` | OS command injection through `child_process.exec` |
| Code | `GET /hash?text=` | MD5 used as a weak cryptographic hash |
| Code/secret | `GET /secret` | Hardcoded fake API key in source |
| Code | `server.js` users array | Hardcoded plaintext passwords |

`GET /search` and `GET /read` currently contain explicit safe-listing controls and
are not expected SQL injection or path traversal findings. This distinction avoids
counting a scanner's correct non-finding as a false negative.

### Python Service

| Type | Location | Intentionally vulnerable behavior |
| --- | --- | --- |
| Open source | `python-service/requirements.txt` | Flask 1.0, Jinja2 2.10.1, PyYAML 5.3, urllib3 1.23, Requests 2.19.1, and other legacy pins |
| Code | `GET /?x=` | Reflected XSS through an interpolated HTML response |
| Code | `GET /notes?q=` | SQL injection through an interpolated SQLite query |
| Code | `POST /yaml` | Unsafe deserialization with `yaml.Loader` |
| Code | `GET /ping?target=` | Shell injection through `shell=True` |
| Configuration | `app.py` | Development server binds to `0.0.0.0` |

### Java Application

| Type | Location | Intentionally vulnerable behavior |
| --- | --- | --- |
| Open source | `java-app/pom.xml` | Log4j Core 2.14.1 (Log4Shell-era release) |
| Open source | `java-app/pom.xml` | Commons Collections 3.2.1 gadget-chain exposure |
| Code | `App.main` | Untrusted value written to Log4j with a JNDI payload default |
| Code | `App.unsafeDeserialize` | Untrusted Java native deserialization |
| Code | `App.trustAll` | Trust-all certificate manager and hostname verifier |

### IaC, Containers, and Compose

| Type | Location | Intentionally vulnerable behavior |
| --- | --- | --- |
| IaC | `iac/main.tf` | SSH ingress from `0.0.0.0/0` |
| IaC | `iac/main.tf` | Unrestricted egress to `0.0.0.0/0` |
| IaC | `iac/main.tf` | Public-read S3 bucket ACL |
| IaC/dependency | `iac/main.tf` | Obsolete AWS provider constraint (`~> 3.0`) |
| Container | `Dockerfile.node` | EOL Node 10 image, root runtime, and `npm install --unsafe-perm` |
| Container | `Dockerfile.python` | EOL Python 3.7 image and root runtime |
| Configuration | `docker-compose.yml` | Services published on host ports 3000 and 5000 |

## Snyk MCP Setup

The workspace definition is in `.vscode/mcp.json`. It starts the current Snyk CLI
through `npx`, uses stdio transport required by VS Code, preserves folder-trust
protection, and enables the `experimental` profile so secret scanning is available:

```text
npx --yes snyk mcp -t stdio --profile experimental
```

Prerequisites:

1. Install Node.js and npm.
2. Install Maven for Java SCA and create `python-service/.venv` with Python 3.8 for
	the legacy Python dependency graph. The workspace MCP configuration prepends
	this virtual environment to its PATH; Python 3.12 can remain the system default.
3. In VS Code, reload the window after cloning or changing `.vscode/mcp.json`.
4. Start or restart the `snyk` server from VS Code's MCP server list.
5. In Copilot Chat, ask Snyk MCP to call `snyk_version`.
6. If a scan reports that Snyk is unauthenticated, ask it to call `snyk_auth` and
	complete authentication in the
	browser. Never paste a Snyk token into chat or commit one to this repository.
7. Ask it to call `snyk_trust` for this repository before the first scan. Folder
	trust is required because SCA can execute Maven, npm, or other ecosystem tools.

Create the ignored Python environment on a new Windows machine with:

```powershell
$python38 = "$env:LOCALAPPDATA/Programs/Python/Python38/python.exe"
& $python38 -m venv python-service/.venv
& python-service/.venv/Scripts/python.exe -m pip install --upgrade "pip<25.1"
& python-service/.venv/Scripts/python.exe -m pip install -r python-service/requirements.txt
```

Python 3.8 is intentional because PyYAML 5.3 has a compatible Windows wheel for
that runtime. Python 3.12 can remain the default; Python 3.14 is not required.

Suggested MCP benchmark prompt:

```text
Use only the Snyk MCP tools. Report the Snyk version, trust this workspace, then
run SCA for node-api, python-service, and java-app; Snyk Code for the repository;
Snyk IaC for iac; container scans for both local images; and the experimental
secret scan. If authentication is required, call snyk_auth. Do not modify files,
ignore findings, or remediate anything. Return each finding's product, issue ID,
severity, title, and location, plus elapsed time for each scan.
```

The MCP tools expected with this profile include `snyk_sca_scan`,
`snyk_code_scan`, `snyk_iac_scan`, `snyk_container_scan`, `snyk_secret_scan`,
`snyk_trust`, `snyk_auth`, and `snyk_version`. Snyk CLI 1.1306.3 does not
advertise a separate `snyk_auth_status` tool.

## Direct CLI Baseline

Authenticate once, then run explicit scans from the repository root. A scan exit
code of 1 is expected when vulnerabilities are found.

```powershell
snyk auth
$env:Path = "$(Resolve-Path 'python-service/.venv/Scripts');$env:Path"
snyk code test --severity-threshold=low
snyk iac test iac --severity-threshold=low
snyk test --file=node-api/package.json --package-manager=npm --severity-threshold=low
snyk test --file=python-service/requirements.txt --package-manager=pip --severity-threshold=low
snyk test --file=java-app/pom.xml --package-manager=maven --severity-threshold=low
docker compose build
snyk container test snyk-test-node:local --file=Dockerfile.node --severity-threshold=low
snyk container test snyk-test-python:local --file=Dockerfile.python --severity-threshold=low
```

Maven is required for the Java dependency tree. Docker Desktop must be running to
build and inspect the local images. Snyk Code, container scanning, and secret
scanning availability depends on the authenticated Snyk account and organization.

Do not use `--skip-unresolved` for the Python benchmark. If its environment is
missing, that option can return a misleading clean result with zero dependencies.

## Verified Local Baseline

Fresh checks on 2026-08-09 used Snyk CLI 1.1306.3, Node.js 24.19.0, Maven
3.9.16, Java 26.0.2, and the isolated Python 3.8.10 environment. The account's
preferred Organization was used by both CLI and MCP.

| Interface | Product/target | Findings | Severity/level breakdown |
| --- | --- | ---: | --- |
| CLI | Open Source: Node.js | 17 | 6 high, 8 medium, 3 low |
| MCP | Open Source: Node.js | 14 | Normalized issue list |
| CLI | Open Source: Python | 67 | 3 critical, 19 high, 42 medium, 3 low |
| MCP | Open Source: Python | 38 | Normalized issue list |
| CLI/MCP | Open Source: Java | 12 | CLI: 5 critical, 3 high, 4 medium |
| CLI/MCP | Snyk Code: repository | 20 | CLI: 8 error, 9 warning, 3 note |
| CLI/MCP | IaC: Terraform | 6 | 2 medium, 4 low |
| MCP | Container: `node:10` | 777 listed | 25 critical, 102 high, 116 medium, 534 low |
| MCP | Container: `python:3.7-slim` | 245 listed | 8 critical, 34 high, 35 medium, 168 low |

The Python service import and Maven build both succeeded. MCP negotiated protocol
`2024-11-05`; version, trust, SCA, Code, IaC, and remote container calls all
completed through the exact workspace command. CLI Open Source output counts
vulnerable dependency paths, while MCP returns a normalized issue list, so their
totals can differ without either scanner missing a vulnerability.

The Snyk account warned that Organization `suramya12` had reached its monthly
200-private-test limit; this can affect subsequent comparisons. Snyk Secrets is
also disabled for that Organization and returned `SNYK-CLI-0016` (HTTP 403).
Enable Snyk Secrets in the Organization settings before benchmarking that tool.

Remote base-image scans work without Docker. Docker Desktop is still required to
build and scan `snyk-test-node:local` and `snyk-test-python:local`, which include
the application layers.

## Comparison Record

Use the same Snyk organization and run all tools against the same commit. Record
results without merging similar findings until after collection.

| Date/time | Commit | Scanner | Version | Product | Duration | Finding count | Missed expected items | Extra findings |
| --- | --- | --- | --- | --- | ---: | ---: | --- | --- |
| | | VS Code extension | | | | | | |
| | | Snyk CLI | | | | | | |
| | | Snyk MCP | | | | | | |

Compare coverage by issue ID and source location, not only totals. The extension and
MCP may group or format the same underlying Snyk result differently.
