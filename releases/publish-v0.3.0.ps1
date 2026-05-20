# publish-v0.3.0.ps1 — finalize the v0.3.0 release on GitHub.
#
# Prerequisite: `gh auth login` (or set $env:GH_TOKEN to a PAT with
# repo scope). Tag v0.3.0 has already been pushed to origin and the
# release artifact has been built locally; this script just creates
# the GitHub release page and uploads the asset.

$ErrorActionPreference = 'Stop'
$tag      = 'v0.3.0'
$title    = 'dosforge 0.3.0 — Windows port complete'
$artifact = Join-Path $PSScriptRoot 'dosforge-0.3.0-windows-x64.zip'
$notes    = Join-Path $PSScriptRoot 'v0.3.0-release-notes.md'

foreach ($f in $artifact, $notes) {
    if (-not (Test-Path $f)) {
        Write-Error "Missing required file: $f"
        exit 1
    }
}

Write-Host "Tag:      $tag"
Write-Host "Title:    $title"
Write-Host "Artifact: $artifact ($((Get-Item $artifact).Length / 1MB) MB)"
Write-Host "Notes:    $notes"
Write-Host ""
Write-Host "Creating release..."

gh release create $tag $artifact `
    --title $title `
    --notes-file $notes

Write-Host ""
Write-Host "Done. View at:" -ForegroundColor Green
gh release view $tag --web
