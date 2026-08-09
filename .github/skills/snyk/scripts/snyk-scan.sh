#!/usr/bin/env bash
# One-shot Snyk preflight + scan (macOS/Linux).
# Usage: snyk-scan.sh <all|sca|code|iac|container> [target-path] [image:tag] [severity] [org-id]
# Exit codes: 0 = clean, 1 = issues found (scan SUCCEEDED), 2 = setup/scan error
set -u
SCAN="${1:-all}"; TARGET="${2:-.}"; IMAGE="${3:-}"; SEV="${4:-}"; ORG="${5:-}"
FINDINGS=0
SEV_ARG=""
[ -n "$SEV" ] && SEV_ARG="--severity-threshold=$SEV"

section() { printf '\n===== %s =====\n' "$1"; }

# --- 1. Ensure CLI installed ---
if ! command -v snyk >/dev/null 2>&1; then
    if command -v npm >/dev/null 2>&1; then
        section "Installing Snyk CLI via npm"
        INSTALL_LOG="${TMPDIR:-/tmp}/snyk-npm-install.log"
        npm install -g snyk >"$INSTALL_LOG" 2>&1 || echo "npm install failed - log: $INSTALL_LOG"
    fi
    if ! command -v snyk >/dev/null 2>&1; then
        echo "ERROR: Snyk CLI not found and could not be installed automatically."
        echo "Install Node.js (https://nodejs.org) and re-run, or install the CLI manually:"
        echo "https://docs.snyk.io/snyk-cli/install-or-update-the-snyk-cli"
        exit 2
    fi
fi

# --- 2. Best-effort update to latest (throttled: network check at most once per day) ---
INSTALLED="$(snyk --version 2>/dev/null | head -n1)"
STAMP="${TMPDIR:-/tmp}/snyk-cli-update-check"
TODAY="$(date +%Y%m%d)"
if command -v npm >/dev/null 2>&1 && [ "$(cat "$STAMP" 2>/dev/null)" != "$TODAY" ]; then
    LATEST="$(npm view snyk version 2>/dev/null || true)"
    if [ -n "$LATEST" ] && [ "$INSTALLED" != "$LATEST" ]; then
        echo "Updating Snyk CLI $INSTALLED -> $LATEST"
        UPDATE_LOG="${TMPDIR:-/tmp}/snyk-npm-update.log"
        npm install -g snyk@latest >"$UPDATE_LOG" 2>&1 || echo "WARN: update failed (continuing with $INSTALLED) - log: $UPDATE_LOG"
        INSTALLED="$(snyk --version 2>/dev/null | head -n1)"
    fi
    echo "$TODAY" > "$STAMP"
fi
echo "Snyk CLI version: $INSTALLED"

# --- 3. Ensure authenticated (opens browser if needed) ---
if ! snyk whoami --experimental >/dev/null 2>&1; then
    echo "Not authenticated - starting browser login. Complete it; the script waits."
    snyk auth
    if ! snyk whoami --experimental >/dev/null 2>&1; then
        echo "ERROR: authentication failed. Run 'snyk auth' manually or set the SNYK_TOKEN environment variable."
        exit 2
    fi
fi
echo "Authenticated."

# --- 3b. Org selection (SNYK_CFG_ORG is honored by every snyk command) ---
if [ -n "$ORG" ]; then
    export SNYK_CFG_ORG="$ORG"
    echo "Using Snyk org: $ORG"
elif [ -n "${SNYK_CFG_ORG:-}" ]; then
    echo "Using Snyk org from environment: $SNYK_CFG_ORG"
else
    CFG_ORG="$(snyk config get org 2>/dev/null || true)"
    if [ -n "$CFG_ORG" ]; then echo "Using Snyk org from CLI config: $CFG_ORG"
    else echo "No org specified - using your account's default org. Pass an org-id (5th argument) if scans fail with authorization errors."; fi
fi

# --- 4. Run scans (spinner/progress noise stripped to keep output compact) ---
run_scan() {
    local name="$1"; shift
    section "$name"
    # 'analysis for' matches the Snyk Code progress spinner; intentionally minimal filter -
    # extend the pattern only if other scan types add progress chatter
    snyk "$@" 2>&1 | grep -vE 'analysis for'
    local rc=${PIPESTATUS[0]}
    case $rc in
        0) echo "RESULT: $name - no issues found." ;;
        1) echo "RESULT: $name - issues found (scan succeeded)."; FINDINGS=1 ;;
        *) echo "RESULT: $name - error (exit $rc). See output above." ;;
    esac
}

if [ "$SCAN" = "sca" ] || [ "$SCAN" = "all" ]; then
    run_scan "SCA (dependencies)" test --all-projects --detection-depth=4 $SEV_ARG
fi
if [ "$SCAN" = "code" ] || [ "$SCAN" = "all" ]; then
    run_scan "Code (SAST)" code test "$TARGET" $SEV_ARG
fi
if [ "$SCAN" = "iac" ] || [ "$SCAN" = "all" ]; then
    run_scan "IaC" iac test "$TARGET" $SEV_ARG
fi
if [ "$SCAN" = "container" ]; then
    if [ -z "$IMAGE" ]; then echo "ERROR: container scan requires an image:tag argument"; exit 2; fi
    run_scan "Container" container test "$IMAGE" $SEV_ARG
elif [ "$SCAN" = "all" ] && [ -n "$IMAGE" ]; then
    run_scan "Container" container test "$IMAGE" $SEV_ARG
elif [ "$SCAN" = "all" ]; then
    echo ""
    echo "RESULT: Container - skipped (no image provided; pass image:tag as 3rd argument to include it)."
fi

exit $FINDINGS
