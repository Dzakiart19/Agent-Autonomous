"""
E2B Sandbox Manager for Dzeck AI Agent.
Provides a persistent, isolated cloud sandbox for shell and browser automation.
All tool calls (shell, browser) are routed through this secure E2B environment.
Uses E2B v2 API: Sandbox.create() pattern.
"""
import os
import json
import logging
import threading
import base64
from typing import Optional, Any, Dict

logger = logging.getLogger(__name__)

E2B_API_KEY = os.environ.get("E2B_API_KEY", "")

_sandbox_lock = threading.Lock()
_sandbox: Optional[Any] = None


def get_sandbox() -> Optional[Any]:
    """Get or create the E2B sandbox singleton."""
    global _sandbox
    if _sandbox is not None:
        try:
            _sandbox.commands.run("echo ok", timeout=5)
            return _sandbox
        except Exception:
            logger.warning("[E2B] Sandbox appears dead, recreating...")
            _sandbox = None

    with _sandbox_lock:
        if _sandbox is None:
            _sandbox = _create_sandbox()
    return _sandbox


def _create_sandbox() -> Optional[Any]:
    """Create a new E2B sandbox instance using Sandbox.create()."""
    if not E2B_API_KEY:
        logger.error("[E2B] E2B_API_KEY not set. Cannot create sandbox.")
        return None
    try:
        from e2b import Sandbox
        logger.info("[E2B] Creating new sandbox...")
        sb = Sandbox.create(api_key=E2B_API_KEY, timeout=300)
        logger.info("[E2B] Sandbox ready (id=%s). Installing Playwright...", sb.sandbox_id)
        sb.commands.run(
            "pip install playwright --quiet 2>/dev/null && playwright install chromium --with-deps 2>/dev/null || true",
            timeout=120
        )
        logger.info("[E2B] Sandbox ready with Playwright (id=%s)", sb.sandbox_id)
        return sb
    except Exception as e:
        logger.error("[E2B] Failed to create sandbox: %s", e)
        return None


def reset_sandbox() -> Optional[Any]:
    """Force-recreate the sandbox."""
    global _sandbox
    with _sandbox_lock:
        if _sandbox:
            try:
                _sandbox.kill()
            except Exception:
                pass
        _sandbox = _create_sandbox()
    return _sandbox


def run_command(command: str, workdir: str = "/home/user", timeout: int = 90) -> Dict[str, Any]:
    """Run a shell command in the E2B sandbox and return result dict."""
    sb = get_sandbox()
    if sb is None:
        return {
            "success": False,
            "stdout": "",
            "stderr": "E2B sandbox not available. Check E2B_API_KEY.",
            "exit_code": -1,
        }
    try:
        result = sb.commands.run(command, cwd=workdir, timeout=timeout)
        return {
            "success": (result.exit_code == 0),
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "exit_code": result.exit_code,
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
        }


def run_browser_script(script: str, timeout: int = 90) -> Dict[str, Any]:
    """Run a Playwright Python script inside E2B sandbox and return JSON output."""
    sb = get_sandbox()
    if sb is None:
        return {"success": False, "error": "E2B sandbox not available."}
    try:
        script_path = "/tmp/dzeck_browser_script.py"
        sb.files.write(script_path, script)
        result = sb.commands.run(f"python3 {script_path}", timeout=timeout)
        stdout = result.stdout or ""
        if result.exit_code != 0:
            err = result.stderr or result.stdout or "Script failed"
            return {"success": False, "error": err}
        try:
            return json.loads(stdout)
        except Exception:
            return {"success": True, "output": stdout}
    except Exception as e:
        return {"success": False, "error": str(e)}


def read_file(path: str) -> Optional[str]:
    """Read a file from the E2B sandbox."""
    sb = get_sandbox()
    if sb is None:
        return None
    try:
        return sb.files.read(path)
    except Exception:
        return None


def write_file(path: str, content: str) -> bool:
    """Write a file to the E2B sandbox."""
    sb = get_sandbox()
    if sb is None:
        return False
    try:
        sb.files.write(path, content)
        return True
    except Exception:
        return False
