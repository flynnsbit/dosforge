# Build the dosforge lite Windows bundle.
#
# Produces dist\dosforge\ with the structured layout:
#   dosforge.exe       — launcher
#   dosassets\         — per-mode readme stubs (user drops install media here)
#   _internal\         — Python runtime + vendor binaries (QEMU, mtools)
#
# Prerequisites:
#   1. Activate the project venv:   .\.venv\Scripts\Activate.ps1
#   2. Fetch vendor binaries:       python scripts\fetch-windows-vendor.py
#   3. Run this script:             .\scripts\build-lite-bundle.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot

# Verify venv
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Error "Venv not found at $venvPython. Run: python -m venv .venv && .venv\Scripts\pip install -e .[dev] pyinstaller py7zr"
}

# Verify vendor binaries
$vendorBin = Join-Path $repoRoot 'vendor\windows\bin'
if (-not (Test-Path (Join-Path $vendorBin 'qemu-img.exe'))) {
    Write-Error "Vendor binaries missing. Run: python scripts\fetch-windows-vendor.py"
}

Write-Host "Building dosforge lite bundle..." -ForegroundColor Cyan
Push-Location $repoRoot
try {
    & $venvPython -m PyInstaller windows\dosforge-lite.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$distDir = Join-Path $repoRoot 'dist\dosforge'
$totalMB  = [math]::Round((Get-ChildItem $distDir -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1)
$exeMB    = [math]::Round((Get-Item (Join-Path $distDir 'dosforge.exe')).Length / 1MB, 1)

Write-Host ""
Write-Host "Lite bundle complete: $distDir" -ForegroundColor Green
Write-Host "  dosforge.exe : $exeMB MB"
Write-Host "  Total        : $totalMB MB"
Write-Host ""
Write-Host "Layout:"
Get-ChildItem $distDir | ForEach-Object {
    $sz = if ($_.PSIsContainer) {
        [math]::Round((Get-ChildItem $_.FullName -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1)
    } else {
        [math]::Round($_.Length / 1MB, 1)
    }
    Write-Host ("  {0,-30} {1,6} MB" -f $_.Name, $sz)
}
