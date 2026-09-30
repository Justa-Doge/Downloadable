$ErrorActionPreference = "Stop"
try {
  Set-Location $PSScriptRoot
  $links = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
  if (Test-Path -LiteralPath $links) {
    $entries = $env:PATH -split ";"
    if ($entries -notcontains $links) { $env:PATH = "$links;$env:PATH" }
  }
  if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Python environment is missing. Run setup.cmd first."
  }
  & ".venv\Scripts\python.exe" "helper\helper.py"
  if ($LASTEXITCODE -ne 0) { throw "The helper exited with code $LASTEXITCODE." }
} catch {
  Write-Host ""
  Write-Host "Downloadable could not start:" -ForegroundColor Red
  Write-Host $_.Exception.Message -ForegroundColor Yellow
}
Read-Host "Press Enter to close"
