@echo off
setlocal
set "DOWNLOADABLE_ROOT=%~dp0"
cd /d "%DOWNLOADABLE_ROOT%"

powershell.exe -NoProfile -Command "Get-ChildItem -LiteralPath $env:DOWNLOADABLE_ROOT -Filter *.ps1 -File | Unblock-File"
if errorlevel 1 (
  echo Downloadable could not prepare its local launcher.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%DOWNLOADABLE_ROOT%start.ps1"
