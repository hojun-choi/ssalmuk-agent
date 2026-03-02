param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    py -m venv .venv
}

Write-Host "Activate with: .\\.venv\\Scripts\\Activate.ps1"

& .\.venv\Scripts\python.exe -m pip install -U pip
if (-not $SkipInstall) {
    & .\.venv\Scripts\pip.exe install -e .
}

Write-Host "Bootstrap complete."
