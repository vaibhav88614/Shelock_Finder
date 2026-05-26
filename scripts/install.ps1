#requires -Version 5.1
<#
.SYNOPSIS
    Bootstrap a JobPulse dev environment on Windows.

.DESCRIPTION
    - Installs uv if missing.
    - Creates .venv via uv.
    - Installs pinned deps from requirements.lock.
    - Runs DB migrations + seed.
    - Builds the frontend (if Node 20+ is on PATH).

.PARAMETER SkipFrontend
    Skip 'npm install' + 'npm run build'.

.PARAMETER SkipPlaywright
    Skip 'playwright install chromium' (saves ~150 MB).

.EXAMPLE
    .\scripts\install.ps1
    .\scripts\install.ps1 -SkipFrontend -SkipPlaywright
#>
[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$SkipPlaywright
)

$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..'))

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }

# ---------- 1. uv ----------
Write-Step 'Checking for uv'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host '    uv not found; installing from astral.sh ...' -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c 'irm https://astral.sh/uv/install.ps1 | iex'
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'uv install failed. Add ~/.local/bin to PATH and rerun.'
    }
}
Write-Ok ((uv --version) -join ' ')

# ---------- 2. Python venv ----------
Write-Step 'Creating .venv (Python 3.13+)'
if (-not (Test-Path .venv)) {
    uv venv --python 3.13 .venv
} else {
    Write-Ok '.venv already exists; reusing'
}

# ---------- 3. Install pinned deps ----------
Write-Step 'Installing locked dependencies (uv pip sync requirements.lock)'
$env:VIRTUAL_ENV = (Resolve-Path .venv).Path
uv pip sync requirements.lock
Write-Ok 'Backend deps installed'

# ---------- 4. Playwright browser (optional) ----------
if (-not $SkipPlaywright) {
    Write-Step 'Installing Playwright Chromium (use -SkipPlaywright to skip)'
    & .venv\Scripts\python.exe -m playwright install chromium
} else {
    Write-Ok 'Skipped Playwright browser download'
}

# ---------- 5. DB ----------
Write-Step 'Running migrations + seed'
& .venv\Scripts\python.exe run.py migrate
& .venv\Scripts\python.exe run.py seed

# ---------- 6. Frontend ----------
if (-not $SkipFrontend) {
    Write-Step 'Building frontend (Node 20+ required)'
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Host '    npm not found; skipping frontend build.' -ForegroundColor Yellow
    } else {
        Push-Location frontend
        try {
            npm install --no-audit --no-fund
            npm run build
        } finally {
            Pop-Location
        }
        Write-Ok 'Frontend built to frontend/dist/'
    }
} else {
    Write-Ok 'Skipped frontend build'
}

Write-Host ''
Write-Host 'Done. Next steps:' -ForegroundColor Green
Write-Host '  .\.venv\Scripts\Activate.ps1'
Write-Host '  python run.py scrape         # first scrape (1-5 min)'
Write-Host '  python run.py serve          # http://127.0.0.1:8000'
