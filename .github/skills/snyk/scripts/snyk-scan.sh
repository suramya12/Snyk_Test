#!/usr/bin/env bash
# One-shot Snyk preflight + scan (macOS/Linux).
# Usage: snyk-scan.sh <all|sca|code|iac|container> [target-path] [image:tag] [severity] [org-id] [dockerfile]
#   dockerfile: for container scans, extract the base image from its FROM line and scan
#   with base-image remediation advice (image:tag takes precedence if both are given).
# Exit codes: 0 = clean, 1 = issues found (scan SUCCEEDED), 2 = setup/scan error,
#             3 = no supported targets found
set -u
SCAN="${1:-all}"; TARGET="${2:-.}"; IMAGE="${3:-}"; SEV="${4:-}"; ORG="${5:-}"; DOCKERFILE="${6:-}"
FINDINGS=0
SCAN_ERROR=0
NO_PROJECTS=0
SEV_ARG=""
[ -n "$SEV" ] && SEV_ARG="--severity-threshold=$SEV"

case "$SCAN" in
    all|sca|code|iac|container) ;;
    *) echo "ERROR: invalid scan type '$SCAN'. Expected all, sca, code, iac, or container."; exit 2 ;;
esac
case "$SEV" in
    ''|low|medium|high|critical) ;;
    *) echo "ERROR: invalid severity '$SEV'. Expected low, medium, high, or critical."; exit 2 ;;
esac

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
        3) echo "RESULT: $name - skipped (no supported targets found)."; NO_PROJECTS=1 ;;
        *) echo "RESULT: $name - error (exit $rc). See output above."; SCAN_ERROR=1 ;;
    esac
}

overall_exit() {
    if [ "$SCAN_ERROR" -ne 0 ]; then return 2; fi
    if [ "$NO_PROJECTS" -ne 0 ]; then return 3; fi
    return "$FINDINGS"
}

dockerfile_base_image() {
    awk '
        toupper($1) == "ARG" && index($2, "=") > 0 {
            name = substr($2, 1, index($2, "=") - 1)
            args[name] = substr($2, index($2, "=") + 1)
        }
        toupper($1) == "FROM" {
            for (i = 2; i <= NF; i++) {
                if ($i !~ /^--/) { image = $i; break }
            }
        }
        END {
            for (name in args) {
                gsub("\\$\\{" name "\\}", args[name], image)
                gsub("\\$" name, args[name], image)
            }
            if (image != "") print image
        }
    ' "$1"
}

validate_container_input() {
    local dockerfile_path="$1"
    local image_name="$2"
    if [ -n "$dockerfile_path" ] && [ ! -f "$dockerfile_path" ]; then
        echo "ERROR: Dockerfile not found: $dockerfile_path"
        return 1
    fi
    case "$image_name" in
        *'$'*) echo "ERROR: Dockerfile base image '$image_name' contains an unresolved ARG. Pass an image:tag (3rd argument)."; return 1 ;;
    esac
    return 0
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
    if [ -z "$IMAGE" ] && [ -n "$DOCKERFILE" ]; then
        if ! validate_container_input "$DOCKERFILE" ""; then exit 2; fi
        IMAGE="$(dockerfile_base_image "$DOCKERFILE")"
        if [ -n "$IMAGE" ]; then echo "Extracted base image from $DOCKERFILE: $IMAGE"
        else echo "ERROR: no FROM line found in $DOCKERFILE. Pass an image:tag (3rd argument) instead."; exit 2; fi
    fi
    if [ -z "$IMAGE" ]; then echo "ERROR: container scan requires an image:tag (3rd arg) or a dockerfile (6th arg)"; exit 2; fi
    if ! validate_container_input "$DOCKERFILE" "$IMAGE"; then exit 2; fi
    if [ -n "$DOCKERFILE" ]; then
        run_scan "Container" container test "$IMAGE" --file="$DOCKERFILE" $SEV_ARG
    else
        run_scan "Container" container test "$IMAGE" $SEV_ARG
    fi
elif [ "$SCAN" = "all" ] && [ -n "$IMAGE" ]; then
    if ! validate_container_input "$DOCKERFILE" "$IMAGE"; then exit 2; fi
    if [ -n "$DOCKERFILE" ]; then
        run_scan "Container" container test "$IMAGE" --file="$DOCKERFILE" $SEV_ARG
    else
        run_scan "Container" container test "$IMAGE" $SEV_ARG
    fi
elif [ "$SCAN" = "all" ]; then
    # Auto-discover Dockerfiles so container coverage is never silently skipped.
    FOUND_DOCKERFILE=0
    while IFS= read -r df; do
        if [ -n "$df" ]; then
            FOUND_DOCKERFILE=1
            img=$(dockerfile_base_image "$df")
            if [ -z "$img" ]; then echo "RESULT: Container ($(basename "$df")) - skipped (no FROM line found)."; SCAN_ERROR=1; continue; fi
            case "$img" in
                *'$'*) echo "RESULT: Container ($(basename "$df")) - skipped (unresolved ARG in base image; pass an image:tag)."; SCAN_ERROR=1; continue ;;
            esac
            # Resolve to an absolute path: snyk code test can change the CLI's working dir,
            # so a relative --file path breaks later scans in the same run.
            df_abs="$(cd "$(dirname "$df")" && pwd)/$(basename "$df")"
            echo "Auto-discovered $(basename "$df") -> base image $img"
            run_scan "Container ($(basename "$df"))" container test "$img" --file="$df_abs" $SEV_ARG
        fi
    done < <(find . -type f -name 'Dockerfile*' \
        -not -path '*/node_modules/*' -not -path '*/.git/*' \
        -not -path '*/target/*' -not -path '*/dist/*' -not -path '*/build/*' 2>/dev/null | sort)
    if [ "$FOUND_DOCKERFILE" -eq 0 ]; then
        echo ""
        echo "RESULT: Container - skipped (no image provided and no Dockerfile* found)."
    fi
fi

overall_exit
exit $?
