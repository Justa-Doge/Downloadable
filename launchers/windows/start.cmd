@echo off
setlocal
set "DOWNLOADABLE_ROOT=%~dp0..\..\"
cd /d "%DOWNLOADABLE_ROOT%"

powershell.exe -NoProfile -Command "Get-ChildItem -LiteralPath '%DOWNLOADABLE_ROOT%launchers\windows' -Filter *.ps1 -File | Unblock-File"
if errorlevel 1 (
  echo Downloadable could not prepare its local launcher.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%DOWNLOADABLE_ROOT%launchers\windows\start.ps1"
if errorlevel 1 (
  echo.
  echo Downloadable helper stopped with an error.
  pause
)
