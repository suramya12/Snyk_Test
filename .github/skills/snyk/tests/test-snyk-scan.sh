#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SCAN_SCRIPT="$SKILL_ROOT/scripts/snyk-scan.sh"
TEST_ROOT="$(mktemp -d)"
ORIGINAL_PATH="$PATH"

cleanup() {
    rm -rf "$TEST_ROOT"
}
trap cleanup EXIT

mkdir -p "$TEST_ROOT/bin" "$TEST_ROOT/workspace"
cat > "$TEST_ROOT/bin/snyk" <<'MOCK'
#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then echo "1.1306.3"; exit 0; fi
if [ "${1:-}" = "whoami" ]; then exit 0; fi
if [ "${1:-}" = "config" ]; then exit 0; fi
echo "Mock Snyk scan output"
if [ "${MOCK_CONTAINER_FINDINGS:-0}" = "1" ] && [ "${1:-}" = "container" ]; then exit 1; fi
exit "${MOCK_SNYK_EXIT:-0}"
MOCK
chmod +x "$TEST_ROOT/bin/snyk"

export PATH="$TEST_ROOT/bin:$ORIGINAL_PATH"
export TMPDIR="$TEST_ROOT"
date +%Y%m%d > "$TEST_ROOT/snyk-cli-update-check"

assert_scan_exit() {
    local mock_exit="$1"
    local expected_exit="$2"
    local expected_result="$3"
    local output_file="$TEST_ROOT/output.txt"

    MOCK_SNYK_EXIT="$mock_exit" "$SCAN_SCRIPT" code > "$output_file" 2>&1
    local actual_exit=$?
    if [ "$actual_exit" -ne "$expected_exit" ]; then
        echo "FAIL: mock exit $mock_exit produced script exit $actual_exit; expected $expected_exit"
        cat "$output_file"
        exit 1
    fi
    if ! grep -Fq "$expected_result" "$output_file"; then
        echo "FAIL: expected result line '$expected_result'"
        cat "$output_file"
        exit 1
    fi
}

assert_scan_exit 0 0 'RESULT: Code (SAST) - no issues found.'
assert_scan_exit 1 1 'RESULT: Code (SAST) - issues found (scan succeeded).'
assert_scan_exit 2 2 'RESULT: Code (SAST) - error (exit 2).'
assert_scan_exit 3 3 'RESULT: Code (SAST) - skipped (no supported targets found).'

printf 'ARG BASE_IMAGE=alpine:3.20\nFROM --platform=linux/amd64 ${BASE_IMAGE}\n' > "$TEST_ROOT/workspace/Dockerfile"
(
    cd "$TEST_ROOT/workspace" || exit 1
    MOCK_SNYK_EXIT=0 MOCK_CONTAINER_FINDINGS=1 "$SCAN_SCRIPT" all > "$TEST_ROOT/all-output.txt" 2>&1
)
actual_exit=$?
if [ "$actual_exit" -ne 1 ]; then
    echo "FAIL: auto-discovered container findings produced exit $actual_exit; expected 1"
    cat "$TEST_ROOT/all-output.txt"
    exit 1
fi

echo 'Bash scan contract tests: PASS'