# dosforge.ps1 — PowerShell launcher.
#
# Forwards every argument to the PyInstaller-built bundle under
# dist\dosforge\. Build the bundle once with
# `.\.venv\Scripts\python.exe -m PyInstaller windows\dosforge.spec --noconfirm`
# and then run `.\dosforge ...` from this directory (PowerShell
# autocompletes the .ps1 / .bat extension).
#
# PowerShell may block this script under the default "Restricted"
# execution policy. If you see that error use the .bat launcher
# instead, or run:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = 'Stop'
$bundle = Join-Path $PSScriptRoot 'dist\dosforge\dosforge.exe'
if (-not (Test-Path $bundle)) {
    Write-Error @"
dosforge: bundle not found at $bundle.
Build it with:
    .\.venv\Scripts\python.exe -m PyInstaller windows\dosforge.spec --noconfirm
"@
    exit 2
}
& $bundle @args
exit $LASTEXITCODE
