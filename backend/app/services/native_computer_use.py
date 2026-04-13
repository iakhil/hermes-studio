"""Generic native macOS computer-use bridge for Hermes Studio.

The module is intentionally low-level. Hermes should combine these primitives
with screenshot observation and vision analysis instead of relying on
app-specific shortcuts.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


SPECIAL_KEY_CODES = {
    "return": 36,
    "enter": 36,
    "tab": 48,
    "space": 49,
    "delete": 51,
    "backspace": 51,
    "escape": 53,
    "esc": 53,
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
    "page-up": 116,
    "page-down": 121,
    "home": 115,
    "end": 119,
}

MODIFIERS = {
    "command": "command down",
    "cmd": "command down",
    "meta": "command down",
    "shift": "shift down",
    "option": "option down",
    "alt": "option down",
    "control": "control down",
    "ctrl": "control down",
}


class BridgeError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="native_computer_use",
        description="Control and observe native macOS apps for Hermes Studio.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Report bridge dependency status.")
    subparsers.add_parser("observe", help="Capture the visible screen and report the frontmost app.")
    subparsers.add_parser("frontmost", help="Report the frontmost macOS app.")

    open_app = subparsers.add_parser("open-app", help="Open or activate a native app.")
    open_app.add_argument("--name", required=True)

    click = subparsers.add_parser("click", help="Click a screen coordinate.")
    click.add_argument("--x", required=True, type=int)
    click.add_argument("--y", required=True, type=int)
    click.add_argument("--double", action="store_true")

    type_text = subparsers.add_parser("type", help="Type text through System Events.")
    type_text.add_argument("--text")
    type_text.add_argument("--stdin", action="store_true")

    paste = subparsers.add_parser("paste", help="Paste text through the clipboard.")
    paste.add_argument("--text")
    paste.add_argument("--stdin", action="store_true")

    press = subparsers.add_parser("press", help="Press a key such as return, tab, escape, down.")
    press.add_argument("--key", required=True)
    press.add_argument("--repeat", type=int, default=1)

    scroll = subparsers.add_parser("scroll", help="Scroll the focused view using page keys.")
    scroll.add_argument("--direction", choices=["up", "down"], required=True)
    scroll.add_argument("--amount", type=int, default=1)

    hotkey = subparsers.add_parser("hotkey", help="Press a hotkey such as command,n or command,shift,g.")
    hotkey.add_argument("--keys", required=True)
    hotkey.add_argument("--repeat", type=int, default=1)

    wait = subparsers.add_parser("wait", help="Wait for UI changes.")
    wait.add_argument("--seconds", required=True, type=float)

    args = parser.parse_args(argv)

    try:
        result = dispatch(args)
    except Exception as exc:
        print_json({"ok": False, "error": summarize_error(exc)})
        return 1

    print_json({"ok": True, **result})
    return 0


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "status":
        return status()
    if args.command == "observe":
        return observe()
    if args.command == "frontmost":
        return {"frontmost_app": frontmost_app()}
    if args.command == "open-app":
        return open_app(args.name)
    if args.command == "click":
        return click(args.x, args.y, double=args.double)
    if args.command == "type":
        return type_text(read_text_arg(args))
    if args.command == "paste":
        return paste_text(read_text_arg(args))
    if args.command == "press":
        return press_key(args.key, repeat=args.repeat)
    if args.command == "scroll":
        return scroll_view(args.direction, amount=args.amount)
    if args.command == "hotkey":
        return press_hotkey(args.keys, repeat=args.repeat)
    if args.command == "wait":
        time.sleep(max(0.0, args.seconds))
        return {"waited_seconds": args.seconds}
    raise BridgeError(f"Unsupported command: {args.command}")


def status() -> dict[str, Any]:
    return {
        "platform": sys.platform,
        "available": sys.platform == "darwin",
        "osascript": bool(shutil.which("osascript")),
        "screencapture": bool(shutil.which("screencapture")),
        "sips": bool(shutil.which("sips")),
        "open": bool(shutil.which("open")),
        "cliclick": bool(shutil.which("cliclick")),
        "notes": [
            "Accessibility is required for click, type, press, and hotkey.",
            "Screen Recording is required for useful screenshots.",
            "cliclick is optional; System Events handles the default actions.",
            "Use frontmost or observe when you need active-app context.",
        ],
    }


def observe() -> dict[str, Any]:
    require_macos()
    if not shutil.which("screencapture"):
        raise BridgeError("screencapture is not available.")

    target_dir = Path(tempfile.gettempdir()) / "hermes-studio-computer-use"
    target_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = target_dir / f"screen-{int(time.time() * 1000)}.png"

    run(["screencapture", "-x", str(screenshot_path)], timeout=10)
    if not screenshot_path.exists() or screenshot_path.stat().st_size <= 0:
        raise BridgeError("Screen capture did not produce an image. Grant Screen Recording permission.")

    return {
        "frontmost_app": safe_frontmost_app(),
        "screenshot_path": str(screenshot_path),
        "screenshot": image_size(screenshot_path),
        "next_step": (
            "Use vision_analyze with this screenshot_path to decide the next click, "
            "typing, hotkey, or paste action."
        ),
    }


def open_app(name: str) -> dict[str, Any]:
    require_macos()
    app_name = clean_required(name, "app name")
    run(["open", "-a", app_name], timeout=15)
    return {"opened_app": app_name}


def image_size(path: Path) -> dict[str, int] | None:
    if not shutil.which("sips"):
        return None
    try:
        result = run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)], timeout=5)
    except Exception:
        return None
    values: dict[str, int] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, raw_value = [part.strip() for part in line.split(":", 1)]
        try:
            parsed = int(raw_value)
        except ValueError:
            continue
        if key == "pixelWidth":
            values["width"] = parsed
        elif key == "pixelHeight":
            values["height"] = parsed
    return values or None


def click(x: int, y: int, *, double: bool = False) -> dict[str, Any]:
    require_macos()
    if shutil.which("cliclick"):
        action = "dc" if double else "c"
        run(["cliclick", f"{action}:{x},{y}"], timeout=5)
    else:
        script = f'tell application "System Events" to click at {{{x}, {y}}}'
        osascript(script, timeout=5)
        if double:
            time.sleep(0.08)
            osascript(script, timeout=5)
    return {"clicked": {"x": x, "y": y, "double": double}}


def type_text(text: str) -> dict[str, Any]:
    require_macos()
    value = clean_required(text, "text")
    osascript(f'tell application "System Events" to keystroke {applescript_string(value)}', timeout=15)
    return {"typed_characters": len(value)}


def paste_text(text: str) -> dict[str, Any]:
    require_macos()
    value = clean_required(text, "text")
    script = f'''
set textToPaste to {applescript_string(value)}
set oldClipboard to missing value
try
    set oldClipboard to the clipboard as text
end try
set the clipboard to textToPaste
delay 0.12
tell application "System Events" to keystroke "v" using {{command down}}
delay 0.2
if oldClipboard is not missing value then
    try
        set the clipboard to oldClipboard
    end try
end if
'''
    osascript(script, timeout=15)
    return {"pasted_characters": len(value)}


def press_key(key: str, *, repeat: int = 1) -> dict[str, Any]:
    require_macos()
    normalized = key.strip().lower()
    repeat = clamp_repeat(repeat)
    if normalized in SPECIAL_KEY_CODES:
        script = repeat_script(f'key code {SPECIAL_KEY_CODES[normalized]}', repeat)
    elif len(normalized) == 1:
        script = repeat_script(f'keystroke {applescript_string(normalized)}', repeat)
    else:
        raise BridgeError(f"Unsupported key: {key}")
    osascript(f'tell application "System Events"\n{script}\nend tell', timeout=10)
    return {"pressed": normalized, "repeat": repeat}


def scroll_view(direction: str, *, amount: int = 1) -> dict[str, Any]:
    normalized = direction.strip().lower()
    if normalized not in {"up", "down"}:
        raise BridgeError("Scroll direction must be up or down.")
    key = "page-up" if normalized == "up" else "page-down"
    repeat = clamp_repeat(amount)
    press_key(key, repeat=repeat)
    return {"scrolled": normalized, "amount": repeat}


def press_hotkey(keys: str, *, repeat: int = 1) -> dict[str, Any]:
    require_macos()
    parts = [part.strip().lower() for part in keys.split(",") if part.strip()]
    if not parts:
        raise BridgeError("Missing hotkey keys.")

    modifiers: list[str] = []
    key: str | None = None
    for part in parts:
        modifier = MODIFIERS.get(part)
        if modifier:
            if modifier not in modifiers:
                modifiers.append(modifier)
            continue
        if key is not None:
            raise BridgeError("Hotkey must contain one non-modifier key.")
        key = part

    if key is None:
        raise BridgeError("Hotkey must contain a non-modifier key.")

    using = f" using {{{', '.join(modifiers)}}}" if modifiers else ""
    if key in SPECIAL_KEY_CODES:
        action = f"key code {SPECIAL_KEY_CODES[key]}{using}"
    elif len(key) == 1:
        action = f"keystroke {applescript_string(key)}{using}"
    else:
        raise BridgeError(f"Unsupported hotkey key: {key}")

    repeat = clamp_repeat(repeat)
    osascript(f'tell application "System Events"\n{repeat_script(action, repeat)}\nend tell', timeout=10)
    return {"hotkey": parts, "repeat": repeat}


def frontmost_app() -> str:
    require_macos()
    return osascript(
        'tell application "System Events" to get name of first application process whose frontmost is true',
        timeout=5,
    ).strip()


def safe_frontmost_app() -> str | None:
    try:
        return frontmost_app()
    except Exception:
        return None


def read_text_arg(args: argparse.Namespace) -> str:
    if args.stdin:
        return sys.stdin.read()
    if args.text is None:
        raise BridgeError("Provide --text or --stdin.")
    return args.text


def run(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"{command[0]} failed."
        raise BridgeError(detail)
    return result


def osascript(script: str, *, timeout: float) -> str:
    result = run(["osascript", "-e", script], timeout=timeout)
    return result.stdout


def applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def clean_required(value: str, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise BridgeError(f"Missing {label}.")
    return cleaned


def clamp_repeat(repeat: int) -> int:
    return max(1, min(int(repeat or 1), 50))


def repeat_script(action: str, repeat: int) -> str:
    if repeat <= 1:
        return f"    {action}"
    return f"    repeat {repeat} times\n        {action}\n    end repeat"


def require_macos() -> None:
    if sys.platform != "darwin":
        raise BridgeError("Native computer use is only available on macOS.")


def summarize_error(exc: Exception) -> str:
    raw = str(exc).strip()
    if not raw:
        return "Native computer-use command failed."
    if (
        "not authorized to send Apple events" in raw
        or "not allowed assistive access" in raw
        or "assistive access" in raw
        or "Not authorized" in raw
    ):
        return (
            "macOS blocked automation. Grant Accessibility and Automation permission "
            "to Hermes Studio or the launching terminal."
        )
    if "Screen capture" in raw or "screencapture" in raw:
        return f"{raw} Grant Screen Recording permission to Hermes Studio or the launching terminal."
    return raw[:1000]


def print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
