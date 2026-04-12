import asyncio
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.hermes import redact

router = APIRouter()


class AgentSession:
    """Manages a chat session with the hermes agent."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.session_id = str(uuid.uuid4())
        self.conversation: list[dict] = []
        self._interrupt = False

    async def send(self, msg: dict):
        await self.ws.send_json(msg)

    async def handle_message(self, content: str):
        """Process a user message and stream the response."""
        self.conversation.append({"role": "user", "content": content})
        self._interrupt = False

        handled = await self._try_handle_studio_computer_action(content)
        if handled:
            self.conversation.append({"role": "assistant", "content": handled})
            return

        try:
            response = await self._run_with_library(content)
        except (ImportError, ModuleNotFoundError) as exc:
            await self.send({
                "type": "status",
                "message": f"Python API unavailable, falling back to CLI: {type(exc).__name__}",
            })
            response = await self._run_with_cli(content)
        except Exception as exc:
            await self.send({"type": "error", "message": _summarize_hermes_error(str(exc), "")})
            await self.send({"type": "done", "usage": None})
            response = None

        if response:
            self.conversation.append({"role": "assistant", "content": response})

    async def _run_with_library(self, content: str) -> Optional[str]:
        """Run using hermes-agent Python API so terminal UI never reaches chat."""
        migration_error = await _migrate_legacy_openai_provider()
        if migration_error:
            await self.send({"type": "error", "message": migration_error})
            await self.send({"type": "done", "usage": None})
            return None

        _ensure_hermes_python_path()
        from run_agent import AIAgent
        from hermes_cli.env_loader import load_hermes_dotenv
        from hermes_cli.config import load_config
        from hermes_cli.runtime_provider import resolve_runtime_provider, format_runtime_provider_error

        hermes_home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
        load_hermes_dotenv(hermes_home=hermes_home)

        config = load_config()
        loop = asyncio.get_event_loop()
        accumulated_text = []

        def on_delta(text: str):
            if text is None:
                return
            accumulated_text.append(text)
            asyncio.run_coroutine_threadsafe(
                self.send({"type": "delta", "text": text}), loop
            )

        def on_tool_start(tool_name: str, tool_args: dict):
            tool_id = str(uuid.uuid4())[:8]
            asyncio.run_coroutine_threadsafe(
                self.send({
                    "type": "tool_start",
                    "id": tool_id,
                    "name": tool_name,
                    "args": tool_args,
                }),
                loop,
            )
            return tool_id

        def on_tool_complete(tool_id: str, result: str, duration_ms: int = 0):
            asyncio.run_coroutine_threadsafe(
                self.send({
                    "type": "tool_complete",
                    "id": tool_id,
                    "name": "",
                    "result": result[:2000],
                    "duration_ms": duration_ms,
                }),
                loop,
            )

        def on_thinking(text: str):
            asyncio.run_coroutine_threadsafe(
                self.send({"type": "thinking", "text": text}), loop
            )

        def on_status(text: str):
            asyncio.run_coroutine_threadsafe(
                self.send({"type": "status", "message": str(text)}), loop
            )

        try:
            runtime = resolve_runtime_provider()
        except Exception as exc:
            await self.send({"type": "error", "message": format_runtime_provider_error(exc)})
            await self.send({"type": "done", "usage": None})
            return None

        enabled_toolsets = _enabled_toolsets_for_platform(config, "cli")

        model_cfg = config.get("model")
        if isinstance(model_cfg, dict):
            model = runtime.get("model") or model_cfg.get("default") or ""
        else:
            model = runtime.get("model") or model_cfg or ""

        agent = AIAgent(
            model=model,
            base_url=runtime.get("base_url", ""),
            api_key=runtime.get("api_key", ""),
            provider=runtime.get("provider", ""),
            api_mode=runtime.get("api_mode", ""),
            reasoning_config=_reasoning_config_for_runtime(runtime, model),
            request_overrides=_request_overrides_for_runtime(runtime, model),
            enabled_toolsets=enabled_toolsets,
            ephemeral_system_prompt=_studio_system_prompt(enabled_toolsets),
            platform="cli",
            credential_pool=runtime.get("credential_pool"),
            quiet_mode=True,
            persist_session=True,
            stream_delta_callback=on_delta,
            tool_start_callback=on_tool_start,
            tool_complete_callback=on_tool_complete,
            thinking_callback=on_thinking,
            status_callback=on_status,
        )
        agent.suppress_status_output = True

        def run_agent():
            return agent.run_conversation(
                content,
                conversation_history=self.conversation[:-1],
            )

        result = await asyncio.to_thread(run_agent)
        final_response = result.get("final_response", "") if isinstance(result, dict) else str(result or "")
        if not accumulated_text and final_response:
            await self.send({"type": "delta", "text": final_response})
        if isinstance(result, dict) and result.get("failed"):
            await self.send({
                "type": "error",
                "message": final_response or "Hermes failed before returning a response.",
            })
        await self.send({"type": "done", "usage": None})
        return final_response or "".join(accumulated_text)

    async def _try_handle_studio_computer_action(self, content: str) -> Optional[str]:
        browser_target = _browser_target_from_prompt(content)
        if not browser_target:
            return None

        tool_id = str(uuid.uuid4())[:8]
        await self.send({
            "type": "tool_start",
            "id": tool_id,
            "name": "open_browser",
            "args": {"url": browser_target},
        })
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["open", browser_target],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except Exception as exc:
            message = (
                "I could not open the browser from Hermes Studio. "
                f"macOS returned: {_summarize_hermes_error(str(exc), '')}"
            )
            await self.send({
                "type": "tool_complete",
                "id": tool_id,
                "name": "open_browser",
                "result": message,
                "duration_ms": 0,
            })
            await self.send({"type": "error", "message": message})
            await self.send({"type": "done", "usage": None})
            return message

        message = f"Opened your browser to {browser_target}."
        await self.send({
            "type": "tool_complete",
            "id": tool_id,
            "name": "open_browser",
            "result": message,
            "duration_ms": 0,
        })
        await self.send({"type": "delta", "text": message})
        await self.send({"type": "done", "usage": None})
        return message

    async def _run_with_cli(self, content: str) -> Optional[str]:
        """Run hermes via CLI subprocess with sanitized streaming."""
        await self.send({"type": "status", "message": "Running Hermes..."})
        migration_error = await _migrate_legacy_openai_provider()
        if migration_error:
            await self.send({"type": "error", "message": migration_error})
            await self.send({"type": "done", "usage": None})
            return None

        process = await asyncio.create_subprocess_exec(
            "hermes", "chat", "-Q", "-q", content,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        full_response: list[str] = []
        stderr_chunks: list[str] = []

        async def read_stdout():
            if not process.stdout:
                return
            while True:
                if self._interrupt:
                    process.terminate()
                    await self.send({"type": "status", "message": "Interrupted"})
                    break
                chunk = await process.stdout.read(512)
                if not chunk:
                    break
                text = _clean_cli_output(chunk.decode("utf-8", errors="replace"))
                if text:
                    full_response.append(text)

        async def read_stderr():
            if not process.stderr:
                return
            while True:
                chunk = await process.stderr.read(512)
                if not chunk:
                    break
                stderr_chunks.append(chunk.decode("utf-8", errors="replace"))

        await asyncio.gather(read_stdout(), read_stderr())
        await process.wait()

        stdout_text = "".join(full_response)
        response_text = _extract_cli_response(stdout_text)

        if process.returncode != 0:
            error_text = _summarize_hermes_error("".join(stderr_chunks), stdout_text)
            await self.send({"type": "error", "message": error_text})
        elif response_text:
            await self.send({"type": "delta", "text": response_text})
        elif stderr_chunks:
            error_text = _summarize_hermes_error("".join(stderr_chunks), "")
            if error_text:
                await self.send({"type": "error", "message": error_text})
        else:
            await self.send({
                "type": "error",
                "message": (
                    "Hermes completed but returned no final text response. "
                    "Check the selected model/provider in Setup and run the connection test."
                ),
            })

        await self.send({"type": "done", "usage": None})
        return response_text

    def interrupt(self):
        self._interrupt = True


@router.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    await ws.accept()
    session = AgentSession(ws)

    await session.send({
        "type": "connected",
        "session_id": session.session_id,
        "model": _get_current_model(),
    })

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "message":
                await session.handle_message(data["content"])
            elif msg_type == "interrupt":
                session.interrupt()
            elif msg_type == "new_conversation":
                session.conversation.clear()
                await session.send({"type": "status", "message": "New conversation started"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await session.send({"type": "error", "message": str(e)})
        except Exception:
            pass


def _get_current_model() -> str:
    try:
        _ensure_hermes_python_path()
        from hermes_cli.config import load_config
        config = load_config()
        model = config.get("model")
        if isinstance(model, dict):
            return model.get("default") or "not configured"
        return model or "not configured"
    except Exception:
        return "not configured"


def _ensure_hermes_python_path() -> None:
    candidates = [
        Path(os.environ.get("HERMES_AGENT_PATH", "")).expanduser() if os.environ.get("HERMES_AGENT_PATH") else None,
        Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser() / "hermes-agent",
        Path.home() / ".hermes" / "hermes-agent",
    ]
    for candidate in candidates:
        if candidate and (candidate / "run_agent.py").exists():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)
            return


def _clean_cli_output(text: str) -> str:
    # Strip ANSI escape sequences and common box-drawing splash characters.
    import re

    text = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", text)
    text = text.replace("\r", "\n")
    return text


def _extract_cli_response(stdout: str) -> str:
    text = _clean_cli_output(stdout)
    if not text.strip():
        return ""

    # `hermes chat -Q` prints the final answer followed by parseable metadata:
    #   <answer>
    #   session_id: 2026...
    # The metadata is not assistant content.
    import re
    text = re.split(r"(?im)^\s*session_id\s*:", text, maxsplit=1)[0]
    if not text.strip():
        return ""

    # Quiet mode should usually return only the answer. If a terminal banner or
    # rich layout leaks through, drop known CLI chrome and keep human text.
    lines = [line.rstrip() for line in text.splitlines()]
    filtered: list[str] = []
    skip_tokens = (
        "Hermes Agent v",
        "Available Tools",
        "Available Skills",
        "Session:",
        "Query:",
        "Initializing agent",
        "Goodbye!",
        "commands",
        "tools ·",
        "skills ·",
        "session_id:",
    )
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if filtered and filtered[-1] != "":
                filtered.append("")
            continue
        if any(token in stripped for token in skip_tokens):
            continue
        # Drop box drawing / splash-art heavy lines.
        non_ascii = sum(1 for ch in stripped if ord(ch) > 127)
        if non_ascii > max(8, len(stripped) // 3):
            continue
        if set(stripped) <= set("╭╮╰╯─│┌┐└┘├┤┬┴┼━┃ "):
            continue
        filtered.append(stripped)

    response = "\n".join(filtered).strip()
    # Do not return standalone diagnostics as assistant content.
    diagnostic_markers = (
        "Failed to initialize",
        "SQLite session store",
        "resolve_provider_client",
        "Operation not permitted",
    )
    if any(marker in response for marker in diagnostic_markers):
        return ""
    return response


def _summarize_hermes_error(stderr: str, stdout: str) -> str:
    raw = redact("\n".join(part for part in [stderr, stdout] if part).strip())
    if not raw:
        return "Hermes exited without a response."

    if "unknown provider 'openai'" in raw:
        return (
            "Hermes does not support provider 'openai' as a main provider in this version. "
            "Use Setup to save OpenAI again so Hermes Studio can store it as a custom OpenAI-compatible endpoint."
        )
    if "gpt-4o' model is not supported when using Codex" in raw or "gpt-4o model is not supported when using Codex" in raw:
        return (
            "The selected model is not supported by the ChatGPT-backed Codex provider. "
            "Choose an OpenAI Codex model, or switch to OpenRouter/Anthropic in Setup."
        )
    if "Encrypted content is not supported with this model" in raw:
        return (
            "OpenAI rejected Hermes' Responses request because the selected model does not "
            "support encrypted reasoning content. Hermes Studio now disables that option for "
            "direct OpenAI GPT-4/o-series models; restart the backend or app and try again."
        )
    if "Operation not permitted" in raw and ".hermes/logs/agent.log" in raw:
        return (
            "Hermes could not write to ~/.hermes/logs/agent.log. "
            "Launch Hermes Studio outside the sandbox or grant the app/terminal file access."
        )

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    signal_lines = [
        line for line in lines
        if "error" in line.lower() or "failed" in line.lower() or "unknown provider" in line.lower()
    ]
    selected = signal_lines[:4] or lines[-4:]
    return "\n".join(selected)[:1200]


async def _migrate_legacy_openai_provider() -> str | None:
    """Convert older Hermes Studio direct-OpenAI config to Hermes v0.8 shape."""
    try:
        from pathlib import Path

        config_path = Path.home() / ".hermes" / "config.yaml"
        text = config_path.read_text() if config_path.exists() else ""
        if "provider: openai" not in text:
            return None
    except Exception:
        return None

    commands = [
        ["hermes", "config", "set", "model.provider", "custom"],
        ["hermes", "config", "set", "model.base_url", "https://api.openai.com/v1"],
        ["hermes", "config", "set", "model.api_mode", "codex_responses"],
    ]
    for cmd in commands:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
            return (
                "Hermes Studio found an old OpenAI config but could not migrate it. "
                "Run these commands from Terminal:\n"
                "hermes config set model.provider custom\n"
                "hermes config set model.base_url https://api.openai.com/v1\n"
                "hermes config set model.api_mode codex_responses\n\n"
                f"Migration error: {redact(detail)[:500]}"
            )
    return None


def _reasoning_config_for_runtime(runtime: dict, model: str) -> dict | None:
    if _is_direct_openai_runtime(runtime) and not _model_requires_responses_api(model):
        return {"enabled": False}
    return None


def _request_overrides_for_runtime(runtime: dict, model: str) -> dict | None:
    if _is_direct_openai_runtime(runtime) and not _model_requires_responses_api(model):
        # Hermes' Responses path requests reasoning.encrypted_content by default.
        # GPT-4/o-series OpenAI API models reject that include, so omit it.
        return {"include": None}
    return None


def _is_direct_openai_runtime(runtime: dict) -> bool:
    base_url = str(runtime.get("base_url") or "").lower()
    provider = str(runtime.get("provider") or "").lower()
    return provider == "custom" and "api.openai.com" in base_url and "openrouter" not in base_url


def _model_requires_responses_api(model: str) -> bool:
    normalized = str(model or "").lower()
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    return normalized.startswith("gpt-5")


def _enabled_toolsets_for_platform(config: dict, platform: str) -> list[str] | None:
    try:
        from hermes_cli.tools_config import _get_platform_tools

        toolsets = sorted(_get_platform_tools(config, platform))
        return toolsets or None
    except Exception:
        return None


def _studio_system_prompt(enabled_toolsets: list[str] | None) -> str:
    if not enabled_toolsets:
        return ""

    lines = [
        "You are running inside Hermes Studio, a desktop GUI for controlling the user's Mac.",
        "When the user explicitly asks you to open, control, click, type in, inspect, or use an app, browser, terminal, file, calendar, music, FaceTime, or WhatsApp, perform the task with tools instead of only replying with information.",
        "For browser-control requests, call browser_navigate first and continue with browser_snapshot, browser_click, browser_type, browser_press, or browser_scroll as needed. Do not substitute web_search when the user asked to open or use the browser.",
        "If a requested local action needs a permission or dependency that is missing, say exactly what is missing and what the user should enable.",
    ]
    if "browser" in enabled_toolsets:
        lines.append("The browser toolset is enabled for this Studio session.")
    if "terminal" in enabled_toolsets:
        lines.append("The terminal toolset is enabled for local command and process tasks.")
    return "\n".join(lines)


def _browser_target_from_prompt(content: str) -> str | None:
    text = " ".join(str(content or "").strip().split())
    if not text:
        return None

    lowered = text.lower()
    browser_intent = any(
        phrase in lowered
        for phrase in (
            "open browser",
            "open the browser",
            "open chrome",
            "open safari",
            "open a browser",
            "launch browser",
            "launch the browser",
        )
    )
    if not browser_intent:
        return None

    url_match = re.search(r"https?://[^\s)>\]]+", text)
    if url_match:
        return url_match.group(0)

    domain_match = re.search(
        r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|io|ai|dev|app|co|news|edu|gov)(?:/[^\s]*)?",
        text,
        flags=re.IGNORECASE,
    )
    if domain_match:
        target = domain_match.group(0)
        return target if target.startswith(("http://", "https://")) else f"https://{target}"

    search_match = re.search(
        r"\b(?:search(?: for)?|look up|google)\s+(.+?)(?:\s+and\s+tell\b|$)",
        text,
        flags=re.IGNORECASE,
    )
    query = search_match.group(1).strip(" .") if search_match else ""
    if not query and "news" in lowered:
        query = "latest news"
    if not query:
        query = "news"

    return f"https://www.google.com/search?q={quote_plus(query)}"
