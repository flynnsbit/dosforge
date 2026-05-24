# Build the dosforge CLI-only Windows bundle.
#
# Produces dist\dosforge\ with the minimal layout:
#   dosforge.exe       - launcher
#   dosassets\         - per-mode readme stubs (user drops install media here)
#   _internal\         - Python runtime + vendor binaries (qemu-img + mtools only)
#
# 8 of 11 boot modes work.  The 3 modes that need qemu-system-i386
# (compaq331, msdos33, msdos331) are NOT supported in this bundle; the
# CLI's dependency check produces a clear "Missing required tools:
# qemu-system-i386" error when those modes are requested.
#
# Prerequisites:
#   1. Activate the project venv:   .\.venv\Scripts\Activate.ps1
#   2. Fetch vendor binaries:       python scripts\fetch-windows-vendor.py
#   3. Run this script:             .\scripts\build-cli-bundle.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot

$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Error "Venv not found at $venvPython. Run: python -m venv .venv && .venv\Scripts\pip install -e .[dev] pyinstaller"
}

$vendorBin = Join-Path $repoRoot 'vendor\windows\bin'
if (-not (Test-Path (Join-Path $vendorBin 'qemu-img.exe'))) {
    Write-Error "Vendor binaries missing. Run: python scripts\fetch-windows-vendor.py"
}

Write-Host "Building dosforge CLI-only bundle..." -ForegroundColor Cyan
Push-Location $repoRoot
try {
    & $venvPython -m PyInstaller windows\dosforge-cli.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$distDir = Join-Path $repoRoot 'dist\dosforge'
$totalMB  = [math]::Round((Get-ChildItem $distDir -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1)
$exeMB    = [math]::Round((Get-Item (Join-Path $distDir 'dosforge.exe')).Length / 1MB, 1)
$vendorMB = [math]::Round((Get-ChildItem (Join-Path $distDir '_internal\vendor\windows\bin') | Measure-Object Length -Sum).Sum / 1MB, 1)

Write-Host ""
Write-Host "CLI bundle complete: $distDir" -ForegroundColor Green
Write-Host "  dosforge.exe : $exeMB MB"
Write-Host "  vendor/      : $vendorMB MB (qemu-img + mtools + 28 DLLs)"
Write-Host "  Total        : $totalMB MB"
Write-Host ""
Write-Host "Note: this CLI bundle does NOT include qemu-system-i386." -ForegroundColor Yellow
Write-Host "      Boot modes compaq331, msdos33, msdos331 are unavailable."
