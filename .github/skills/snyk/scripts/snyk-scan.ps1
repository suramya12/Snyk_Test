<#
One-shot Snyk preflight + scan (Windows).
Usage:
  powershell -ExecutionPolicy Bypass -File snyk-scan.ps1 -Scan all
  powershell -ExecutionPolicy Bypass -File snyk-scan.ps1 -Scan all -Org <org-id>
  powershell -ExecutionPolicy Bypass -File snyk-scan.ps1 -Scan iac -Target iac/
  powershell -ExecutionPolicy Bypass -File snyk-scan.ps1 -Scan container -Image node:18-alpine
Exit codes: 0 = clean, 1 = issues found (scan SUCCEEDED), 2 = setup/scan error
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet('all', 'sca', 'code', 'iac', 'container')][string]$Scan,
    [string]$Target = '.',
    [string]$Image = '',
    [string]$Org = '',
    [ValidateSet('', 'low', 'medium', 'high', 'critical')][string]$SeverityThreshold = ''
)
$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$script:Findings = $false
$sevArgs = @(); if ($SeverityThreshold) { $sevArgs = @("--severity-threshold=$SeverityThreshold") }

function Write-Section([string]$t) { Write-Output ''; Write-Output "===== $t =====" }

# --- 1. Ensure CLI installed ---
if (-not (Get-Command snyk -ErrorAction SilentlyContinue)) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Section 'Installing Snyk CLI via npm'
        npm install -g snyk *> $null
    }
    if (-not (Get-Command snyk -ErrorAction SilentlyContinue)) {
        Write-Output 'ERROR: Snyk CLI not found and could not be installed automatically.'
        Write-Output 'Install Node.js (https://nodejs.org) and re-run, or install the CLI manually:'
        Write-Output 'https://docs.snyk.io/snyk-cli/install-or-update-the-snyk-cli'
        exit 2
    }
}

# --- 2. Best-effort update to latest ---
$installed = (& snyk --version 2>$null | Select-Object -First 1)
if (Get-Command npm -ErrorAction SilentlyContinue) {
    $latest = (npm view snyk version 2>$null)
    if ($latest -and $installed -and ("$installed".Trim() -ne "$latest".Trim())) {
        Write-Output "Updating Snyk CLI $installed -> $latest"
        npm install -g snyk@latest *> $null
        $installed = (& snyk --version 2>$null | Select-Object -First 1)
    }
}
Write-Output "Snyk CLI version: $installed"

# --- 3. Ensure authenticated (opens browser if needed) ---
& snyk whoami --experimental *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Output 'Not authenticated - starting browser login. Complete it; the script waits.'
    & snyk auth
    & snyk whoami --experimental *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Output 'ERROR: authentication failed. Run "snyk auth" manually or set the SNYK_TOKEN environment variable.'
        exit 2
    }
}
Write-Output 'Authenticated.'

# --- 3b. Org selection (SNYK_CFG_ORG is honored by every snyk command) ---
if ($Org) {
    $env:SNYK_CFG_ORG = $Org
    Write-Output "Using Snyk org: $Org"
}
elseif ($env:SNYK_CFG_ORG) {
    Write-Output "Using Snyk org from environment: $($env:SNYK_CFG_ORG)"
}
else {
    $cfgOrg = (& snyk config get org 2>$null)
    if ($cfgOrg) { Write-Output "Using Snyk org from CLI config: $cfgOrg" }
    else { Write-Output 'No org specified - using your account''s default org. Pass -Org <org-id> if scans fail with authorization errors.' }
}

# --- 4. Run scans (spinner/progress noise stripped to keep output compact) ---
function Invoke-Scan([string]$name, [string[]]$snykArgs) {
    Write-Section $name
    & snyk @snykArgs 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -notmatch 'analysis for' }
    switch ($LASTEXITCODE) {
        0 { Write-Output "RESULT: $name - no issues found." }
        1 { Write-Output "RESULT: $name - issues found (scan succeeded)."; $script:Findings = $true }
        default { Write-Output "RESULT: $name - error (exit $LASTEXITCODE). See output above." }
    }
}

if ($Scan -in @('sca', 'all')) {
    Invoke-Scan 'SCA (dependencies)' (@('test', '--all-projects', '--detection-depth=4') + $sevArgs)
}
if ($Scan -in @('code', 'all')) {
    Invoke-Scan 'Code (SAST)' (@('code', 'test', $Target) + $sevArgs)
}
if ($Scan -in @('iac', 'all')) {
    Invoke-Scan 'IaC' (@('iac', 'test', $Target) + $sevArgs)
}
if ($Scan -eq 'container') {
    if (-not $Image) { Write-Output 'ERROR: container scan requires -Image <image:tag>'; exit 2 }
    Invoke-Scan 'Container' (@('container', 'test', $Image) + $sevArgs)
}
elseif ($Scan -eq 'all' -and $Image) {
    Invoke-Scan 'Container' (@('container', 'test', $Image) + $sevArgs)
}

if ($script:Findings) { exit 1 } else { exit 0 }
