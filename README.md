# BabyKiosk
*A TinyFingers/BabySmash-style full-screen keyboard-mashing game that toddlers can’t escape.*

> **TL;DR**
> - Cross-platform: **Linux**, **macOS**, **Windows**
> - True full-screen, pointer + keyboard grabs (best on X11)
> - Big colorful letters/numbers + confetti
> - Emojis via bundled **Twemoji PNGs** in `./assets/72x72/`
> - Adult-only exit: **Hold both Shift** → **press F12** → type secret (default **`GROWNUP`**) → **Enter**

---

## Demo
<!-- Drop a GIF or short video here -->
<!-- ![demo](docs/demo.gif) -->

---

## Features
- **Kid-proof full-screen:** borderless, always-on-top, periodic re-grabs to avoid accidental minimize.
- **Escape-resistant input handling:**
  - **Linux/X11:** server-side keyboard & pointer grabs; GNOME shortcut unbinding; optional **`--nuclear`** sweep.
  - **macOS:** full-screen + Twemoji images for reliable color emoji rendering.
  - **Windows:** low-level keyboard hook to swallow **Win**, **Alt+Tab**, **Ctrl+Esc**, **PrintScreen**, etc. (OS limits apply).
- **Fun visuals:** confetti bursts; **large** letters/numbers; auto-scales to display resolution.
- **Emoji on smash:** non-alphanumeric keys show random emoji (Twemoji).

---

## Quick start

### 1) Get the code and assets
```bash
git clone https://github.com/AlexanderGatesV2/babykiosk.git
cd babykiosk

# Create the emoji assets folder (add Twemoji PNGs later)
mkdir -p assets/72x72
```

### 2) One-command setup per OS
| OS        | Command                                                                 |
|-----------|-------------------------------------------------------------------------|
| **Linux** | `bash scripts/setup_linux.sh`                                           |
| **macOS** | `bash scripts/setup_macos.sh`                                           |
| **Windows** | `powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1` |

The scripts create a virtualenv, install deps, and add a launcher:

- Linux → `./run_baby_kiosk.sh`  
- macOS → `./run_baby_kiosk.command` (double-clickable)  
- Windows → desktop shortcut **“Baby Kiosk”** (runs `run_baby_kiosk.ps1`)

> If your file isn’t named `baby_kiosk.py`, pass it as an argument:  
> `bash scripts/setup_linux.sh baby_kiosk_v11.py` (similarly for macOS/Windows scripts)

---

## Running

**Basic:**
```bash
python3 baby_kiosk.py
```

**Useful flags:**
```bash
python3 baby_kiosk.py \
  --escape-code=MYSECRET \
  --no-sound \
  --windowed \
  --allow-alt \
  --allow-super \
  --no-gnome-keyblock \
  --nuclear \
  --no-win-keyblock
```

- `--escape-code`  Set the adult exit code (default: `GROWNUP`).
- `--no-sound`     Mute click/bleep.
- `--windowed`     Debug in a window (no system grabs).
- `--allow-alt`    Don’t block Alt-based combos.
- `--allow-super`  Don’t block Super/Win.
- `--no-gnome-keyblock`  Skip GNOME shortcut unbinding (Linux).
- `--nuclear`      **Linux/GNOME/X11:** temporarily blank most GNOME keybindings while running, restore on exit.
- `--no-win-keyblock`   Skip the Windows keyboard hook.

### Adult-only exit sequence
Hold **Left Shift** + **Right Shift**, press **F12**, type your secret (default `GROWNUP`), press **Enter**.

---

## Assets (Emoji)

Place Twemoji PNGs under **`./assets/72x72/`** (relative to the Python file):

```
babykiosk/
  baby_kiosk.py
  assets/
    72x72/
      1f389.png   # 🎉
      2728.png    # ✨
      ...
```

If the folder is missing/empty, the app falls back to system fonts (color emoji support may vary, especially on macOS with SDL_ttf).

---

## Platform notes

### Linux
- **Best on X11.** Uses:
  - X server **keyboard & pointer grabs**
  - X-level grabs on **Alt (Mod1)** and **Super (Mod4)**
  - GNOME: temporarily unbinds **Alt+Tab**, **Alt+`**, **Alt+Space**, **Super overlay**, **Win+1..9**
  - `--nuclear` option sweeps common schemas and blanks most shortcuts while running **(RECOMMENDED)**
- **Wayland:** the compositor owns global shortcuts; apps can’t fully block them. For kiosk-like behavior, run inside a kiosk compositor:
  ```bash
  cage -s -- python3 baby_kiosk.py
  ```
- **Known un-blockable:** VT switch (e.g., `Ctrl+Alt+F3`) unless you harden the session/TTY.

### macOS
- Full-screen works. SDL_ttf may not render Apple Color Emoji; Twemoji images provide consistent full-color emoji.

### Windows 10/11
- Installs a low-level keyboard hook on a dedicated message-loop thread. Swallows:
  - **Win key** (and anything while Win is held)
  - **Alt+Tab**, **Alt+Esc**, **Alt+F4** 
  - **Ctrl+Esc** (Start) (I ihad to disable it manually)
  - **PrintScreen** (also disables Win11 “PrintScreen opens Snipping Tool” mapping during the session) **(Disable in Settings if it doesn't work)**
- **Known un-blockables:** `Ctrl+Alt+Del`, `Win+L`, UAC secure desktop prompts.

---

## Autostart (optional)
- **GNOME:** the Linux setup can write `~/.config/autostart/baby-kiosk.desktop` (uses `--nuclear`).
- **macOS:** the macOS setup can create a LaunchAgent (`~/Library/LaunchAgents/com.babykiosk.plist`).
- **Windows:** the setup creates a desktop shortcut; add `run_baby_kiosk.ps1` to Task Scheduler (At logon) for auto-start.

---

## Troubleshooting
- **macOS emojis blank/monochrome:** ensure Twemoji PNGs exist under `assets/72x72/`.  
- **Win11 Snipping Tool still opens:** launch via the provided runner/shortcut so the app can toggle the PrintScreen mapping and install the hook.  
- **Alt/Super combos leak on Linux:** confirm you’re on **X11** (not Wayland). On GNOME, try `--nuclear`.  
- **Can’t exit:** verify the sequence (both Shift → F12 → type secret → Enter). For testing, try `--windowed`.

---

## Development
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install pygame python-xlib
python3 baby_kiosk.py --windowed
```

PRs welcome for:
- KDE/Plasma & non-GNOME keybinding sweeps
- Wayland kiosk helpers (Sway/Cage configs)
- macOS CoreText emoji path (optional true-color rendering)

---

## Security & limits
Desktop OSs reserve secure shortcuts by design. This app follows best-effort kiosk strategies but **cannot** block everything (e.g., `Ctrl+Alt+Del`, `Win+L`). For bullet-proof setups, combine with OS policies (Assigned Access, MDM, kiosk sessions).
