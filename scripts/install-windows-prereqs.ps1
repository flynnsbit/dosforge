# install-windows-prereqs.ps1
#
# Idempotent winget-based installer for the Windows host prereqs that
# dosforge's editable install and scripts/fetch-windows-vendor.py
# depend on:
#
#   - Python.Python.3.12     (dosforge requires Python >= 3.11)
#   - 7zip.7zip              (>= 23.x; needed to unpack the NSIS-format
#                             QEMU installer used by the fetch script)
#   - dscharrer.innoextract  (legacy Inno-Setup fallback for the fetch
#                             script; small download, harmless to install)
#
# Run this BEFORE creating the project venv or invoking the vendor
# fetcher. Subsequent recommended steps:
#
#     py -3.12 -m venv .venv
#     .\.venv\Scripts\Activate.ps1
#     pip install -e .[dev]
#     pip install zstandard
#     python scripts/fetch-windows-vendor.py

[CmdletBinding()]
param(
    [switch] $Quiet
)

$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string] $Message)
    if (-not $Quiet) {
        Write-Host "[install-windows-prereqs] $Message" -ForegroundColor Cyan
    }
}

function Test-PackageInstalled {
    param([string] $WingetId)
    $null = winget list --id $WingetId --accept-source-agreements 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Install-IfMissing {
    param(
        [Parameter(Mandatory)][string] $WingetId,
        [Parameter(Mandatory)][string] $FriendlyName
    )
    if (Test-PackageInstalled -WingetId $WingetId) {
        Write-Step "$FriendlyName already installed ($WingetId) - skipping."
        return
    }
    Write-Step "Installing $FriendlyName ($WingetId) ..."
    winget install --id $WingetId --accept-source-agreements --accept-package-agreements --silent | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "winget install failed for $WingetId (exit $LASTEXITCODE)."
    }
    Write-Step "$FriendlyName installed."
}

function Update-PathFromRegistry {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $combined    = $machinePath + ';' + $userPath
    Set-Item -Path Env:Path -Value $combined
}

# --- Main ------------------------------------------------------------------

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget is required but not found. Install 'App Installer' from the Microsoft Store, then re-run this script."
}

Install-IfMissing -WingetId 'Python.Python.3.12'    -FriendlyName 'Python 3.12'
Install-IfMissing -WingetId '7zip.7zip'             -FriendlyName '7-Zip'
Install-IfMissing -WingetId 'dscharrer.innoextract' -FriendlyName 'innoextract'

Update-PathFromRegistry

Write-Step "Verifying installs ..."

if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3.12 --version
} else {
    Write-Warning "py launcher not on PATH yet; open a new shell to use Python 3.12."
}

$sevenZip = Join-Path $env:ProgramFiles '7-Zip\7z.exe'
if (Test-Path $sevenZip) {
    & $sevenZip | Select-Object -First 1 | ForEach-Object { Write-Host $_ }
} else {
    Write-Warning "7-Zip not found at $sevenZip; open a new shell or verify the install."
}

if (Get-Command innoextract -ErrorAction SilentlyContinue) {
    innoextract --version | Select-Object -First 1
} else {
    Write-Warning "innoextract not on PATH yet; open a new shell to pick it up."
}

Write-Step "All host prerequisites are installed."
Write-Step "Next steps (run from the repo root):"
Write-Host "    py -3.12 -m venv .venv"
Write-Host "    .\.venv\Scripts\Activate.ps1"
Write-Host "    pip install -e .[dev] zstandard"
Write-Host "    python scripts/fetch-windows-vendor.py"
