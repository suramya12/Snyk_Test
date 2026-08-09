# Changelog

## 1.0.0 - 2026-08-09

- Propagate scan errors, unsupported-target results, findings, and clean results with distinct exit codes.
- Preserve container findings during Bash Dockerfile auto-discovery.
- Support multi-stage Dockerfiles, `FROM --platform=...`, and default `ARG` values.
- Add quota-free launcher contract tests for PowerShell and Bash.
- Add validated versioned ZIP packaging with SHA-256 manifests.
- Clarify scan accounting, installation, troubleshooting, and remediation guidance.