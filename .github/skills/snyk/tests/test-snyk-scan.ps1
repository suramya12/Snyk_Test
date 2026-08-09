$ErrorActionPreference = 'Stop'

$skillRoot = Split-Path -Parent $PSScriptRoot
$scanScript = Join-Path $skillRoot 'scripts\snyk-scan.ps1'
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("snyk-skill-test-" + [guid]::NewGuid().ToString('N'))
$binDir = Join-Path $testRoot 'bin'
$originalPath = $env:Path
$originalTemp = $env:TEMP

function Assert-ScanExit([int]$mockExit, [int]$expectedExit, [string]$expectedResult) {
    $env:MOCK_SNYK_EXIT = "$mockExit"
    $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $scanScript -Scan code 2>&1
    $actualExit = $LASTEXITCODE
    if ($actualExit -ne $expectedExit) {
        throw "Mock exit $mockExit produced script exit $actualExit; expected $expectedExit.`n$output"
    }
    if (($output -join "`n") -notmatch [regex]::Escape($expectedResult)) {
        throw "Expected result line '$expectedResult' was not emitted.`n$output"
    }
}

try {
    New-Item -ItemType Directory -Path $binDir -Force | Out-Null
    @'
@echo off
if "%1"=="--version" (
  echo 1.1306.3
  exit /b 0
)
if "%1"=="whoami" exit /b 0
if "%1"=="config" exit /b 0
echo Mock Snyk scan output
if "%MOCK_CONTAINER_FINDINGS%"=="1" if "%1"=="container" exit /b 1
exit /b %MOCK_SNYK_EXIT%
'@ | Set-Content -Path (Join-Path $binDir 'snyk.cmd') -Encoding ASCII

    $env:TEMP = $testRoot
    $env:Path = "$binDir;$originalPath"
    Set-Content -Path (Join-Path $testRoot 'snyk-cli-update-check.txt') -Value (Get-Date -Format 'yyyyMMdd')

    Assert-ScanExit 0 0 'RESULT: Code (SAST) - no issues found.'
    Assert-ScanExit 1 1 'RESULT: Code (SAST) - issues found (scan succeeded).'
    Assert-ScanExit 2 2 'RESULT: Code (SAST) - error (exit 2).'
    Assert-ScanExit 3 3 'RESULT: Code (SAST) - skipped (no supported targets found).'

    $workspace = Join-Path $testRoot 'workspace with spaces'
    New-Item -ItemType Directory -Path $workspace | Out-Null
    "ARG BASE_IMAGE=alpine:3.20`nFROM --platform=linux/amd64 `${BASE_IMAGE}`n" |
        Set-Content -Path (Join-Path $workspace 'Dockerfile') -Encoding ASCII
    $env:MOCK_SNYK_EXIT = '0'
    $env:MOCK_CONTAINER_FINDINGS = '1'
    Push-Location $workspace
    try {
        $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $scanScript -Scan all 2>&1
        $actualExit = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($actualExit -ne 1 -or ($output -join "`n") -notmatch 'base image alpine:3\.20') {
        throw "Auto-discovered container scan failed its contract (exit $actualExit).`n$output"
    }
    Write-Output 'PowerShell scan contract tests: PASS'
}
finally {
    $env:Path = $originalPath
    $env:TEMP = $originalTemp
    Remove-Item Env:MOCK_SNYK_EXIT -ErrorAction SilentlyContinue
    Remove-Item Env:MOCK_CONTAINER_FINDINGS -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $testRoot -ErrorAction SilentlyContinue
}