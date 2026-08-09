<#
Build a shareable, versioned Snyk skill archive.
Usage:
  powershell -NoProfile -ExecutionPolicy Bypass -File package-skill.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File package-skill.ps1 -OutputDirectory C:\releases
#>
param(
    [string]$OutputDirectory = '',
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$skillRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $skillRoot '..\..\..')).Path
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repoRoot 'dist' }

$versionFile = Join-Path $skillRoot 'VERSION'
$version = (Get-Content -Path $versionFile -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$') {
    throw "VERSION must contain a semantic version; found '$version'."
}

$requiredFiles = @(
    'SKILL.md',
    'README.md',
    'VERSION',
    'CHANGELOG.md',
    'scripts\snyk-scan.ps1',
    'scripts\snyk-scan.sh',
    'scripts\package-skill.ps1',
    'references\commands.md',
    'references\output-template.md',
    'references\remediation.md',
    'tests\test-snyk-scan.ps1',
    'tests\test-snyk-scan.sh'
)
foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -Path (Join-Path $skillRoot $relativePath) -PathType Leaf)) {
        throw "Required package file is missing: $relativePath"
    }
}

$skillDocument = Get-Content -Path (Join-Path $skillRoot 'SKILL.md') -Raw
if ($skillDocument -notmatch '(?ms)\A---\s*$.*?^name:\s*snyk\s*$.*?^description:\s*.+?^---\s*$') {
    throw 'SKILL.md frontmatter is missing a valid name or description.'
}

if (-not $SkipTests) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $skillRoot 'tests\test-snyk-scan.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'PowerShell scan contract tests failed.' }

    $gitBash = 'C:\Program Files\Git\bin\bash.exe'
    if (Test-Path $gitBash) {
        & $gitBash (Join-Path $skillRoot 'tests\test-snyk-scan.sh')
        if ($LASTEXITCODE -ne 0) { throw 'Bash scan contract tests failed.' }
    }
    else {
        Write-Warning 'Git Bash is unavailable; Bash contract tests were not run.'
    }
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$stagingRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("snyk-skill-package-" + [guid]::NewGuid().ToString('N'))
$stagedSkill = Join-Path $stagingRoot 'snyk'
$versionedArchive = Join-Path $OutputDirectory "snyk-skill-v$version.zip"
$stableArchive = Join-Path $OutputDirectory 'snyk-skill.zip'
$checksumFile = "$versionedArchive.sha256"

try {
    New-Item -ItemType Directory -Path $stagedSkill -Force | Out-Null
    foreach ($name in @('SKILL.md', 'README.md', 'VERSION', 'CHANGELOG.md')) {
        Copy-Item -Path (Join-Path $skillRoot $name) -Destination $stagedSkill
    }
    foreach ($name in @('scripts', 'references', 'tests')) {
        Copy-Item -Path (Join-Path $skillRoot $name) -Destination (Join-Path $stagedSkill $name) -Recurse
    }

    $manifestLines = Get-ChildItem -Path $stagedSkill -Recurse -File |
        Sort-Object FullName |
        ForEach-Object {
            $relativePath = $_.FullName.Substring($stagedSkill.Length + 1).Replace('\', '/')
            $hash = (Get-FileHash -Path $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            "$hash  $relativePath"
        }
    $manifestLines | Set-Content -Path (Join-Path $stagedSkill 'MANIFEST.sha256') -Encoding ASCII

    Remove-Item -Path $versionedArchive, $stableArchive, $checksumFile -Force -ErrorAction SilentlyContinue
    Compress-Archive -Path $stagedSkill -DestinationPath $versionedArchive -CompressionLevel Optimal
    Copy-Item -Path $versionedArchive -Destination $stableArchive

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($versionedArchive)
    try {
        $entryNames = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
        foreach ($entry in @('snyk/SKILL.md', 'snyk/VERSION', 'snyk/MANIFEST.sha256')) {
            if ($entryNames -notcontains $entry) { throw "Archive validation failed: missing $entry" }
        }
    }
    finally {
        $archive.Dispose()
    }

    $archiveHash = (Get-FileHash -Path $versionedArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    "$archiveHash  $([System.IO.Path]::GetFileName($versionedArchive))" |
        Set-Content -Path $checksumFile -Encoding ASCII

    Write-Output "PACKAGE: $versionedArchive"
    Write-Output "ALIAS: $stableArchive"
    Write-Output "SHA256: $archiveHash"
}
finally {
    Remove-Item -Path $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
}