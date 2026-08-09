# Snyk Scan Output Template

Always report results in this exact structure. Fill every section. Never skip
"Recommended Next Actions".

## Section 1 — Scan Summary

```
## Snyk Scan Summary

| Scan | Target | Critical | High | Medium | Low | Status |
|------|--------|----------|------|--------|-----|--------|
| SCA (dependencies) | node-api/package.json | 1 | 4 | 3 | 2 | Issues found |
| Code (SAST) | workspace | 0 | 6 | 9 | 5 | Issues found |
| IaC | iac/ | 0 | 2 | 4 | 0 | Issues found |
| Container | node:10 (from Dockerfile.node) | 26 | 130 | 135 | 536 | Issues found |
```

Include a row for every scan attempted — including the Container row when it was skipped
(`RESULT: Container - skipped (no -Image provided)`). If a scan was skipped or failed, put the
reason in
Status (e.g. "Skipped — mvn not installed", "Blocked — org test limit reached").

## Section 2 — Findings

Group by severity, Critical → High → Medium → Low. Per finding show:

```
### Critical (1)
- **SQL Injection in `lodash` transitive path** — [CVE-2021-23337] — node-api/package.json
  - Introduced through: lodash@4.17.15
  - Fix: Upgrade lodash to 4.17.21

### High (4)
- **Hardcoded credential** — node-api/server.js:12 (Snyk Code)
  - Fix: Move secret to environment variable
- ...
```

Rules:
- Max ~10 detailed findings per scan type; summarize the remainder:
  "…plus 7 more Medium/Low issues (see snyk output / --json-file-output for full list)."
- Always include the fix line when Snyk provides one ("Upgrade X to Y", "Fixed in Z").
- Mark findings with no available fix as "No fix available yet — monitor".
- If any findings are suppressed via `snyk ignore` / a `.snyk` policy file, add a final line:
  "N finding(s) suppressed by policy (.snyk): <issue-id> — <reason> (expires <date>)" —
  suppressions must stay visible in every report.

## Section 3 — Recommended Next Actions (REQUIRED)

Generate 3–6 numbered, specific, prioritized actions using these rules — do NOT write
generic advice like "fix the vulnerabilities":

1. **Severity first.** Critical/High fixable issues are action #1. Name the exact package and
   target version: "Upgrade `express` 4.16.0 → 4.19.2 in node-api/package.json (fixes 1 Critical, 2 High)."
2. **Cluster by ecosystem/file.** If one area dominates (e.g. most issues are in Python code),
   say so explicitly and recommend focusing there:
   "python-service accounts for 12 of 20 code issues — prioritize a remediation pass on app.py."
3. **One upgrade fixing many issues wins.** If a single dependency upgrade resolves multiple
   CVEs, call that out as the highest-leverage move.
4. **Recommend the missing scan.** If only SCA was run, suggest `snyk code test`; if code+SCA
   were run and Dockerfiles/Terraform exist, suggest container/IaC scans. Name the file that
   makes it relevant ("Dockerfile.node exists — run a container scan on its base image").
5. **Recommend monitoring.** If findings exist and the project isn't monitored, suggest
   `snyk monitor --all-projects` for ongoing alerts.
6. **Note structural problems.** Missing lockfiles, unresolvable manifests, skipped ecosystems
   (e.g. "Maven scan skipped — install mvn to get Java dependency coverage").

Example:

```
## Recommended Next Actions

1. Upgrade `ejs` 2.7.4 → 3.1.10 in node-api/package.json — single upgrade removes 1 Critical
   and 2 High RCE/injection issues.
2. python-service/app.py contains 8 of the 20 code issues (SQLi, command injection, debug=True).
   Prioritize a remediation pass on this file next.
3. Java SCA coverage is missing — mvn is not installed, so java-app/pom.xml was skipped.
   Install Maven and re-run `snyk test --file=java-app/pom.xml` for full coverage.
4. iac/main.tf has 2 High findings (public S3 bucket, open security group) — fix before deploy.
5. Dockerfile.node and Dockerfile.python exist but no container scan was run — scan the base
   images: `snyk container test node:<tag> --file=Dockerfile.node`.
6. Enable continuous alerts: `snyk monitor --all-projects`.
```

## Tone rules

- Be factual and specific: real package names, versions, file paths, counts.
- No filler ("security is important", "consider reviewing").
- If everything is clean, still produce next actions (e.g. run remaining scan types, add
  monitoring, add Snyk to CI).
