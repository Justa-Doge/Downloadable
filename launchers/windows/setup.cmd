@echo off
setlocal
set "DOWNLOADABLE_ROOT=%~dp0..\..\"
cd /d "%DOWNLOADABLE_ROOT%"

rem Remove only the downloaded-file marker from this project's PowerShell scripts.
powershell.exe -NoProfile -Command "Get-ChildItem -LiteralPath '%DOWNLOADABLE_ROOT%launchers\windows' -Filter *.ps1 -File | Unblock-File"
if errorlevel 1 (
  echo.
  echo Downloadable could not prepare its local setup scripts.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%DOWNLOADABLE_ROOT%launchers\windows\setup.ps1"
if errorlevel 1 (
  echo.
  echo Downloadable setup did not finish.
  pause
  exit /b 1
)

exit /b 0
