Param(
  [string]$AppPath = "baby_kiosk.py"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Repo root (assumes this file lives in scripts\)
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$ROOT = Split-Path -Parent $SCRIPT_DIR
Set-Location $ROOT

# Find the app script if not explicitly provided
if (-not (Test-Path $AppPath)) {
  $cand = Get-ChildItem -File -Name "baby_kiosk*.py" | Select-Object -First 1
  if ($null -ne $cand) { $AppPath = $cand }
}
if (-not (Test-Path $AppPath)) {
  Write-Error "Cannot find baby_kiosk.py (or variant). Pass -AppPath path to the script."
}

# Choose Python (py launcher preferred)
$python = ""
try { $python = (& py -3 -c "import sys; print(sys.executable)") 2>$null } catch {}
if (-not $python) { try { $python = (& python -c "import sys; print(sys.executable)") } catch {} }
if (-not $python) { Write-Error "Python 3 not found. Install from python.org or Microsoft Store." }

# venv
& $python -m venv .venv
$venvPy = Join-Path $PWD ".venv\Scripts\python.exe"

# pip & deps
& $venvPy -m pip install -U pip wheel
try { & $venvPy -m pip uninstall -y opencv-python-headless } catch {}
& $venvPy -m pip install pygame numpy opencv-python imageio imageio-ffmpeg

# Assets
New-Item -ItemType Directory -Force -Path (Join-Path $PWD "assets\72x72") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $PWD "assets\background") | Out-Null

# Runner (create or overwrite)
$runPath = Join-Path $PWD "run_baby_kiosk.ps1"
$runner = @'
Param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ArgsPassthru
)
$ErrorActionPreference = 'Stop'

$Root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPy = Join-Path $Root '.venv\Scripts\python.exe'
$App    = Join-Path $Root 'APP_PLACEHOLDER'

if (-not (Test-Path $VenvPy)) { Write-Error "Virtualenv Python not found at $VenvPy. Run scripts\setup_windows.ps1 first." }
if (-not (Test-Path $App))   { Write-Error "App script not found at $App. Edit run_baby_kiosk.ps1 or re-run setup." }

& $VenvPy $App @ArgsPassthru
'@

# Replace placeholder with the given app path (keep it relative to repo root)
$runner = $runner.Replace('APP_PLACEHOLDER', $AppPath.Replace('\','\\'))
Set-Content -Path $runPath -Value $runner -Encoding UTF8

Write-Host ""
Write-Host "✅ Windows setup complete."
Write-Host "Run: powershell -ExecutionPolicy Bypass -File .\run_baby_kiosk.ps1  --no-sound"
