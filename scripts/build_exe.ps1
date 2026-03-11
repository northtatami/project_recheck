param(
    [switch]$InstallBuildDeps
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if ($InstallBuildDeps) {
    python -m pip install -r requirements-build.txt
}

if (Test-Path build) {
    Remove-Item -Recurse -Force build
}
if (Test-Path dist) {
    Remove-Item -Recurse -Force dist
}

python -m PyInstaller --noconfirm --clean ReCheck.spec

Write-Host "Build completed:"
Write-Host "  dist\\ReCheck\\ReCheck.exe"
