# Screen OCR client launcher (PowerShell)
$venvPy = "C:\Users\microsnow\.workbuddy\binaries\python\envs\ocrclient\Scripts\python.exe"
$main   = Join-Path $PSScriptRoot "main.py"

if (-not (Test-Path $venvPy)) {
    Write-Host "[ERROR] venv python not found. Please install dependencies first."
    Read-Host "Press Enter to exit"
    exit 1
}
if (-not (Test-Path $main)) {
    Write-Host "[ERROR] main.py not found (should be in same folder as this script)."
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Starting Screen OCR client..."
& $venvPy $main
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ABNORMAL EXIT] See error above."
    Read-Host "Press Enter to exit"
}
