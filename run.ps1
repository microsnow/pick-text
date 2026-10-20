# PickText launcher (PowerShell)
# Automatically locates a Python virtual environment and starts main.py.
# No hard-coded user paths: adjust the $venvPy line below if auto-detection fails.
$venvPy = $null

# 1) Try common virtual environment locations under the project root
$candidates = @(
    (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
    (Join-Path $PSScriptRoot "venv\Scripts\python.exe"),
    (Join-Path $PSScriptRoot "build_venv\Scripts\python.exe"),
    (Join-Path $PSScriptRoot "ocrclient\Scripts\python.exe")
)
foreach ($c in $candidates) {
    if (Test-Path $c) { $venvPy = $c; break }
}

# 2) Fall back to whatever python is on PATH
if (-not $venvPy) {
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath) { $venvPy = $onPath.Source }
}

$main = Join-Path $PSScriptRoot "main.py"

if (-not $venvPy) {
    Write-Host "[ERROR] No Python interpreter found."
    Write-Host "Create a virtual environment first, for example:"
    Write-Host "    python -m venv .venv"
    Write-Host "    .venv\Scripts\python.exe -m pip install -r requirements.txt"
    Read-Host "Press Enter to exit"
    exit 1
}
if (-not (Test-Path $main)) {
    Write-Host "[ERROR] main.py not found (should be in same folder as this script)."
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Using Python: $venvPy"
Write-Host "Starting PickText..."
& $venvPy $main
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ABNORMAL EXIT] See error above."
    Read-Host "Press Enter to exit"
}