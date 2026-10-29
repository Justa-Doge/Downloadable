param([switch]$KeepHelperOpen)
$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $projectRoot

Write-Host "Setting up Downloadable..."

# A repair/setup run can be started while the background helper still has the
# virtual environment's Python executable open. Stop only this app's scheduled
# task and helper process before venv tries to refresh those files.
$taskName = "Downloadable Helper"
try { Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue } catch { }
Start-Sleep -Milliseconds 700
if ($env:OS -eq "Windows_NT") {
  $helperPattern = '(?i)(?:Downloadable|personal-media-downloader).*helper[\\/]helper\.py'
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match $helperPattern -and $_.ProcessId -ne $PID } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Milliseconds 400
}

function Install-WingetPackage([string]$Id, [string]$Name) {
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw "$Name is missing, and winget is not available. Install $Name, then run Downloadable.cmd again."
  }
  $answer = Read-Host "$Name is missing. Install it with winget now? (Y/N)"
  if ($answer -notmatch '^(y|yes)$') { throw "$Name is required. Run setup again and allow the install when ready." }
  Write-Host "Installing $Name..."
  & $winget.Source install --id $Id --exact --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0) { throw "$Name could not be installed." }
}

function Add-DownloadableToolPath {
  $links = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
  if (Test-Path -LiteralPath $links) {
    $entries = $env:PATH -split ";"
    if ($entries -notcontains $links) { $env:PATH = "$links;$env:PATH" }
  }
  if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    $packages = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path -LiteralPath $packages) {
      $ffmpeg = Get-ChildItem -LiteralPath $packages -Directory -Filter "Gyan.FFmpeg*" -ErrorAction SilentlyContinue |
        ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -Recurse -File -Filter "ffmpeg.exe" -ErrorAction SilentlyContinue } |
        Select-Object -First 1
      if ($ffmpeg) { $env:PATH = "$($ffmpeg.DirectoryName);$env:PATH" }
    }
  }
}

Add-DownloadableToolPath
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  Install-WingetPackage "Gyan.FFmpeg" "FFmpeg"
  Add-DownloadableToolPath
  if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "FFmpeg was installed but could not be found yet. Restart Downloadable.cmd once." }
}

$launcher = Get-Command py -ErrorAction SilentlyContinue
if ($launcher) {
  & $launcher.Source -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
  if ($LASTEXITCODE -ne 0) {
    Install-WingetPackage "Python.Python.3.11" "Python 3.11"
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $launcher) { throw "Python was installed but could not be found yet. Restart Downloadable.cmd once." }
    & $launcher.Source -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    if ($LASTEXITCODE -ne 0) { throw "Python 3.11 or newer is required." }
  }
  & $launcher.Source -3 -m venv .venv
} else {
  $launcher = Get-Command python -ErrorAction SilentlyContinue
  if (-not $launcher) {
    Install-WingetPackage "Python.Python.3.11" "Python 3.11"
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $launcher) { $launcher = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $launcher) { throw "Python was installed but could not be found yet. Restart Downloadable.cmd once." }
  }
  & $launcher.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
  if ($LASTEXITCODE -ne 0) {
    Install-WingetPackage "Python.Python.3.11" "Python 3.11"
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $launcher) { $launcher = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $launcher) { throw "Python was installed but could not be found yet. Restart Downloadable.cmd once." }
    & $launcher.Source -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    if ($LASTEXITCODE -ne 0) { throw "Python 3.11 or newer is required." }
  }
  & $launcher.Source -m venv .venv
}
if ($LASTEXITCODE -ne 0 -or -not (Test-Path ".venv\Scripts\python.exe")) { throw "Python could not create the local environment." }
& ".venv\Scripts\python.exe" -m pip install --upgrade pip yt-dlp mutagen curl-cffi
if ($LASTEXITCODE -ne 0) { throw "Python packages could not be installed." }

if (-not (Test-Path .helper-token)) {
  $token = (& ".venv\Scripts\python.exe" -c "import secrets; print(secrets.token_urlsafe(32))").Trim()
  Set-Content -Path .helper-token -Value $token -NoNewline
} else {
  $token = (Get-Content .helper-token -Raw).Trim()
}
Set-Content -Path extension\config.js -Value "// Generated by setup.ps1.`nglobalThis.HELPER_TOKEN = `"$token`";`nglobalThis.HELPER_URL = `"http://127.0.0.1:47821`";"

$pythonwPath = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonwPath)) { throw "The background Python launcher was not created." }
$taskAction = New-ScheduledTaskAction -Execute $pythonwPath -Argument "`"$projectRoot\helper\helper.py`"" -WorkingDirectory $projectRoot
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$taskPrincipal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger -Principal $taskPrincipal -Force | Out-Null
$keep = $KeepHelperOpen
if (-not $KeepHelperOpen) {
  $keepAnswer = Read-Host "Keep the Downloadable helper running after setup? (Y/N)"
  $keep = $keepAnswer -match '^(y|yes)$'
}
if ($keep) { Start-ScheduledTask -TaskName $taskName }

Write-Host "Setup complete. Open chrome://extensions, enable Developer mode, and Load unpacked:"
Write-Host "$projectRoot\extension"
if ($keep) { Write-Host "The helper is running in the background and will start when you sign in." }
else { Write-Host "The helper is installed but paused. Start it later with launchers\windows\start.cmd or the extension's Reconnect button." }
Write-Host "Use launchers\windows\start.cmd only when you want to see diagnostic output."
