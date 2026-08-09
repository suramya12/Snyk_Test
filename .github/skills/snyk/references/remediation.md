# Remediation Workflow (MCP parity: scan → fix → verify)

Run this ONLY after the user explicitly approves fixing. Before starting, show the user a
short list of the fixes you intend to apply and get one approval for the batch.

## Order of work

1. **Dependency upgrades (SCA)** — highest leverage, lowest risk.
2. **Code fixes (SAST)** — Critical/High first.
3. **IaC fixes** — apply the `Resolve:` line the scan printed for each issue.

## 1. Dependency upgrades

Use EXACTLY the versions from the scan output ("Upgrade X to Y"). Do not jump further ahead
than Snyk recommends without asking.

| Ecosystem | How to apply |
|---|---|
| npm | Edit the version in `package.json`, then run `npm install` in that folder |
| Maven | Edit the `<version>` element in `pom.xml` |
| pip | Bump the pin in `requirements.txt` |

After edits, verify the project still resolves/builds (`npm install` exits 0; `mvn -q compile`
if Maven is installed). If a major-version upgrade is required (e.g. ejs 2.x → 3.x), warn the
user it may contain breaking changes before applying.

## 2. Code fixes — pattern table

Fix only what the finding requires; preserve existing behavior.

| Finding type | Standard fix |
|---|---|
| SQL Injection | Parameterized queries / prepared statements — never string-concatenate SQL |
| Command Injection | No shell string interpolation: `subprocess.run([...])` (no `shell=True`), `execFile` instead of `exec`; validate/allowlist input |
| XSS | Escape output; use template autoescaping (`render_template`); never return raw user input as HTML |
| Unsafe deserialization (`yaml.load`, `pickle`, `ObjectInputStream`) | `yaml.safe_load`; never deserialize untrusted input; use JSON/DTOs |
| Hardcoded secrets / passwords | Read from environment variables (`process.env.X` / `os.environ`); delete the literal value |
| Weak hashing (MD5/SHA1 for passwords) | bcrypt/scrypt/argon2 for passwords; SHA-256 for integrity checks |
| Permissive TrustManager / disabled cert validation | Remove the custom TrustManager; restore default certificate validation |
| Missing rate limiting | Add middleware: `express-rate-limit` (Node), `flask-limiter` (Python) |
| X-Powered-By exposure | `app.disable('x-powered-by')` or add Helmet |
| Debug mode enabled | `debug=False` / remove debug flag for production entrypoints |
| Cleartext HTTP | Use `https` module / TLS endpoints |

## 3. IaC fixes

The scan output contains a `Resolve:` line per finding — apply it literally
(e.g. set `acl = "private"`, restrict `cidr_blocks` to a specific range, enable versioning).

## 4. Verify loop (required — do not skip)

1. Rescan ONLY the affected scan types via the one-shot script:
   dependencies changed → `-Scan sca` · source changed → `-Scan code` · IaC changed → `-Scan iac`.
2. Confirm each fixed issue is gone AND no new issues were introduced.
3. If fixable issues remain, fix and rescan again. **Maximum 3 rounds** — then stop and report
   what remains and why (no fix available, needs major upgrade, needs human decision).
4. Final report to the user:
   - Fixed: list of issues resolved (with file/package)
   - Remaining: issues with no fix available or deferred (with reason)
   - Files changed: full list
