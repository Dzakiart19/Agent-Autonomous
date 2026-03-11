"""
VNC Manager for Dzeck AI.
Starts Xvfb virtual display + x11vnc server + websockify proxy.
Provides real-time VNC streaming to the web/mobile frontend via noVNC.
"""
import os
import subprocess
import threading
import time
import logging
import atexit

logger = logging.getLogger(__name__)

DISPLAY_NUM = ":10"
VNC_PORT = 5910
WS_PORT = 6081
SCREEN_RES = "1280x720x24"

_procs: list = []
_started = False
_lock = threading.Lock()


def _kill_proc(proc):
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _cleanup():
    for p in _procs:
        _kill_proc(p)


atexit.register(_cleanup)


def _find_bin(name: str) -> str:
    """Find binary in PATH or nix store, checking bin/ subdirectories."""
    import shutil
    path = shutil.which(name)
    if path:
        return path
    # Search nix store — binaries live in HASH-pkg-VER/bin/NAME
    try:
        import glob as _glob
        # Check bin/ subdirectory (most common)
        matches = _glob.glob(f"/nix/store/*/{name}")
        matches += _glob.glob(f"/nix/store/*/bin/{name}")
        if matches:
            # Prefer bin/ paths
            bin_paths = [m for m in matches if "/bin/" in m]
            return bin_paths[0] if bin_paths else matches[0]
    except Exception:
        pass
    return name


def start_vnc() -> bool:
    global _started
    with _lock:
        if _started:
            # Verify all procs still alive
            if all(p.poll() is None for p in _procs if p is not None):
                return True
            # Dead — restart
            for p in _procs:
                _kill_proc(p)
            _procs.clear()
            _started = False

        try:
            env = os.environ.copy()

            xvfb_bin = _find_bin("Xvfb")
            x11vnc_bin = _find_bin("x11vnc")

            logger.info(f"[VNC] Xvfb: {xvfb_bin}")
            logger.info(f"[VNC] x11vnc: {x11vnc_bin}")
            logger.info(f"[VNC] Starting Xvfb on display {DISPLAY_NUM} ({SCREEN_RES})...")

            xvfb_proc = subprocess.Popen(
                [xvfb_bin, DISPLAY_NUM, "-screen", "0", SCREEN_RES,
                 "-ac", "-nolisten", "tcp", "-dpi", "96"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=env,
            )
            _procs.append(xvfb_proc)
            time.sleep(2.0)

            if xvfb_proc.poll() is not None:
                logger.error("[VNC] Xvfb failed to start.")
                return False

            display_env = dict(env, DISPLAY=DISPLAY_NUM)

            logger.info(f"[VNC] Starting x11vnc on port {VNC_PORT}...")
            x11vnc_proc = subprocess.Popen(
                [
                    x11vnc_bin,
                    "-display", DISPLAY_NUM,
                    "-forever",
                    "-shared",
                    "-nopw",
                    "-rfbport", str(VNC_PORT),
                    "-noxdamage",
                    "-noxfixes",
                    "-nocursorshape",
                    "-nocursor",
                    "-quiet",
                    "-bg",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=display_env,
            )
            _procs.append(x11vnc_proc)
            time.sleep(2.0)

            if x11vnc_proc.poll() is not None:
                logger.error("[VNC] x11vnc failed to start.")
                return False

            logger.info(f"[VNC] Starting websockify ws:{WS_PORT} -> vnc:127.0.0.1:{VNC_PORT}...")
            ws_proc = subprocess.Popen(
                ["python3", "-m", "websockify",
                 "--web", "/tmp/novnc_web",
                 str(WS_PORT), f"127.0.0.1:{VNC_PORT}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=env,
            )
            _procs.append(ws_proc)
            time.sleep(1.5)

            if ws_proc.poll() is not None:
                # Try without --web flag (in case it fails due to missing web dir)
                ws_proc2 = subprocess.Popen(
                    ["python3", "-m", "websockify",
                     str(WS_PORT), f"127.0.0.1:{VNC_PORT}"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    env=env,
                )
                _procs.append(ws_proc2)
                time.sleep(1.5)
                if ws_proc2.poll() is not None:
                    logger.error("[VNC] websockify failed to start.")
                    return False

            _started = True
            logger.info(f"[VNC] Stack ready: DISPLAY={DISPLAY_NUM}, VNC={VNC_PORT}, WS={WS_PORT}")

            _draw_idle_screen()
            return True

        except Exception as e:
            logger.error(f"[VNC] Failed to start VNC stack: {e}")
            return False


def _draw_idle_screen():
    """Draw a background on the virtual display so it's not black."""
    try:
        env = dict(os.environ, DISPLAY=DISPLAY_NUM)
        xsetroot = _find_bin("xsetroot")
        subprocess.Popen(
            [xsetroot, "-solid", "#0e0e14"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).wait(timeout=3)
    except Exception:
        pass


def is_running() -> bool:
    return _started and all(p.poll() is None for p in _procs if p is not None)


def get_display() -> str:
    return DISPLAY_NUM if _started else ""


def get_ws_port() -> int:
    return WS_PORT
