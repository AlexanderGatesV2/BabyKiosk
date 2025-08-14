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

# Install minimal deps on Debian/Ubuntu if available
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y python3-venv python3-pip fonts-noto-color-emoji
fi

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip wheel
python -m pip install pygame python-xlib

# Ensure assets folder exists (we hardcode ./assets/72x72 in the app)
mkdir -p assets/72x72

# Create a simple launcher
cat > run_baby_kiosk.sh <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate"
exec python "$SCRIPT_DIR/APP_PLACEHOLDER" "$@"
EOS
sed -i.bak "s|APP_PLACEHOLDER|$APP|g" run_baby_kiosk.sh && rm -f run_baby_kiosk.sh.bak
chmod +x run_baby_kiosk.sh

echo
echo "✅ Linux setup complete."
echo "Run: ./run_baby_kiosk.sh"
read -r -p "Create GNOME autostart entry (uses --nuclear)? [y/N] " yn || true
if [[ "${yn:-N}" =~ ^[Yy]$ ]]; then
  mkdir -p "$HOME/.config/autostart"
  cat >"$HOME/.config/autostart/baby-kiosk.desktop" <<EOD
[Desktop Entry]
Type=Application
Name=Baby Kiosk
Exec=$SCRIPT_DIR/run_baby_kiosk.sh --nuclear
X-GNOME-Autostart-enabled=true
OnlyShowIn=GNOME;
EOD
  echo "Autostart entry created at ~/.config/autostart/baby-kiosk.desktop"
fi
