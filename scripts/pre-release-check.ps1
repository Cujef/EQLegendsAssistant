#requires -Version 5.1
<#
.SYNOPSIS
    Read-only pre-release GO / NO-GO gate enforcing this project's release discipline.

.DESCRIPTION
    Verifies (without mutating anything remote) that a project is ready to tag
    and release:
      1. Detects the project stack from manifest files.
      2. Confirms the manifest version matches -ExpectedVersion (if provided)
         and that the version is not already tagged.
      3. Confirms CHANGELOG.md contains an entry for that version.
      4. Runs the stack's build / smoke step and checks the exit code.
      5. Prints a clear GO or NO-GO summary.

    EXPLICITLY does NOT push, tag, publish, or create a release. It only reads
    and runs local build/test commands. Safe to run anytime.

.PARAMETER ExpectedVersion
    The version you intend to release, e.g. 1.3.0 (no leading 'v'). If omitted,
    the script reports the detected manifest version and skips the match check.

.PARAMETER SkipBuild
    Skip the build/smoke step (only do version + changelog checks).

.PARAMETER NodeSmokeCommand
    Override the node smoke command (default 'npm test'). Use this when the
    project's smoke step is e.g. 'npm run build' or there is no test script.
    The string is run as-is. Ignored for non-node stacks.

.EXAMPLE
    pwsh -File scripts/pre-release-check.ps1 -ExpectedVersion 1.3.0

.EXAMPLE
    pwsh -File scripts/pre-release-check.ps1 -ExpectedVersion 1.3.0 -NodeSmokeCommand 'npm run build'
#>
[CmdletBinding()]
param(
    [string]$ExpectedVersion,
    [switch]$SkipBuild,
    [string]$NodeSmokeCommand
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Problems = New-Object System.Collections.Generic.List[string]
$script:Notes    = New-Object System.Collections.Generic.List[string]

function Add-Problem([string]$m) { $script:Problems.Add($m); Write-Host "  [FAIL] $m" -ForegroundColor Red }
function Add-Ok([string]$m)      { Write-Host "  [ OK ] $m" -ForegroundColor Green }
function Add-Note([string]$m)    { $script:Notes.Add($m); Write-Host "  [note] $m" -ForegroundColor DarkGray }

# Resolve repo root (parent of this script's folder).
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Write-Host "Pre-release check (read-only) in: $RepoRoot" -ForegroundColor Cyan
Write-Host "This script will NOT push, tag, or publish anything." -ForegroundColor Cyan
Write-Host ''

# --- 1. Detect stack + manifest version --------------------------------------
function Get-ManifestInfo {
    param([string]$Root)
    $pkg = Join-Path $Root 'package.json'
    if (Test-Path $pkg) {
        $json = $null
        try { $json = (Get-Content $pkg -Raw | ConvertFrom-Json) } catch { $json = $null }
        $v = if ($json) { $json.version } else { $null }
        # Detect whether a runnable 'test' script exists (so we don't run npm test into a default-fail).
        $hasTest = $false
        if ($json -and ($json.PSObject.Properties.Name -contains 'scripts')) {
            $scripts = $json.scripts
            if ($scripts -and ($scripts.PSObject.Properties.Name -contains 'test')) {
                $testCmd = [string]$scripts.test
                # npm's default placeholder exits 1; treat that as 'no real test'.
                if ($testCmd -and ($testCmd -notmatch 'no test specified')) { $hasTest = $true }
            }
        }
        $tauri = Join-Path $Root 'src-tauri/tauri.conf.json'
        if (-not (Test-Path $tauri)) { $tauri = Join-Path $Root 'tauri.conf.json' }
        $stack = if (Test-Path $tauri) { 'tauri' } else { 'node' }
        return [pscustomobject]@{ Stack = $stack; Version = $v; File = 'package.json'; HasTestScript = $hasTest }
    }
    $pyproject = Join-Path $Root 'pyproject.toml'
    if (Test-Path $pyproject) {
        $m = Select-String -Path $pyproject -Pattern '^\s*version\s*=\s*"([^"]+)"' | Select-Object -First 1
        $v = if ($m) { $m.Matches[0].Groups[1].Value } else { $null }
        return [pscustomobject]@{ Stack = 'python'; Version = $v; File = 'pyproject.toml'; HasTestScript = $false }
    }
    $gradleProps = Join-Path $Root 'gradle.properties'
    if (Test-Path $gradleProps) {
        $m = Select-String -Path $gradleProps -Pattern '^\s*version\s*=\s*(.+)$' | Select-Object -First 1
        $v = if ($m) { $m.Matches[0].Groups[1].Value.Trim() } else { $null }
        return [pscustomobject]@{ Stack = 'gradle'; Version = $v; File = 'gradle.properties'; HasTestScript = $false }
    }
    if ((Test-Path (Join-Path $Root 'build.gradle')) -or (Test-Path (Join-Path $Root 'build.gradle.kts'))) {
        return [pscustomobject]@{ Stack = 'gradle'; Version = $null; File = 'build.gradle'; HasTestScript = $false }
    }
    $cargo = Join-Path $Root 'Cargo.toml'
    if (Test-Path $cargo) {
        $m = Select-String -Path $cargo -Pattern '^\s*version\s*=\s*"([^"]+)"' | Select-Object -First 1
        $v = if ($m) { $m.Matches[0].Groups[1].Value } else { $null }
        return [pscustomobject]@{ Stack = 'rust'; Version = $v; File = 'Cargo.toml'; HasTestScript = $false }
    }
    return [pscustomobject]@{ Stack = 'unknown'; Version = $null; File = $null; HasTestScript = $false }
}

Write-Host 'Step 1: detect stack and manifest version' -ForegroundColor White
$info = Get-ManifestInfo -Root $RepoRoot
if ($info.Stack -eq 'unknown') {
    Add-Note 'No known manifest detected (package.json/pyproject.toml/gradle/Cargo.toml).'
} else {
    Add-Ok "Stack: $($info.Stack); manifest: $($info.File); version: $($info.Version)"
}

# --- 2. Version match + not-already-tagged -----------------------------------
Write-Host 'Step 2: version checks' -ForegroundColor White
if ($ExpectedVersion) {
    if ($info.Version -and ($info.Version -ne $ExpectedVersion)) {
        Add-Problem "Manifest version '$($info.Version)' != expected '$ExpectedVersion'. Bump the manifest."
    } elseif ($info.Version -eq $ExpectedVersion) {
        Add-Ok "Manifest version matches expected: $ExpectedVersion"
    } else {
        Add-Note "Could not read manifest version; expected $ExpectedVersion."
    }

    # Is this version already tagged? (read-only git)
    $tag = "v$ExpectedVersion"
    $gitDir = Join-Path $RepoRoot '.git'
    if (Test-Path $gitDir) {
        $existing = & git -C $RepoRoot tag --list $tag
        if ($LASTEXITCODE -eq 0 -and $existing) {
            Add-Problem "Tag '$tag' already exists. Pick a new version or delete the local tag."
        } else {
            Add-Ok "Tag '$tag' is not yet present (good)."
        }
    } else {
        Add-Note 'Not a git repo (no .git) - skipping tag check.'
    }
} else {
    Add-Note 'No -ExpectedVersion supplied; skipping version-match and tag checks.'
}

# --- 3. CHANGELOG entry ------------------------------------------------------
Write-Host 'Step 3: CHANGELOG entry' -ForegroundColor White
$changelog = Join-Path $RepoRoot 'CHANGELOG.md'
if (-not (Test-Path $changelog)) {
    Add-Problem 'CHANGELOG.md not found at repo root. Add one (Keep a Changelog format).'
} elseif ($ExpectedVersion) {
    $content = Get-Content $changelog -Raw
    # Match a heading like: ## [1.3.0] - 2026-06-26  (date optional but recommended)
    $pattern = "##\s*\[?" + [regex]::Escape($ExpectedVersion) + "\]?"
    if ($content -match $pattern) {
        Add-Ok "CHANGELOG.md has an entry for $ExpectedVersion"
        if ($content -notmatch ($pattern + ".*\d{4}-\d{2}-\d{2}")) {
            Add-Note 'CHANGELOG entry has no ISO date (YYYY-MM-DD) on the heading line.'
        }
    } else {
        Add-Problem "CHANGELOG.md has no entry for $ExpectedVersion. Add it BEFORE tagging."
    }
} else {
    Add-Note 'CHANGELOG.md present; no version supplied to verify its entry.'
}

# --- 4. Build / smoke step ---------------------------------------------------
Write-Host 'Step 4: build / smoke' -ForegroundColor White
function Invoke-Step {
    param([string]$Label, [scriptblock]$Action)
    Write-Host "  running: $Label" -ForegroundColor DarkGray
    try {
        & $Action
        if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) {
            Add-Problem "$Label failed (exit $LASTEXITCODE)."
            return $false
        }
        Add-Ok "$Label passed."
        return $true
    } catch {
        Add-Problem "$Label threw: $($_.Exception.Message)"
        return $false
    }
}

if ($SkipBuild) {
    Add-Note 'Build/smoke skipped (-SkipBuild).'
} else {
    Push-Location $RepoRoot
    try {
        switch ($info.Stack) {
            'python' {
                # This project's gate is selftest.py (auto-discovered suites),
                # not pytest — prefer it when present so a release actually runs
                # the checks instead of silently skipping them.
                if (Test-Path (Join-Path $RepoRoot 'selftest.py')) {
                    [void](Invoke-Step 'python selftest.py' { python selftest.py })
                } elseif (Get-Command pytest -ErrorAction SilentlyContinue) {
                    [void](Invoke-Step 'pytest -q' { pytest -q })
                } else {
                    Add-Note 'pytest not found on PATH; skipping Python smoke.'
                }
            }
            'node' {
                if ($NodeSmokeCommand) {
                    # Explicit override wins. Run it through cmd so a full command line works.
                    [void](Invoke-Step $NodeSmokeCommand { cmd /c $NodeSmokeCommand })
                } elseif ($info.HasTestScript) {
                    [void](Invoke-Step 'npm test' { npm test --silent })
                } else {
                    Add-Note 'No runnable npm "test" script found; skipping node smoke. Override with -NodeSmokeCommand to run a build/smoke step.'
                }
            }
            'tauri' {
                if ($NodeSmokeCommand) {
                    [void](Invoke-Step $NodeSmokeCommand { cmd /c $NodeSmokeCommand })
                } else {
                    [void](Invoke-Step 'npm run build' { npm run build })
                }
            }
            'gradle' {
                $gw = Join-Path $RepoRoot 'gradlew.bat'
                if (Test-Path $gw) {
                    [void](Invoke-Step '.\gradlew.bat test' { & $gw test })
                } else {
                    Add-Note 'gradlew.bat not found; skipping Gradle test.'
                }
            }
            'rust' {
                if (Get-Command cargo -ErrorAction SilentlyContinue) {
                    [void](Invoke-Step 'cargo test' { cargo test --quiet })
                } else {
                    Add-Note 'cargo not found; skipping Rust test.'
                }
            }
            default {
                Add-Note 'Unknown stack; no build/smoke command to run.'
            }
        }
    } finally {
        Pop-Location
    }
}

# --- 5. Verdict --------------------------------------------------------------
Write-Host ''
Write-Host '====================================' -ForegroundColor White
if ($script:Problems.Count -eq 0) {
    Write-Host ' VERDICT: GO' -ForegroundColor Green
    Write-Host ' All checks passed. Safe to proceed to the CONSENT GATE.' -ForegroundColor Green
    Write-Host ' Reminder: still get explicit consent before any push / tag-push / release.' -ForegroundColor Yellow
    $exit = 0
} else {
    Write-Host ' VERDICT: NO-GO' -ForegroundColor Red
    Write-Host " $($script:Problems.Count) blocking issue(s):" -ForegroundColor Red
    foreach ($p in $script:Problems) { Write-Host "   - $p" -ForegroundColor Red }
    $exit = 1
}
Write-Host '====================================' -ForegroundColor White
Write-Host 'This script did not push, tag, or publish anything.' -ForegroundColor Cyan
exit $exit
