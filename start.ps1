$ErrorActionPreference = "Stop"
try {
  Set-Location $PSScriptRoot
  if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Python environment is missing. Run setup.ps1 first."
  }
  & ".venv\Scripts\python.exe" "helper\helper.py"
  if ($LASTEXITCODE -ne 0) { throw "The helper exited with code $LASTEXITCODE." }
} catch {
  Write-Host ""
  Write-Host "Downloadable could not start:" -ForegroundColor Red
  Write-Host $_.Exception.Message -ForegroundColor Yellow
}
Read-Host "Press Enter to close"
