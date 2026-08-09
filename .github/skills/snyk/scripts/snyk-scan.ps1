<#
One-shot Snyk preflight + scan (Windows).
Usage:
  powershell -ExecutionPolicy Bypass -File snyk-scan.ps1 -Scan all
  powershell -ExecutionPolicy Bypass -File snyk-scan.ps1 -Scan all -Org <org-id>
  powershell -ExecutionPolicy Bypass -File snyk-scan.ps1 -Scan iac -Target iac/
  powershell -ExecutionPolicy Bypass -File snyk-scan.ps1 -Scan container -Image node:18-alpine
  powershell -ExecutionPolicy Bypass -File snyk-scan.ps1 -Scan container -Dockerfile Dockerfile.node
    (extracts the base image from the FROM line and scans it WITH base-image remediation advice)
Exit codes: 0 = clean, 1 = issues found (scan SUCCEEDED), 2 = setup/scan error,
            3 = no supported targets found
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet('all', 'sca', 'code', 'iac', 'container')][string]$Scan,
    [string]$Target = '.',
    [string]$Image = '',
    [string]$Dockerfile = '',
    [string]$Org = '',
    [ValidateSet('', 'low', 'medium', 'high', 'critical')][string]$SeverityThreshold = ''
)
# Windows PowerShell can surface native stderr as non-terminating ErrorRecord objects.
# Keep those records in the scan output and decide success from the native exit code.
$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$script:Findings = $false
$script:ScanError = $false
$script:NoProjects = $false
$sevArgs = @(); if ($SeverityThreshold) { $sevArgs = @("--severity-threshold=$SeverityThreshold") }

function Write-Section([string]$t) { Write-Output ''; Write-Output "===== $t =====" }

function Get-OverallExitCode {
    if ($script:ScanError) { return 2 }
    if ($script:NoProjects) { return 3 }
    if ($script:Findings) { return 1 }
    return 0
}

function Get-DockerfileBaseImage([string]$path) {
    $arguments = @{}
    $image = ''
    foreach ($line in (Get-Content -Path $path)) {
        if ($line -match '^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)=(\S+)\s*(?:#.*)?$') {
            $arguments[$Matches[1]] = $Matches[2]
            continue
        }
        if ($line -match '^\s*FROM\s+(.+?)\s*(?:#.*)?$') {
            $image = (($Matches[1] -split '\s+') | Where-Object { $_ -and $_ -notmatch '^--' } | Select-Object -First 1)
        }
    }
    foreach ($name in $arguments.Keys) {
        $image = $image.Replace(('${' + $name + '}'), $arguments[$name]).Replace(('$' + $name), $arguments[$name])
    }
    return $image
}

function Test-ContainerInput([string]$dockerfilePath, [string]$imageName) {
    if ($dockerfilePath -and -not (Test-Path -Path $dockerfilePath -PathType Leaf)) {
        Write-Output "ERROR: Dockerfile not found: $dockerfilePath"
        return $false
    }
    if ($imageName -match '\$') {
        Write-Output "ERROR: Dockerfile base image '$imageName' contains an unresolved ARG. Pass -Image <image:tag>."
        return $false
    }
    return $true
}

# --- 1. Ensure CLI installed ---
if (-not (Get-Command snyk -ErrorAction SilentlyContinue)) {
    $installLog = Join-Path $env:TEMP 'snyk-npm-install.log'
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Section 'Installing Snyk CLI via npm'
        npm install -g snyk *> $installLog
    }
    if (-not (Get-Command snyk -ErrorAction SilentlyContinue)) {
        Write-Output 'ERROR: Snyk CLI not found and could not be installed automatically.'
        if (Test-Path $installLog) { Write-Output "npm install log: $installLog" }
        Write-Output 'Install Node.js (https://nodejs.org) and re-run, or install the CLI manually:'
        Write-Output 'https://docs.snyk.io/snyk-cli/install-or-update-the-snyk-cli'
        exit 2
    }
}

# --- 2. Best-effort update to latest (throttled: network check at most once per day) ---
$installed = (& snyk --version 2>$null | Select-Object -First 1)
$stamp = Join-Path $env:TEMP 'snyk-cli-update-check.txt'
$today = Get-Date -Format 'yyyyMMdd'
if ((Get-Command npm -ErrorAction SilentlyContinue) -and ((Get-Content $stamp -ErrorAction SilentlyContinue) -ne $today)) {
    $latest = (npm view snyk version 2>$null)
    if ($latest -and $installed -and ("$installed".Trim() -ne "$latest".Trim())) {
        Write-Output "Updating Snyk CLI $installed -> $latest"
        $updateLog = Join-Path $env:TEMP 'snyk-npm-update.log'
        npm install -g snyk@latest *> $updateLog
        if ($LASTEXITCODE -ne 0) { Write-Output "WARN: update failed (continuing with $installed) - log: $updateLog" }
        $installed = (& snyk --version 2>$null | Select-Object -First 1)
    }
    Set-Content -Path $stamp -Value $today
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
    # 'analysis for' matches the Snyk Code progress spinner; intentionally minimal filter -
    # extend the pattern only if other scan types add progress chatter
    & snyk @snykArgs 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -notmatch 'analysis for' }
    $scanExitCode = $LASTEXITCODE
    switch ($scanExitCode) {
        0 { Write-Output "RESULT: $name - no issues found." }
        1 { Write-Output "RESULT: $name - issues found (scan succeeded)."; $script:Findings = $true }
        3 { Write-Output "RESULT: $name - skipped (no supported targets found)."; $script:NoProjects = $true }
        default { Write-Output "RESULT: $name - error (exit $scanExitCode). See output above."; $script:ScanError = $true }
    }
}

# Container-only runs skip SCA/Code/IaC entirely (mirrors the .sh script's behavior).
if ($Scan -eq 'container') {
    if (-not $Image -and $Dockerfile) {
        if (-not (Test-ContainerInput $Dockerfile '')) { exit 2 }
        $Image = Get-DockerfileBaseImage $Dockerfile
        if ($Image) { Write-Output "Extracted base image from ${Dockerfile}: $Image" }
        else { Write-Output "ERROR: no FROM line found in $Dockerfile. Pass -Image <image:tag> instead."; exit 2 }
    }
    if (-not $Image) { Write-Output 'ERROR: container scan requires -Image <image:tag> or -Dockerfile <path>'; exit 2 }
    if (-not (Test-ContainerInput $Dockerfile $Image)) { exit 2 }
    $cArgs = @('container', 'test', $Image) + $sevArgs
    if ($Dockerfile) { $cArgs += @("--file=$((Resolve-Path $Dockerfile).Path)") }
    Invoke-Scan 'Container' $cArgs
    exit (Get-OverallExitCode)
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
if ($Scan -eq 'all' -and $Image) {
    if (-not (Test-ContainerInput $Dockerfile $Image)) { exit 2 }
    $cArgs = @('container', 'test', $Image) + $sevArgs
    if ($Dockerfile) { $cArgs += @("--file=$((Resolve-Path $Dockerfile).Path)") }
    Invoke-Scan 'Container' $cArgs
}
elseif ($Scan -eq 'all') {
    # Auto-discover Dockerfiles so container coverage is never silently skipped.
    $dockerfiles = Get-ChildItem -Recurse -Filter 'Dockerfile*' -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -inotmatch '\\(node_modules|\.git|target|dist|build)\\' } |
        Sort-Object FullName
    if ($dockerfiles) {
        foreach ($df in $dockerfiles) {
            $img = Get-DockerfileBaseImage $df.FullName
            if (-not $img) { Write-Output "RESULT: Container ($($df.Name)) - skipped (no FROM line found)."; $script:ScanError = $true; continue }
            if ($img -match '\$') { Write-Output "RESULT: Container ($($df.Name)) - skipped (unresolved ARG in base image; pass -Image)."; $script:ScanError = $true; continue }
            # Resolve to an absolute path: snyk code test can change the CLI's working dir,
            # so a relative --file path breaks later scans in the same run.
            $dfAbs = (Resolve-Path $df.FullName).Path
            Write-Output "Auto-discovered $($df.Name) -> base image $img"
            Invoke-Scan "Container ($($df.Name))" (@('container', 'test', $img, "--file=$dfAbs") + $sevArgs)
        }
    }
    else {
        Write-Output ''
        Write-Output 'RESULT: Container - skipped (no -Image provided and no Dockerfile* found).'
    }
}

exit (Get-OverallExitCode)
