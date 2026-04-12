import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.services.hermes import HermesConfig, redact

router = APIRouter(prefix="/computer-use")

CDP_URL = "http://127.0.0.1:9222"
PROFILE_DIR = Path.home() / ".hermes" / "studio-chrome-profile"


@router.get("/status")
async def status() -> dict[str, Any]:
    connected = _cdp_ready(CDP_URL)
    if connected:
        os.environ["BROWSER_CDP_URL"] = CDP_URL
    return {
        "browser_cdp_url": CDP_URL,
        "chrome_connected": connected,
        "profile_dir": str(PROFILE_DIR),
        "mode": "live-chrome-cdp" if connected else "not-connected",
        "detail": (
            "Hermes browser tools will operate on the visible Hermes Studio Chrome profile."
            if connected
            else "Connect Chrome so browser tools can control a visible persistent session."
        ),
    }


@router.post("/connect-browser")
async def connect_browser() -> dict[str, Any]:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["BROWSER_CDP_URL"] = CDP_URL
    HermesConfig().write_env_values({"BROWSER_CDP_URL": CDP_URL})

    if not _cdp_ready(CDP_URL):
        _launch_chrome()
        _wait_for_cdp(CDP_URL, timeout=12)

    connected = _cdp_ready(CDP_URL)
    return {
        "success": connected,
        "browser_cdp_url": CDP_URL,
        "chrome_connected": connected,
        "profile_dir": str(PROFILE_DIR),
        "error": None if connected else "Chrome did not expose the DevTools endpoint on port 9222.",
    }


@router.post("/disconnect-browser")
async def disconnect_browser() -> dict[str, Any]:
    os.environ.pop("BROWSER_CDP_URL", None)
    HermesConfig().write_env_values({"BROWSER_CDP_URL": None})
    return {"success": True, "chrome_connected": _cdp_ready(CDP_URL)}


def _launch_chrome() -> None:
    args = [
        "open",
        "-na",
        "Google Chrome",
        "--args",
        "--remote-debugging-port=9222",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        subprocess.Popen(
            [
                "open",
                "-a",
                "Google Chrome",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _wait_for_cdp(url: str, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _cdp_ready(url):
            return
        time.sleep(0.4)


def _cdp_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/json/version", timeout=1.5) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False
    except Exception as exc:
        redacted = redact(str(exc))
        return bool(redacted and False)
