@echo off
setlocal
set "DOWNLOADABLE_ROOT=%~dp0"
cd /d "%DOWNLOADABLE_ROOT%"

rem This is the only Windows file a new user needs to run.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%DOWNLOADABLE_ROOT%launchers\windows' -Filter *.ps1 -File | Unblock-File"
if errorlevel 1 goto :failed
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%DOWNLOADABLE_ROOT%launchers\windows\setup.ps1"
if errorlevel 1 goto :failed
echo.
echo Downloadable is ready. Load the extension folder shown above in Chrome.
pause
exit /b 0

:failed
echo.
echo Downloadable setup did not finish. See the message above and try again.
pause
exit /b 1
