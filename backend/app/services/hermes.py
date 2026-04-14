import asyncio
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_GATEWAY_DEFAULT_MODEL = "gpt-5.4-mini"
OPENAI_REASONING_MODEL_PREFIXES = ("gpt-5",)

SECRET_PATTERNS = [
    re.compile(r"([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*=)([^\s]+)", re.I),
    re.compile(r"(\b\d{6,}:[A-Za-z0-9_-]{20,}\b)"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{12,})\b"),
]

USER_BIN_PATHS = (
    Path.home() / ".local" / "bin",
    Path.home() / ".cargo" / "bin",
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path("/usr/bin"),
    Path("/bin"),
)


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()


def studio_path() -> str:
    existing = [part for part in os.environ.get("PATH", "").split(os.pathsep) if part]
    paths: list[str] = []
    for path in [*existing, *(str(path) for path in USER_BIN_PATHS)]:
        if path and path not in paths:
            paths.append(path)
    return os.pathsep.join(paths)


def studio_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {**os.environ, **(extra or {})}
    env["PATH"] = studio_path()
    return env


def resolve_hermes_executable() -> str | None:
    return shutil.which("hermes", path=studio_path())


def ensure_hermes_python_path() -> None:
    candidates = [
        Path(os.environ.get("HERMES_AGENT_PATH", "")).expanduser() if os.environ.get("HERMES_AGENT_PATH") else None,
        hermes_home() / "hermes-agent",
        Path.home() / ".hermes" / "hermes-agent",
    ]
    for candidate in candidates:
        if candidate and (candidate / "run_agent.py").exists():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)
            return


def redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.groups >= 2:
            redacted = pattern.sub(r"\1[redacted]", redacted)
        else:
            redacted = pattern.sub("[redacted]", redacted)
    return redacted


class CommandResult(dict):
    @property
    def success(self) -> bool:
        return bool(self.get("success"))


class HermesCommand:
    def __init__(self, executable: str = "hermes"):
        self.executable = executable

    def installed(self) -> bool:
        return self._resolved_executable() is not None

    def run(self, args: list[str], timeout: int = 30, env: dict[str, str] | None = None) -> CommandResult:
        start = time.time()
        executable = self._resolved_executable()
        if not executable:
            return CommandResult(
                success=False,
                returncode=127,
                stdout="",
                stderr="hermes command not found",
                duration_ms=int((time.time() - start) * 1000),
            )
        try:
            result = subprocess.run(
                [executable, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=studio_env(env),
            )
            return CommandResult(
                success=result.returncode == 0,
                returncode=result.returncode,
                stdout=redact(result.stdout),
                stderr=redact(result.stderr),
                duration_ms=int((time.time() - start) * 1000),
            )
        except FileNotFoundError:
            return CommandResult(
                success=False,
                returncode=127,
                stdout="",
                stderr="hermes command not found",
                duration_ms=int((time.time() - start) * 1000),
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                success=False,
                returncode=124,
                stdout=redact(exc.stdout or ""),
                stderr=f"Command timed out after {timeout}s",
                duration_ms=int((time.time() - start) * 1000),
            )

    def _resolved_executable(self) -> str | None:
        if self.executable == "hermes":
            return resolve_hermes_executable()
        return shutil.which(self.executable, path=studio_path()) or self.executable


class HermesConfig:
    def __init__(self, home: Path | None = None):
        self.home = home or hermes_home()
        self.env_path = self.home / ".env"

    def read_env(self) -> dict[str, str]:
        if not self.env_path.exists():
            return {}

        values: dict[str, str] = {}
        for raw_line in self.env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
        return values

    def write_env_values(self, updates: dict[str, str | None]) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        existing = self.env_path.read_text().splitlines() if self.env_path.exists() else []
        seen: set[str] = set()
        next_lines: list[str] = []

        for raw_line in existing:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                next_lines.append(raw_line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                seen.add(key)
                value = updates[key]
                if value is not None:
                    next_lines.append(f"{key}={_quote_env(value)}")
            else:
                next_lines.append(raw_line)

        for key, value in updates.items():
            if key not in seen and value is not None:
                next_lines.append(f"{key}={_quote_env(value)}")

        self.env_path.write_text("\n".join(next_lines).rstrip() + "\n")
        try:
            self.env_path.chmod(0o600)
        except OSError:
            pass

    def current(self) -> dict[str, Any]:
        try:
            ensure_hermes_python_path()
            from hermes_cli.config import load_config

            config = load_config()
            return dict(config)
        except Exception:
            return {}

    def normalize_openai_gateway_config(self) -> list[str]:
        """Make direct OpenAI configs compatible with Hermes' gateway path.

        Hermes' gateway uses the Responses API for direct OpenAI endpoints and,
        when reasoning is enabled, requests encrypted reasoning content. Older
        GPT-4/o-series models reject that include. Studio uses a GPT-5.4 model
        for direct OpenAI gateway runs so Telegram/WhatsApp do not fail at the
        first model call.
        """
        try:
            ensure_hermes_python_path()
            from hermes_cli.config import load_config, save_config

            config = load_config()
            model = config.get("model")
            if not isinstance(model, dict):
                return []

            if not _is_direct_openai_model_config(model):
                return []

            changes: list[str] = []
            current_model = str(model.get("default") or "").strip()
            if not _is_openai_reasoning_model(current_model):
                model["default"] = OPENAI_GATEWAY_DEFAULT_MODEL
                changes.append(
                    f"Updated OpenAI model from {current_model or 'unset'} to {OPENAI_GATEWAY_DEFAULT_MODEL} for gateway compatibility."
                )

            if model.get("provider") != "custom":
                model["provider"] = "custom"
                changes.append("Stored OpenAI as Hermes custom provider.")
            if str(model.get("base_url") or "").rstrip("/") != OPENAI_BASE_URL:
                model["base_url"] = OPENAI_BASE_URL
                changes.append("Set OpenAI base URL.")
            if model.get("api_mode") != "codex_responses":
                model["api_mode"] = "codex_responses"
                changes.append("Set OpenAI API mode to Responses.")

            if changes:
                save_config(config)
            return changes
        except Exception as exc:
            return [f"Could not normalize OpenAI gateway config: {redact(str(exc))[:300]}"]


def _quote_env(value: str) -> str:
    if re.search(r"\s|#|'|\"", value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


class HermesDoctor:
    def __init__(self, command: HermesCommand | None = None, config: HermesConfig | None = None):
        self.command = command or HermesCommand()
        self.config = config or HermesConfig()

    def summary(self) -> dict[str, Any]:
        installed = self.command.installed()
        version_result = self.command.run(["--version"], timeout=5) if installed else None
        config = self.config.current() if installed else {}
        model = config.get("model")
        current_model = model.get("default") if isinstance(model, dict) else model
        current_provider = model.get("provider") if isinstance(model, dict) else config.get("provider")
        env_values = self.config.read_env()

        checks = [
            {
                "id": "hermes",
                "label": "Hermes CLI",
                "ok": installed,
                "detail": version_result.get("stdout", "").strip() if version_result else "Install Hermes Agent first.",
                "action": "Install Hermes Agent" if not installed else None,
            },
            {
                "id": "model",
                "label": "Model selected",
                "ok": bool(current_model),
                "detail": current_model or "Choose a provider and model in Setup.",
                "action": "Open Setup" if not current_model else None,
            },
            {
                "id": "provider",
                "label": "Provider configured",
                "ok": bool(current_provider),
                "detail": current_provider or "Choose an LLM provider in Setup.",
                "action": "Open Setup" if not current_provider else None,
            },
            {
                "id": "telegram",
                "label": "Telegram token",
                "ok": bool(env_values.get("TELEGRAM_BOT_TOKEN")),
                "detail": "Token stored in ~/.hermes/.env" if env_values.get("TELEGRAM_BOT_TOKEN") else "Add a BotFather token to connect your phone.",
                "action": "Open Connections" if not env_values.get("TELEGRAM_BOT_TOKEN") else None,
            },
        ]

        if installed:
            doctor_result = self.command.run(["doctor"], timeout=20)
        else:
            doctor_result = CommandResult(success=False, stdout="", stderr="Hermes is not installed.", duration_ms=0)

        return {
            "installed": installed,
            "version": version_result.get("stdout", "").strip() if version_result else None,
            "configured": bool(current_model),
            "current_model": current_model,
            "current_provider": current_provider,
            "checks": checks,
            "doctor": doctor_result,
        }


class HermesTools:
    PRESETS = {
        "computer_use": {
            "id": "computer_use",
            "name": "Computer Use",
            "description": "Browser, terminal, screen understanding, files, memory, voice, and scheduling.",
            "required": ["browser", "terminal", "vision", "file"],
            "recommended": ["memory", "tts", "cronjob", "web"],
        },
        "phone_agent": {
            "id": "phone_agent",
            "name": "Phone Agent",
            "description": "Keep Hermes useful from Telegram or WhatsApp.",
            "required": ["memory", "session_search", "skills"],
            "recommended": ["tts", "cronjob", "web", "file"],
        },
    }

    def __init__(self, command: HermesCommand | None = None):
        self.command = command or HermesCommand()

    def apply_preset(self, preset_id: str, platform: str = "cli") -> dict[str, Any]:
        preset = self.PRESETS.get(preset_id)
        if not preset:
            return {"success": False, "error": f"Unknown preset: {preset_id}"}

        results = []
        for tool in [*preset["required"], *preset["recommended"]]:
            results.append({"tool": tool, **self.command.run(["tools", "enable", tool, "--platform", platform], timeout=10)})

        return {
            "success": all(r["success"] for r in results),
            "preset": preset,
            "results": results,
        }


class GatewayProcess:
    def __init__(self, command: str = "hermes"):
        self.command = command
        self.process: asyncio.subprocess.Process | None = None
        self.logs: list[str] = []

    def status(self) -> dict[str, Any]:
        running = self.process is not None and self.process.returncode is None
        return {
            "running": running,
            "pid": self.process.pid if running and self.process else None,
            "logs": self.logs[-200:],
        }

    async def start(self) -> dict[str, Any]:
        if self.process is not None and self.process.returncode is None:
            return self.status()

        executable = resolve_hermes_executable()
        if not executable:
            self.logs.append("hermes command not found")
            return self.status()

        self.logs = []
        for line in HermesConfig().normalize_openai_gateway_config():
            self.logs.append(line)
        self.process = await asyncio.create_subprocess_exec(
            executable,
            "gateway",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=studio_env(),
        )
        asyncio.create_task(self._collect_logs(self.process))
        self.logs.append(f"Started hermes gateway with pid {self.process.pid}")
        return self.status()

    async def stop(self) -> dict[str, Any]:
        if self.process is None or self.process.returncode is not None:
            return self.status()

        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=8)
        except asyncio.TimeoutError:
            self.process.kill()
            await self.process.wait()
        self.logs.append("Stopped hermes gateway")
        return self.status()

    async def _collect_logs(self, process: asyncio.subprocess.Process) -> None:
        if not process.stdout:
            return
        async for raw_line in process.stdout:
            self.logs.append(redact(raw_line.decode("utf-8", errors="replace")).rstrip())
            self.logs = self.logs[-500:]
        await process.wait()
        self.logs.append(f"Gateway exited with code {process.returncode}")


gateway_process = GatewayProcess()


def _is_direct_openai_model_config(model: dict[str, Any]) -> bool:
    provider = str(model.get("provider") or "").strip().lower()
    base_url = str(model.get("base_url") or "").strip().lower().rstrip("/")
    return provider == "custom" and "api.openai.com" in base_url and "openrouter" not in base_url


def _is_openai_reasoning_model(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    return normalized.startswith(OPENAI_REASONING_MODEL_PREFIXES)
