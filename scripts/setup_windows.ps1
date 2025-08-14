#requires -Version 5
param([string]$AppPath)
$ErrorActionPreference = "Stop"

# project root (scripts\..)
$scriptDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $scriptDir

# find app file
if (-not $AppPath) {
  $cand = Get-ChildItem -Name "baby_kiosk*.py" | Select-Object -First 1
  if ($cand) { $AppPath = $cand } else { throw "Cannot find baby_kiosk.py; pass -AppPath <file.py>." }
}

# find Python
$py = $null
try { $py = (Get-Command py -ErrorAction Stop).Source } catch {}
if (-not $py) { try { $py = (Get-Command python -ErrorAction Stop).Source } catch {} }
if (-not $py) {
  Write-Host "Python 3 not found. Install from https://www.python.org/downloads/windows/ or Microsoft Store." -ForegroundColor Yellow
  exit 1
}

# venv
& $py -3 -m venv .venv 2>$null | Out-Null
if (-not (Test-Path .\.venv\Scripts\Activate.ps1)) { & $py -m venv .venv }

# deps
& .\.venv\Scripts\python -m pip install -U pip wheel
& .\.venv\Scripts\python -m pip install pygame

# assets folder
New-Item -ItemType Directory -Force -Path "$scriptDir\assets\72x72" | Out-Null

# runner
$run = @'
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$scriptDir\.venv\Scripts\Activate.ps1"
$env:SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS = "0"
$env:SDL_HINT_GRAB_KEYBOARD = "1"
& "$scriptDir\.venv\Scripts\python.exe" "$scriptDir\APP_PLACEHOLDER" @Args
'@
$run = $run -replace 'APP_PLACEHOLDER', [Regex]::Escape($AppPath)
Set-Content -Path "$scriptDir\run_baby_kiosk.ps1" -Value $run -Encoding UTF8

# desktop shortcut
$ws = New-Object -ComObject WScript.Shell
$lnk = "$([Environment]::GetFolderPath('Desktop'))\Baby Kiosk.lnk"
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = "powershell.exe"
$sc.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptDir\run_baby_kiosk.ps1`""
$sc.WorkingDirectory = $scriptDir
$sc.IconLocation = "$env:SystemRoot\System32\shell32.dll,167"
$sc.Save()

Write-Host "`n✅ Windows setup complete. Use the 'Baby Kiosk' desktop shortcut." -ForegroundColor Green
