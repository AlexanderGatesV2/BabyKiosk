#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd .. && pwd)"
cd "$SCRIPT_DIR"

APP="${1:-baby_kiosk.py}"
if [[ ! -f "$APP" ]]; then
  APP="$(ls -1 baby_kiosk*.py 2>/dev/null | head -n1 || true)"
fi
if [[ -z "${APP:-}" || ! -f "$APP" ]]; then
  echo "Cannot find baby_kiosk.py. Pass it as the first arg." >&2; exit 1
fi

# Homebrew (optional but recommended)
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew not found. Installing..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv)" || true
fi
brew install python@3 || true
brew install --cask font-noto-color-emoji || true

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip wheel
python -m pip install pygame python-xlib numpy opencv-python imageio

# Ensure assets folder exists
mkdir -p assets/72x72

# Double-clickable launcher
cat > run_baby_kiosk.command <<'EOS'
#!/usr/bin/env bash
cd "$(dirname "$0")"
source .venv/bin/activate
exec python APP_PLACEHOLDER "$@"
EOS
# macOS sed requires an arg for -i
sed -i '' "s|APP_PLACEHOLDER|$APP|g" run_baby_kiosk.command
chmod +x run_baby_kiosk.command

echo
echo "✅ macOS setup complete."
echo "Double-click: ./run_baby_kiosk.command"
read -r -p "Create LaunchAgent to auto-start at login? [y/N] " yn || true
if [[ "${yn:-N}" =~ ^[Yy]$ ]]; then
  PLIST="$HOME/Library/LaunchAgents/com.babykiosk.plist"
  cat > "$PLIST" <<EOP
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.babykiosk</string>
  <key>ProgramArguments</key>
  <array><string>$SCRIPT_DIR/run_baby_kiosk.command</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
</dict></plist>
EOP
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  echo "LaunchAgent installed at $PLIST"
fi
