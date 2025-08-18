#!/usr/bin/env python3
"""
BabyKiosk — a TinyFingers/BabySmash-style full‑screen keyboard-mashing game for Linux.

Primary goals
-------------
- Run borderless, true full-screen.
- Soak up *all* keyboard/mouse input so a baby can't escape (X11 best‑effort).
- Provide an adult-only escape sequence: hold BOTH Shift keys, press F12, then
  type a secret code (default: GROWNUP) and press Enter.

Important platform notes
------------------------
- Strong lock is supported on **X11** using X keyboard/pointer grabs
  (Alt+Tab, Super, etc., are captured by this window).
- On **Wayland**, global grabs are intentionally restricted by design; this app
  will still run, but the compositor may handle system shortcuts. For a
  near-kiosk experience on Wayland, run inside a kiosk compositor such as
  `cage` (e.g., `cage -s -- python3 baby_kiosk.py`).
- No application can block VT switching (e.g., Ctrl+Alt+F3) universally without
  deeper OS/session configuration. For the strongest kiosk, run this in a
  dedicated Xorg session or kiosk environment.

Dependencies
------------
    pip3 install pygame python-xlib imageio
# Emoji images (cross-platform): place Twemoji PNGs in ./assets/72x72 next to this script

Run
---
    python3 baby_kiosk.py

Options
-------
    python3 baby_kiosk.py --escape-code=MYSECRET --no-sound --windowed

"""

from __future__ import annotations
import pygame
import os, time, math, random
import argparse
import atexit
import math
import os
import random
import sys
import time
from dataclasses import dataclass
import cv2
import numpy as np
import imageio.v2 as imageio  # fallback decoder
import imageio_ffmpeg

# --------------------------- Emoji support --------------------------- #
# A cheerful set of emojis to use when a non‑alphanumeric key is pressed.
EMOJIS = [
    '😀','😄','😁','😆','😍','😎','🤩','🥳','🎉','✨','⭐','🌈','🍭','🍓','🍌','🍕',
    '🐶','🐱','🐭','🐹','🐰','🐻','🦊','🐸','🐵','🦄','🐥','🐙','🐳','🌟','💥','💫','💖','🧸',
    '🚗','🚀','🚁','🚂','⚽','🏀','🏈','🎈','🎵','🎶','🎲','🧩','🪀','🪁','🛝','🍼','🧃','🍪'
]

# Try to locate a color emoji font on Linux systems.
# This improves the chances that emojis render as color glyphs rather than tofu.
# Users may install: sudo apt install fonts-noto-color-emoji (Debian/Ubuntu)
# or the equivalent for their distro.
def find_emoji_font() -> str | None:
    # Look for color-emoji fonts on Linux, macOS, and Windows
    candidates = []
    plat = sys.platform
    home = os.path.expanduser('~')
    if plat.startswith('linux'):
        candidates += [
            '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf',
            '/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf',
            '/usr/share/fonts/emoji/NotoColorEmoji.ttf',
            '/usr/share/fonts/joypixels/JoyPixels.ttf',
        ]
    if plat == 'darwin':
        candidates += [
            '/System/Library/Fonts/Apple Color Emoji.ttc',
            '/Library/Fonts/NotoColorEmoji.ttf',
            f'{home}/Library/Fonts/NotoColorEmoji.ttf',
        ]
    if plat.startswith('win'):
        system_root = os.environ.get('SystemRoot', r'C:\Windows')
        candidates += [
            os.path.join(system_root, 'Fonts', 'seguiemoji.ttf'),   # Segoe UI Emoji (newer)
            os.path.join(system_root, 'Fonts', 'seguiemj.ttf'),     # Segoe UI Emoji (older)
            os.path.join(system_root, 'Fonts', 'seguisym.ttf'),     # Segoe UI Symbol (fallback)
        ]
    # Last-ditch
    candidates.append('/usr/share/fonts/truetype/seguiemj.ttf')
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

# Optional X11 grab support
_X11_OK = False
try:
    from Xlib import X, display
    _X11_OK = True
except Exception:
    _X11_OK = False

# --------------------------- Visual helpers --------------------------- #

# --- helpers ---------------------------------------------------------------
def _resolve_bg_path(args, script_dir):
    """Return a valid background video path or None. Never returns a bool.
    If --bg is provided and exists, use it. Otherwise scan assets/background/
    for the first supported file."""
    if getattr(args, 'no_bg', False):
        return None

    # explicit path beats discovery
    p = getattr(args, 'bg', None)
    if isinstance(p, (str, bytes, os.PathLike)):
        p_str = os.fspath(p)
        if p_str.strip() and os.path.exists(p_str):
            return p_str

    # auto-discovery
    bg_dir = os.path.join(script_dir, 'assets', 'background')
    if os.path.isdir(bg_dir):
        exts = ('.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm', '.gif')
        candidates = []
        try:
            for name in sorted(os.listdir(bg_dir)):
                full = os.path.join(bg_dir, name)
                if os.path.isfile(full) and name.lower().endswith(exts):
                    candidates.append(full)
        except Exception:
            pass
        if candidates:
            return candidates[0]

    return None


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    r: float
    life: float
    color: tuple[int, int, int]

    def update(self, dt: float) -> None:
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += 50.0 * dt  # gentle gravity
        self.life -= dt
        # shrink a bit over time (keep float type consistent)
        self.r = max(0.0, self.r - 10.0 * dt)

    def draw(self, surf: "pygame.Surface") -> None:
        if self.life <= 0.0 or self.r <= 0.0:
            return
        pygame.draw.circle(surf, self.color, (int(self.x), int(self.y)), int(self.r))

@dataclass
class FloatingGlyph:
    text: str
    x: float
    y: float
    vx: float
    vy: float
    life: float
    color: tuple
    font: pygame.font.Font
    fallback_font: pygame.font.Font | None = None
    image: pygame.Surface | None = None  # optional pre-rendered image (e.g., Twemoji)

    def update(self, dt: float):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy -= 10 * dt
        self.life -= dt

    def draw(self, surf: pygame.Surface):
        if self.life <= 0:
            return
        # Prefer pre-rendered image if provided
        if self.image is not None:
            surf.blit(self.image, (int(self.x), int(self.y)))
            return
        s = None
        # Try primary font
        try:
            s_try = self.font.render(self.text, True, self.color)
            if s_try.get_width() > 0 and s_try.get_height() > 0:
                s = s_try
        except Exception:
            s = None
        # Try fallback font with original text
        if s is None and self.fallback_font is not None:
            try:
                s_try = self.fallback_font.render(self.text, True, self.color)
                if s_try.get_width() > 0 and s_try.get_height() > 0:
                    s = s_try
            except Exception:
                s = None
        # Last resort: draw a star with fallback font or primary
        if s is None:
            try:
                ff = self.fallback_font or self.font
                s_try = ff.render('*', True, self.color)
                if s_try.get_width() > 0 and s_try.get_height() > 0:
                    s = s_try
            except Exception:
                return
        surf.blit(s, (int(self.x), int(self.y)))

class BackgroundBase:
    def __init__(self): self.status = ""
    def resize(self, wh): pass
    def update(self, dt): pass
    def draw(self, surf): pass

class BackgroundVideo(BackgroundBase):
    """OpenCV first; falls back to imageio if cv2 can't open the file."""
    def __init__(self, path, wh):
        super().__init__()
        self.path = path
        self.w, self.h = wh
        self.fps = 30.0
        self.last = 0.0
        self.frame = None
        self.ok = False
        self.cap = None
        self.reader = None
        self._use_imageio = False

        if cv2 is not None:
            cap = cv2.VideoCapture(path)
            if not isinstance(path, (str, bytes, os.PathLike)):
                self.ok = False
                self.status = f'bg:invalid path type {type(path).__name__}'
                return
            if cap is not None and cap.isOpened():
                self.cap = cap
                fps = self.cap.get(cv2.CAP_PROP_FPS)
                if fps and fps > 1:
                    self.fps = float(fps)
                self.ok = True
                self.status = f"bg:opencv@{self.fps:.1f}fps"
        if not self.ok and imageio is not None:
            try:
                self.reader = imageio.get_reader(path)
                meta = self.reader.get_meta_data()
                fps = meta.get("fps", 30.0)
                self.fps = float(fps) if fps and fps > 1 else 30.0
                self._use_imageio = True
                self.ok = True
                self.status = f"bg:imageio@{self.fps:.1f}fps"
            except Exception as e:
                self.status = f"bg:fail ({e})"
                self.ok = False

    def resize(self, wh):
        self.w, self.h = wh
        self.last = 0.0  # force refresh

    def _next_cv2(self):
        ret, bgr = self.cap.read()
        if not ret:
            # loop
            try:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, bgr = self.cap.read()
            except Exception:
                return None
        if not ret:
            return None
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if (rgb.shape[1], rgb.shape[0]) != (self.w, self.h):
            rgb = cv2.resize(rgb, (self.w, self.h), interpolation=cv2.INTER_LINEAR)
        arr = np.ascontiguousarray(rgb)
        surf = pygame.image.frombuffer(rgb.tobytes(), (self.w, self.h), "RGB")
        return surf.convert()

    def _next_imageio(self):
        """Read next frame via imageio, normalize to RGB np.uint8, scale to (w,h),
        and return a pygame.Surface. Returns None on failure."""
        try:
            frame = self.reader.get_next_data()
        except Exception:
            # loop/reopen
            try:
                self.reader.close()
                self.reader = imageio.get_reader(self.path)
                frame = self.reader.get_next_data()
            except Exception:
                return None

        if frame is None:
            return None

        # Some plugins may yield dicts (rare); try common keys
        if isinstance(frame, dict):
            if 'image' in frame:
                frame = frame['image']
            elif 'data' in frame:
                frame = frame['data']
            else:
                return None

        # Ensure numpy array
        if not isinstance(frame, np.ndarray):
            try:
                frame = np.asarray(frame)
            except Exception:
                return None

        # Normalize to RGB HxWx3
        if frame.ndim == 2:  # grayscale
            frame = np.stack([frame] * 3, axis=-1)
        elif frame.ndim == 3 and frame.shape[2] == 4:  # RGBA -> RGB
            frame = frame[:, :, :3]
        elif frame.ndim != 3 or frame.shape[2] != 3:
            return None

        # Type to uint8
        if frame.dtype != np.uint8:
            frame = np.clip(frame, 0, 255).astype(np.uint8)

        # Resize to window
        if (frame.shape[1], frame.shape[0]) != (self.w, self.h):
            if cv2 is not None:
                frame = cv2.resize(frame, (self.w, self.h), interpolation=cv2.INTER_LINEAR)
            else:
                # Fallback resize without OpenCV
                surf = pygame.image.frombuffer(frame.tobytes(), (frame.shape[1], frame.shape[0]), "RGB").convert()
                return pygame.transform.smoothscale(surf, (self.w, self.h))

        # Create surface from bytes (width, height)
        w, h = frame.shape[1], frame.shape[0]
        surf = pygame.image.frombuffer(frame.tobytes(), (w, h), "RGB")
        return surf.convert()

    def update(self, dt):
        if not self.ok:
            return
        now = time.time()
        if self.frame is None or (now - self.last) >= 1.0 / max(10.0, self.fps):
            fr = self._next_imageio() if self._use_imageio else self._next_cv2()
            if fr is not None:
                self.frame = fr
                self.last = now
            else:
                self.ok = False
                self.status = "bg:stopped"

    def draw(self, surf):
        if self.frame is not None:
            surf.blit(self.frame, (0, 0))

class BackgroundWaves(BackgroundBase):
    """Lightweight animated gradient fallback."""
    def __init__(self, wh):
        super().__init__()
        self.w, self.h = wh
        self.t = 0.0
        self.canvas = pygame.Surface(wh).convert()
        self.status = "bg:waves"
    def resize(self, wh):
        self.w, self.h = wh
        self.canvas = pygame.Surface(wh).convert()
    def update(self, dt):
        self.t += dt
        for y in range(0, self.h, 8):
            c = int((math.sin(self.t*0.6 + y*0.02) * 0.5 + 0.5) * 60) + 30
            pygame.draw.rect(self.canvas, (10, 10, 20 + c), (0, y, self.w, 8))
    def draw(self, surf):
        surf.blit(self.canvas, (0, 0))

# --------------------------- X11 locker --------------------------- #
class X11Locker:
    """Grabs keyboard and pointer under X11 for strong kiosk behavior."""
    def __init__(self, win_id: int):
        self._disp = display.Display()
        self._root = self._disp.screen().root
        self._win = self._disp.create_resource_object('window', win_id)
        self._grabbed = False
        self._alt_masks: list[int] = []
        self._super_masks: list[int] = []

    def lock(self):
        try:
            # Make sure window is override-redirect and raised
            self._win.change_attributes(override_redirect=True)
            self._win.map()
            self._win.set_input_focus(X.RevertToParent, X.CurrentTime)

            emask = (
                X.ButtonPressMask | X.ButtonReleaseMask |
                X.PointerMotionMask | X.FocusChangeMask | X.EnterWindowMask |
                X.LeaveWindowMask
            )
            # Grab pointer + keyboard
            self._win.grab_pointer(False, emask, X.GrabModeAsync, X.GrabModeAsync,
                                   X.NONE, X.NONE, X.CurrentTime)
            self._win.grab_keyboard(False, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime)

            # Also try to stack above
            try:
                self._win.configure(stack_mode=X.Above)
            except Exception:
                pass

            self._disp.sync()
            self._grabbed = True
        except Exception:
            self._grabbed = False

    def block_alt(self):
        """On X11, aggressively grab *any* key when Alt (Mod1) is held, to defeat Alt+Tab/Alt+`.
        We grab against common lock-modifier combos (Caps/Num/Mod5) and remember them to ungrab later.
        """
        try:
            masks = [
                0,
                X.LockMask,
                X.Mod2Mask,        # usually NumLock
                X.Mod5Mask,        # often ISO_Level3/AltGr/ScrollLock depending on layout
                X.LockMask | X.Mod2Mask,
                X.LockMask | X.Mod5Mask,
                X.Mod2Mask | X.Mod5Mask,
                X.LockMask | X.Mod2Mask | X.Mod5Mask,
            ]
            self._alt_masks = masks
            for m in masks:
                # Any key while Alt (Mod1) is held
                self._root.grab_key(X.AnyKey, X.Mod1Mask | m, True, X.GrabModeAsync, X.GrabModeAsync)
            self._disp.sync()
        except Exception:
            pass

    def unblock_alt(self):
        try:
            for m in getattr(self, "_alt_masks", []):
                try:
                    self._root.ungrab_key(X.AnyKey, X.Mod1Mask | m)
                except Exception:
                    pass
            self._disp.sync()
        except Exception:
            pass
    def block_super(self):
        """Grab any key while Super (Mod4) is held — blocks Win+Number, Win+Tab in many WMs."""
        try:
            masks = [
                0,
                X.LockMask,
                X.Mod2Mask,
                X.Mod5Mask,
                X.LockMask | X.Mod2Mask,
                X.LockMask | X.Mod5Mask,
                X.Mod2Mask | X.Mod5Mask,
                X.LockMask | X.Mod2Mask | X.Mod5Mask,
            ]
            self._super_masks = masks
            for m in masks:
                self._root.grab_key(X.AnyKey, X.Mod4Mask | m, True, X.GrabModeAsync, X.GrabModeAsync)
            self._disp.sync()
        except Exception:
            pass

    def unblock_super(self):
        try:
            for m in getattr(self, "_super_masks", []):
                try:
                    self._root.ungrab_key(X.AnyKey, X.Mod4Mask | m)
                except Exception:
                    pass
            self._disp.sync()
        except Exception:
            pass

    def unlock(self):
        try:
            self._disp.ungrab_pointer(X.CurrentTime)
        except Exception:
            pass
        try:
            self._disp.ungrab_keyboard(X.CurrentTime)
        except Exception:
            pass
        try:
            self._disp.sync()
        except Exception:
            pass
        try:
            self.unblock_alt()
        except Exception:
            pass
        try:
            self.unblock_super()
        except Exception:
            pass
        self._grabbed = False

    def heartbeat(self):
        # Keep input focus and grabs alive.
        try:
            self._win.set_input_focus(X.RevertToParent, X.CurrentTime)
        except Exception:
            pass
        if not self._grabbed:
            self.lock()

# --------------------------- GNOME keybinding blocker (X11) --------------------------- #
# On GNOME (X11), the window manager binds Alt+Tab / Alt+` at the compositor level.
# We temporarily unbind those keybindings via gsettings and restore them on exit.
import subprocess
class GNOMEKeyBlocker:
    KEYS = [
        ("org.gnome.desktop.wm.keybindings", "switch-applications"),
        ("org.gnome.desktop.wm.keybindings", "switch-applications-backward"),
        ("org.gnome.desktop.wm.keybindings", "switch-windows"),
        ("org.gnome.desktop.wm.keybindings", "switch-windows-backward"),
        ("org.gnome.desktop.wm.keybindings", "switch-group"),
        ("org.gnome.desktop.wm.keybindings", "switch-group-backward"),
        ("org.gnome.desktop.wm.keybindings", "cycle-windows"),
        ("org.gnome.desktop.wm.keybindings", "cycle-windows-backward"),
        ("org.gnome.desktop.wm.keybindings", "cycle-group"),
        ("org.gnome.desktop.wm.keybindings", "cycle-group-backward"),
        ("org.gnome.desktop.wm.keybindings", "activate-window-menu"),  # Alt+Space
    ]
    # Super overlay (not Alt, but helps kiosk)
    EXTRA = [("org.gnome.mutter", "overlay-key")]

    def __init__(self, nuclear: bool = False):
        self._saved = {}
        self.nuclear = nuclear

    def _run(self, args):
        return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)

    def enable(self):
        # Save current bindings (add GNOME dock Win+number actions 1..9)
        shell_app_keys = [("org.gnome.shell.keybindings", f"switch-to-application-{i}") for i in range(1, 10)]
        # Dash-to-dock / Ubuntu Dock related keys
        dtd_schema = "org.gnome.shell.extensions.dash-to-dock"
        dtd_hotkeys = [(dtd_schema, "hot-keys"), (dtd_schema, "hotkeys-show-dock")] + \
                      [(dtd_schema, f"app-hotkey-{i}") for i in range(1, 11)] + \
                      [(dtd_schema, f"app-ctrl-hotkey-{i}") for i in range(1, 11)] + \
                      [(dtd_schema, f"app-shift-hotkey-{i}") for i in range(1, 11)]

        for schema, key in self.KEYS + self.EXTRA + shell_app_keys + dtd_hotkeys:
            r = self._run(["gsettings", "get", schema, key])
            if r.returncode == 0:
                self._saved[(schema, key)] = r.stdout.strip()

        # Disable Alt switchers, Super overlay, Super+number app hotkeys (both Shell and Dock)
        for schema, key in self.KEYS + shell_app_keys:
            self._run(["gsettings", "set", schema, key, "[]"])  # unbind
        for schema, key in self.EXTRA:
            self._run(["gsettings", "set", schema, key, "''"])   # empty overlay
        # Dash-to-dock: disable master toggle and any explicit app-hotkeys
        self._run(["gsettings", "set", dtd_schema, "hot-keys", "false"])  # turn off Win+1..9
        self._run(["gsettings", "set", dtd_schema, "hotkeys-show-dock", "false"])  # hide hints
        for i in range(1, 11):
            for key in (f"app-hotkey-{i}", f"app-ctrl-hotkey-{i}", f"app-shift-hotkey-{i}"):
                self._run(["gsettings", "set", dtd_schema, key, "[]"])  # clear any overrides

        # Nuclear option: sweep through common keybinding schemas and blank everything
        if self.nuclear:
            schemas = [
                "org.gnome.desktop.wm.keybindings",
                "org.gnome.shell.keybindings",
                "org.gnome.settings-daemon.plugins.media-keys",
                "org.gnome.mutter",
                "org.gnome.shell.extensions.ubuntu-dock",
                "org.gnome.shell.extensions.dash-to-dock",
            ]
            for schema in schemas:
                lr = self._run(["gsettings", "list-keys", schema])
                if lr.returncode != 0:
                    continue
                for key in lr.stdout.strip().splitlines():
                    gr = self._run(["gsettings", "get", schema, key])
                    if gr.returncode != 0:
                        continue
                    val = gr.stdout.strip()
                    if (schema, key) not in self._saved:
                        self._saved[(schema, key)] = val
                    if val.startswith('['):
                        self._run(["gsettings", "set", schema, key, "[]"])  # unbind arrays
                    elif key == "overlay-key":
                        self._run(["gsettings", "set", schema, key, "''"])  # clear Super overlay
                    elif ("hot-keys" in key or "hotkeys" in key or "enable-hotkeys" in key) and val in ("true", "false"):
                        self._run(["gsettings", "set", schema, key, "false"])  # disable boolean toggles

    def disable(self):
        # Restore previous values
        for (schema, key), val in self._saved.items():
            self._run(["gsettings", "set", schema, key, val])

        # Restore previous values
        for (schema, key), val in self._saved.items():
            self._run(["gsettings", "set", schema, key, val])

# --------------------------- Windows key blocker (best-effort) --------------------------- #
# On Windows, some global shortcuts (Ctrl+Alt+Del, Win+L) cannot be blocked by apps.
# We install a low-level keyboard hook to swallow Win keys and common switchers
# (Alt+Tab, Alt+Esc, Alt+F4, Win+D, Win+1..9) while the game is active.
if sys.platform.startswith('win'):
    import ctypes
    from ctypes import wintypes
    import threading
    import winreg
    import threading
    import winreg

    class WinKeyBlocker:
        WH_KEYBOARD_LL = 13
        WM_KEYDOWN = 0x0100
        WM_SYSKEYDOWN = 0x0104
        VK_TAB = 0x09
        VK_ESCAPE = 0x1B
        VK_F4 = 0x73
        VK_LWIN = 0x5B
        VK_RWIN = 0x5C
        VK_D = 0x44
        # 0..9
        VK_0 = 0x30
        VK_1 = 0x31
        VK_9 = 0x39
        VK_MENU = 0x12  # Alt
        VK_CONTROL = 0x11
        VK_SNAPSHOT = 0x2C  # PrintScreen
        VK_SPACE = 0x20
        WM_KEYUP = 0x0101
        WM_SYSKEYUP = 0x0105

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", wintypes.ULONG)]

        def __init__(self):
            self.user32 = ctypes.windll.user32
            self.kernel32 = ctypes.windll.kernel32
            self.hook = None
            self._CMPFUNC = ctypes.WINFUNCTYPE(wintypes.LRESULT, wintypes.INT, wintypes.WPARAM, wintypes.LPARAM)
            self._proc = self._CMPFUNC(self._low_level_proc)
            # hook thread state
            self.thread = None
            self.thread_id = 0
            self.stop_event = threading.Event()
            self.prev_snip_toggle = None
            # hook thread state
            self.thread = None
            self.thread_id = 0
            self.stop_event = threading.Event()
            self.prev_snip_toggle = None

        def _alt_down(self):
            return (self.user32.GetAsyncKeyState(self.VK_MENU) & 0x8000) != 0

        def _win_down(self):
            return (self.user32.GetAsyncKeyState(self.VK_LWIN) & 0x8000) != 0 or \
                   (self.user32.GetAsyncKeyState(self.VK_RWIN) & 0x8000) != 0

        def _low_level_proc(self, nCode, wParam, lParam):
            if nCode == 0 and wParam in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN, self.WM_KEYUP, self.WM_SYSKEYUP):
                kb = ctypes.cast(lParam, ctypes.POINTER(self.KBDLLHOOKSTRUCT)).contents
                vk = kb.vkCode
                # Block PrintScreen / SnippingTool trigger
                if vk == self.VK_SNAPSHOT:
                    return 1
                # Block Ctrl+Esc (Start menu)
                if (self.user32.GetAsyncKeyState(self.VK_CONTROL) & 0x8000) != 0 and vk == self.VK_ESCAPE:
                    return 1
                # Block Win keys outright
                if vk in (self.VK_LWIN, self.VK_RWIN):
                    return 1
                # Block Win+D and Win+1..9
                if self._win_down():
                    return 1
                # Block Alt+Tab / Alt+Esc / Alt+F4
                if self._alt_down() and vk in (self.VK_TAB, self.VK_ESCAPE, self.VK_F4):
                    return 1
            return self.user32.CallNextHookEx(self.hook, nCode, wParam, lParam)

        def _message_loop(self):
            # Minimal message loop required for LL hooks
            msg = wintypes.MSG()
            while not self.stop_event.is_set():
                res = self.user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if res == -1:  # error
                    break
                self.user32.TranslateMessage(ctypes.byref(msg))
                self.user32.DispatchMessageW(ctypes.byref(msg))

        def install(self):
            if self.hook or (self.thread and self.thread.is_alive()):
                return
        
            # Turn off Win11 "PrintScreen opens Snipping Tool" toggle for this session
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
                    0, winreg.KEY_READ
                )
                self.prev_snip_toggle, _ = winreg.QueryValueEx(key, "PrintScreenKeyForSnippingEnabled")
                winreg.CloseKey(key)
            except Exception:
                self.prev_snip_toggle = None
        
            try:
                key = winreg.CreateKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
                )
                winreg.SetValueEx(key, "PrintScreenKeyForSnippingEnabled", 0, winreg.REG_DWORD, 0)
                winreg.CloseKey(key)
            except Exception:
                pass
        
            self.stop_event.clear()

# --------------------------- Escape detector --------------------------- #
class EscapeGate:
    """Complex escape: hold both Shift keys, press F12, then type secret and Enter."""
    def __init__(self, secret: str, prime_timeout: float = 8.0):
        self.secret = secret.upper()
        self.prime_timeout = prime_timeout
        self.primed = False
        self.started_at = 0.0
        self.buffer = ''

    def try_prime(self, mods: int, key: int):
        both_shifts = (mods & pygame.KMOD_LSHIFT) and (mods & pygame.KMOD_RSHIFT)
        if both_shifts and key == pygame.K_F12:
            self.primed = True
            self.started_at = time.time()
            self.buffer = ''
            return True
        return False

    def feed(self, ev: pygame.event.Event):
        if not self.primed:
            return False
        # timeout
        if time.time() - self.started_at > self.prime_timeout:
            self.reset()
            return False
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_RETURN:
                if self.buffer.upper() == self.secret:
                    return True
                else:
                    self.reset()
                    return False
            elif ev.key == pygame.K_BACKSPACE:
                self.buffer = self.buffer[:-1]
            else:
                ch = ev.unicode
                if ch and ch.isprintable():
                    self.buffer += ch
        return False

    def reset(self):
        self.primed = False
        self.buffer = ''

# --------------------------- Game --------------------------- #
class BabyKiosk:
    def __init__(self, args):
        self.args = args
        flags = pygame.FULLSCREEN
        if args.windowed:
            flags = 0
        # Borderless
        flags |= pygame.NOFRAME
        self.screen = pygame.display.set_mode((0, 0), flags)
        self.w, self.h = self.screen.get_size()
        
        # Background video discovery
        script_dir = os.path.dirname(os.path.abspath(__file__))
        bg_path = _resolve_bg_path(args, script_dir)

        self.background = None
        if not getattr(args, 'no_bg', False):
            if bg_path and (cv2 is not None or imageio is not None):
                self.background = BackgroundVideo(bg_path, (self.w, self.h))
            else:
                self.background = BackgroundWaves((self.w, self.h))

        # Try SDL2 keyboard grab (prevents Alt+Tab on some setups)
        self._sdl2_window = None
        try:
            from pygame._sdl2 import video as sdl2_video
            self._sdl2_window = sdl2_video.Window.from_display_module()
            try:
                self._sdl2_window.keyboard_grab = True
            except Exception:
                pass
        except Exception:
            pass

        pygame.display.set_caption("BabyKiosk")
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)  # pointer grab via SDL as extra belt
        try:
            pygame.display.set_allow_screensaver(False)
        except Exception:
            pass

        # Fonts (dynamic, scale with resolution)
        self.emoji_path = (self.args.emoji_font if getattr(self.args, 'emoji_font', None) else find_emoji_font())
        self._last_size = (0, 0)
        self.big_font = None
        self.mid_font = None
        self.small_font = None
        self.alpha_font = None
        self.emoji_font = None
        self.emoji_px = 64
        self._refresh_fonts(force=True)

        # Twemoji cache (bundled assets)
        # Locate Twemoji assets next to this script: ./assets/72x72
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(script_dir, 'assets', '72x72'),
            os.path.join(script_dir, 'assets'),
            os.path.join(script_dir, 'assets', 'png'),
        ]
        self.twemoji_dir = next((d for d in candidates if os.path.isdir(d)), None)
        self.emoji_cache: dict[tuple[str, int], pygame.Surface] = {}

        self.particles: list[Particle] = []
        self.glyphs: list[FloatingGlyph] = []
        self.escape = EscapeGate(args.escape_code)

        # Whether to block Alt/Super entirely while running (default: enabled)
        self.block_alt = not args.allow_alt
        self.block_super = not getattr(args, 'allow_super', False)

        self.locker = None
        self.on_wayland = (pygame.display.get_driver().lower() == 'wayland')  # platform hint

        # GNOME keybinding blocker (only on GNOME+X11, unless disabled)
        self.gnome_blocker = None
        if (not args.windowed) and (pygame.display.get_driver().lower() == 'x11') and (not getattr(args, 'no_gnome_keyblock', False)):
            desktop = os.environ.get('XDG_CURRENT_DESKTOP', '') + ' ' + os.environ.get('DESKTOP_SESSION', '')
            if 'gnome' in desktop.lower():
                try:
                    self.gnome_blocker = GNOMEKeyBlocker(nuclear=args.nuclear)
                    self.gnome_blocker.enable()
                except Exception:
                    self.gnome_blocker = None

        # If X11, activate strong grab
        wm = pygame.display.get_wm_info()
        if _X11_OK and 'window' in wm and pygame.display.get_driver().lower() == 'x11' and not args.windowed:
            try:
                self.locker = X11Locker(wm['window'])
                self.locker.lock()
                if self.block_alt:
                    try:
                        self.locker.block_alt()
                    except Exception:
                        pass
                if self.block_super:
                    try:
                        self.locker.block_super()
                    except Exception:
                        pass
            except Exception:
                self.locker = None

        # If Windows, install low-level key blocker (best-effort)
        self.win_blocker = None
        if sys.platform.startswith('win') and not args.windowed and not getattr(args, 'no_win_keyblock', False):
            try:
                self.win_blocker = WinKeyBlocker()
                self.win_blocker.install()
            except Exception:
                self.win_blocker = None

        # Simple synth: optional
        self.sound = None
        if not args.no_sound:
            try:
                pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
                self.sound = self._make_click_sound()
            except Exception:
                self.sound = None

        # --- Hold/continuous-spawn state (limits to avoid overload) ---
        self.key_hold: dict[int, dict] = {}
        self.hold_interval_alnum = 0.09   # ~11 per second per key
        self.hold_interval_emoji = 0.09
        self.max_glyphs = 180
        self.max_particles = 800

        # "Resting hand" detection: many simultaneous non-modifier keys => blank screen
        self.rest_threshold = 4
        self.rest_delay = 0.12  # seconds the threshold must be exceeded before blanking
        self.resting = False
        self._rest_timer = 0.0

    def _make_click_sound(self):
        # Generate a tiny click/bleep to reward keypresses
        import array
        sr = 22050
        dur = 0.08
        freq = random.choice([330, 392, 523, 659, 784])
        n = int(sr * dur)
        buf = array.array('h')
        for i in range(n):
            t = i / sr
            # simple decaying sine
            amp = int(3000 * math.exp(-6*t))
            val = int(amp * math.sin(2*math.pi*freq*t))
            buf.append(val)
        return pygame.mixer.Sound(buffer=buf)

    def spawn_burst(self, x: int, y: int) -> None:
        for _ in range(40):
            ang = random.uniform(0, 2 * math.pi)
            spd = random.uniform(50, 350)
            vx = math.cos(ang) * spd
            vy = math.sin(ang) * spd
            r = random.uniform(3, 10)
            color: tuple[int, int, int] = (
                random.randint(60, 255),
                random.randint(60, 255),
                random.randint(60, 255),
            )
            life = random.uniform(0.6, 1.6)
            self.particles.append(Particle(x, y, vx, vy, r, life, color))
        if len(self.particles) > self.max_particles:
            self.particles = self.particles[-self.max_particles:]

    def spawn_glyph(
        self,
        text: str,
        x: int,
        y: int,
        font: pygame.font.Font | None = None,
        fallback_font: pygame.font.Font | None = None,
        image: pygame.Surface | None = None,
    ):
        color: tuple[int, int, int] = (
            random.randint(100, 255),
            random.randint(100, 255),
            random.randint(100, 255),
        )
        vx = random.uniform(-80, 80)
        vy = random.uniform(-30, 30)
        life = random.uniform(0.8, 1.6)
        self.glyphs.append(FloatingGlyph(
            text, x, y, vx, vy, life, color, font or self.mid_font, fallback_font or self.mid_font, image
        ))
        if len(self.glyphs) > self.max_glyphs:
            self.glyphs = self.glyphs[-self.max_glyphs:]


    def draw_wayland_warning(self):
        if self.on_wayland and not self.args.windowed:
            text = "Wayland detected: system shortcuts may not be fully blocked."
            s = self.small_font.render(text, True, (255, 255, 0))
            self.screen.blit(s, (20, self.h - 40))

    def draw_escape_overlay(self):
        overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))
        lines = [
            "Escape mode: type your secret and press Enter",
            f"Secret so far: {self.escape.buffer}",
        ]
        y = self.h // 2 - 60
        for line in lines:
            s = self.mid_font.render(line, True, (255, 255, 255))
            rect = s.get_rect(center=(self.w//2, y))
            self.screen.blit(s, rect)
            y += 70

    def _refresh_fonts(self, force: bool = False):
        # Recompute font sizes based on current resolution (bigger letters/numbers)
        if not force and (self.w, self.h) == getattr(self, '_last_size', None):
            return
        self._last_size = (self.w, self.h)
        base_h = max(480, self.h)
        big_sz   = max(120, int(base_h * 0.18))  # Title
        mid_sz   = max( 64, int(base_h * 0.10))  # UI / default glyphs
        small_sz = max( 28, int(base_h * 0.03))  # hints
        alpha_sz = max(160, int(base_h * 0.22))  # **LARGE letters/numbers**
        emoji_sz = max( 64, int(base_h * 0.12))  # emojis

        self.big_font   = pygame.font.SysFont(None, big_sz)
        self.mid_font   = pygame.font.SysFont(None, mid_sz)
        self.small_font = pygame.font.SysFont(None, small_sz)
        self.alpha_font = pygame.font.SysFont(None, alpha_sz)
        self.emoji_px   = emoji_sz

        # Emoji font selection
        self.emoji_font = self.mid_font
        if self.emoji_path:
            try:
                self.emoji_font = pygame.font.Font(self.emoji_path, emoji_sz)
            except Exception:
                self.emoji_font = self.mid_font
        if self.emoji_path:
            try:
                self.emoji_font = pygame.font.Font(self.emoji_path, emoji_sz)
            except Exception:
                self.emoji_font = self.mid_font

    def _emoji_to_twemoji_name(self, s: str) -> str:
        # Convert an emoji string to Twemoji filename (hyphen-joined codepoints, drop VS-16)
        cps = []
        for ch in s:
            cp = ord(ch)
            if cp == 0xFE0F:  # variation selector-16; twemoji filenames usually omit this
                continue
            cps.append(f"{cp:x}")
        return '-'.join(cps)

    def _twemoji_surface(self, s: str, px: int) -> "pygame.Surface | None":
        """Load a Twemoji PNG for the given emoji, scaled to px. Uses self.twemoji_dir."""
        # Ensure we have an assets dir configured
        base = getattr(self, "twemoji_dir", None)
        if not base:
            return None

        # Cache hit?
        key = (s, px)
        cached = self.emoji_cache.get(key)
        if cached is not None:
            return cached

        # Map emoji → filename like "1f389.png" (VS16 dropped by _emoji_to_twemoji_name)
        name = self._emoji_to_twemoji_name(s)
        candidates = [
            os.path.join(base, f"{name}.png"),
            os.path.join(base, "72x72", f"{name}.png"),
            os.path.join(base, "png", f"{name}.png"),
        ]

        # Try first existing path
        path = next((p for p in candidates if os.path.exists(p)), None)
        if not path:
            return None

        # Load + scale
        try:
            img = pygame.image.load(path).convert_alpha()
            if px and (img.get_width() != px or img.get_height() != px):
                img = pygame.transform.smoothscale(img, (px, px))
            self.emoji_cache[key] = img
            return img
        except Exception:
            return None

    def _restore_fullscreen(self):
        # Force window back to fullscreen, reapply grabs and raise it
        try:
            flags = pygame.FULLSCREEN | pygame.NOFRAME if not self.args.windowed else pygame.NOFRAME
            self.screen = pygame.display.set_mode((0, 0), flags)
            pygame.event.set_grab(True)
            pygame.mouse.set_visible(False)
        except Exception:
            pass
        if self.locker:
            try:
                self.locker.lock()
            except Exception:
                pass
        # SDL2 keyboard grab again
        try:
            if self._sdl2_window:
                self._sdl2_window.keyboard_grab = True
        except Exception:
            pass

    def run(self):
        clock = pygame.time.Clock()
        running = True
        last_regrab = 0.0

        # Opening splash
        self.screen.fill((0, 0, 0))
        title = self.big_font.render("SMASH!", True, (255, 255, 255))
        self.screen.blit(title, title.get_rect(center=(self.w // 2, self.h // 2)))
        hint = self.small_font.render("(Hold BOTH Shift + press F12 to enter escape)", True, (200, 200, 200))
        self.screen.blit(hint, hint.get_rect(center=(self.w // 2, self.h // 2 + 120)))
        pygame.display.flip()
        pygame.time.delay(800)

        while running:
            dt = clock.tick(60) / 1000.0

            # If focus was lost/minimized, force restore
            try:
                active = pygame.display.get_active()
            except Exception:
                active = 1
            if not active:
                self._restore_fullscreen()

            # Maintain X11 grabs (heartbeat)
            tnow = time.time()
            if self.locker and (tnow - last_regrab) > 1.0:
                self.locker.heartbeat()
                last_regrab = tnow

            # --- events ---
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    if self.escape.primed:
                        running = False

                elif ev.type == pygame.KEYDOWN:
                    mods = pygame.key.get_mods()

                    # Ignore PrintScreen/SysRq
                    _kps = [getattr(pygame, 'K_PRINTSCREEN', None), getattr(pygame, 'K_SYSREQ', None)]
                    if ev.key in [k for k in _kps if k is not None]:
                        continue

                    # Block Alt combos
                    if self.block_alt:
                        alt_mask = (pygame.KMOD_LALT | pygame.KMOD_RALT | pygame.KMOD_ALT)
                        if (pygame.key.get_mods() & alt_mask) or ev.key in (getattr(pygame, 'K_LALT', 0),
                                                                            getattr(pygame, 'K_RALT', 0)):
                            continue

                    # Block Super/Win combos
                    if self.block_super:
                        gui_mask = getattr(pygame, 'KMOD_GUI', 0) | getattr(pygame, 'KMOD_LGUI', 0) | getattr(pygame,
                                                                                                              'KMOD_RGUI',
                                                                                                              0)
                        if pygame.key.get_mods() & gui_mask:
                            continue
                        if ev.key in (
                                getattr(pygame, 'K_LSUPER', 0), getattr(pygame, 'K_RSUPER', 0),
                                getattr(pygame, 'K_LMETA', 0), getattr(pygame, 'K_RMETA', 0),
                                getattr(pygame, 'K_LGUI', 0), getattr(pygame, 'K_RGUI', 0),
                        ):
                            continue

                    # Escape mode
                    if self.escape.try_prime(mods, ev.key):
                        continue
                    if self.escape.primed:
                        if self.escape.feed(ev):
                            running = False
                        continue

                    # Regular play: burst + glyph/emoji
                    x = random.randint(40, self.w - 40)
                    y = random.randint(40, self.h - 40)
                    self.spawn_burst(x, y)

                    ch = ev.unicode if hasattr(ev, 'unicode') else ''
                    now = time.time()
                    is_alnum = bool(ch and ch.isalnum())
                    self.key_hold[ev.key] = {
                        'is_alnum': is_alnum,
                        'text': ch.upper() if is_alnum else '',
                        'next': now + (self.hold_interval_alnum if is_alnum else self.hold_interval_emoji),
                    }
                    if is_alnum:
                        self.spawn_glyph(ch.upper(), x, y, font=self.alpha_font, fallback_font=self.mid_font)
                    else:
                        emoji = random.choice(EMOJIS)
                        img = self._twemoji_surface(emoji, self.emoji_px) if self.twemoji_dir else None
                        self.spawn_glyph(emoji, x, y, font=self.emoji_font, fallback_font=self.mid_font, image=img)

                    if self.sound:
                        try:
                            self.sound.play()
                        except Exception:
                            pass

                elif ev.type == pygame.KEYUP:
                    self.key_hold.pop(ev.key, None)

                elif ev.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN):
                    if not self.args.windowed:
                        pygame.mouse.set_pos(self.w // 2, self.h // 2)

            # --- continuous spawns & resting-hand blanking ---
            mod_keys = {
                getattr(pygame, 'K_LSHIFT', 0), getattr(pygame, 'K_RSHIFT', 0),
                getattr(pygame, 'K_LCTRL', 0), getattr(pygame, 'K_RCTRL', 0),
                getattr(pygame, 'K_LALT', 0), getattr(pygame, 'K_RALT', 0),
                getattr(pygame, 'K_LMETA', 0), getattr(pygame, 'K_RMETA', 0),
                getattr(pygame, 'K_LGUI', 0), getattr(pygame, 'K_RGUI', 0),
            }
            nonmod_count = sum(1 for k in self.key_hold.keys() if k not in mod_keys)
            if nonmod_count >= self.rest_threshold:
                self._rest_timer += dt
                if self._rest_timer >= self.rest_delay and not self.resting:
                    self.resting = True
                    self.particles.clear()
                    self.glyphs.clear()
            else:
                self._rest_timer = 0.0
                if self.resting:
                    self.resting = False

            if not self.escape.primed and not self.resting:
                now = time.time()
                for k, info in list(self.key_hold.items()):
                    if now >= info.get('next', now):
                        x = random.randint(40, self.w - 40)
                        y = random.randint(40, self.h - 40)
                        if info.get('is_alnum') and info.get('text'):
                            self.spawn_glyph(info['text'], x, y, font=self.alpha_font, fallback_font=self.mid_font)
                            info['next'] = now + self.hold_interval_alnum
                        else:
                            emoji = random.choice(EMOJIS)
                            img = self._twemoji_surface(emoji, self.emoji_px) if self.twemoji_dir else None
                            self.spawn_glyph(emoji, x, y, font=self.emoji_font, fallback_font=self.mid_font, image=img)
                            info['next'] = now + self.hold_interval_emoji

            # --- handle resize (fonts + background) ---
            self.w, self.h = self.screen.get_size()
            self._refresh_fonts()
            if self.background:
                self.background.resize((self.w, self.h))

            # --- update game objects ---
            self.particles = [p for p in self.particles if p.life > 0 and p.r > 0]
            for p in self.particles:
                p.update(dt)
            self.glyphs = [g for g in self.glyphs if g.life > 0]
            for g in self.glyphs:
                g.update(dt)

            if self.background:
                self.background.update(dt)

            # --- DRAW (ORDER MATTERS) ---
            if self.resting:
                # force blank screen while resting-hand is detected
                self.screen.fill((0, 0, 0))
            else:
                if self.background:
                    self.background.draw(self.screen)
                else:
                    self.screen.fill((0, 0, 0))

                # then game layers
                for p in self.particles:
                    p.draw(self.screen)
                for g in self.glyphs:
                    g.draw(self.screen)

                # overlays last
                self.draw_wayland_warning()
                if self.escape.primed:
                    self.draw_escape_overlay()

                # optional background status (debug)
                # if self.background and getattr(self.background, 'status', ''):
                #     t = self.small_font.render(self.background.status, True, (200, 200, 220))
                #     self.screen.blit(t, (10, self.h - t.get_height() - 10))

            pygame.display.flip()

        # Clean up
        if self.locker:
            self.locker.unlock()


def parse_args():
    ap = argparse.ArgumentParser(description="TinyFingers-style kiosk game for babies")
    ap.add_argument('--escape-code', default='GROWNUP', help='Secret word to exit after priming (default: GROWNUP)')
    ap.add_argument('--no-sound', action='store_true', default=True, help='Disable key click sounds')
    ap.add_argument('--windowed', action='store_true', help='Run in a window (no X11 lock/grab)')
    ap.add_argument('--allow-alt', action='store_true', help='Do NOT block the Alt modifier (default blocks Alt on X11)')
    ap.add_argument('--allow-super', action='store_true', help='Do NOT block the Super/Win modifier (default blocks on X11)')
    ap.add_argument('--emoji-font', help='Path to a TTF emoji-capable font (e.g., NotoColorEmoji.ttf)')
    ap.add_argument('--no-gnome-keyblock', action='store_true', help='Do not unbind GNOME Alt+Tab/Alt+` shortcuts')
    ap.add_argument('--nuclear', dest='nuclear', action='store_true', default=True, help='Blank nearly all GNOME keybindings while the game runs (default: ON)')
    ap.add_argument('--no-nuclear', dest='nuclear', action='store_false', help='Disable the GNOME nuclear keybinding sweep for this run')
    ap.add_argument('--no-win-keyblock', action='store_true', help='(Windows) Do not install the low-level keyboard hook')
    ap.add_argument('--bg', type=str, metavar='PATH', default=None, help='Path to a background video (default: assets/background)')
    ap.add_argument('--no-bg', action='store_true', help='Disable background video/animation')
    return ap.parse_args()


def main():
    # SDL/pygame behavior tweaks to reduce minimize/focus loss escapes
    os.environ.setdefault('SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS', '0')
    os.environ.setdefault('SDL_HINT_GRAB_KEYBOARD', '1')
    pygame.init()
    try:
        game = BabyKiosk(parse_args())
        # Ensure we ungrab on crash
        def _cleanup():
            try:
                if getattr(game, 'gnome_blocker', None):
                    game.gnome_blocker.disable()
            except Exception:
                pass
            try:
                if getattr(game, 'win_blocker', None):
                    game.win_blocker.uninstall()
            except Exception:
                pass
            try:
                if game.locker:
                    game.locker.unlock()
            except Exception:
                pass
            try:
                pygame.display.quit()
            except Exception:
                pass
        atexit.register(_cleanup)
        game.run()
    finally:
        pygame.quit()


if __name__ == '__main__':
    main()

