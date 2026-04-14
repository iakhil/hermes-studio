import asyncio
import os
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.services.hermes import (
    ensure_hermes_python_path,
    redact,
    resolve_hermes_executable,
    studio_env,
)

router = APIRouter()


class ChatRunRequest(BaseModel):
    content: str


class AgentSession:
    """Manages a chat session with the hermes agent."""

    def __init__(self, ws: WebSocket | None):
        self.ws = ws
        self.session_id = str(uuid.uuid4())
        self.conversation: list[dict] = []
        self._interrupt = False
        self.events: list[dict] = []

    async def send(self, msg: dict):
        if self.ws is not None:
            await self.ws.send_json(msg)
        else:
            self.events.append(msg)

    async def handle_message(self, content: str):
        """Process a user message and stream the response."""
        self.conversation.append({"role": "user", "content": content})
        self._interrupt = False

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
        _set_studio_process_env()

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

        def on_tool_start(*args):
            if len(args) >= 3:
                tool_id = str(args[0] or uuid.uuid4())[:16]
                tool_name = str(args[1] or "")
                tool_args = args[2] if isinstance(args[2], dict) else {}
            else:
                tool_id = str(uuid.uuid4())[:8]
                tool_name = str(args[0] if args else "")
                tool_args = args[1] if len(args) > 1 and isinstance(args[1], dict) else {}
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

        def on_tool_complete(*args):
            if len(args) >= 4:
                tool_id = str(args[0] or "")[:16]
                tool_name = str(args[1] or "")
                result = str(args[3] or "")
                duration_ms = 0
            else:
                tool_id = str(args[0] or "")[:16] if args else str(uuid.uuid4())[:8]
                tool_name = ""
                result = str(args[1] or "") if len(args) > 1 else ""
                duration_ms = int(args[2] or 0) if len(args) > 2 else 0
            asyncio.run_coroutine_threadsafe(
                self.send({
                    "type": "tool_complete",
                    "id": tool_id,
                    "name": tool_name,
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

    async def _run_with_cli(self, content: str) -> Optional[str]:
        """Run hermes via CLI subprocess with sanitized streaming."""
        await self.send({"type": "status", "message": "Running Hermes..."})
        migration_error = await _migrate_legacy_openai_provider()
        if migration_error:
            await self.send({"type": "error", "message": migration_error})
            await self.send({"type": "done", "usage": None})
            return None

        env = _set_studio_process_env()
        hermes = resolve_hermes_executable() or "hermes"
        process = await asyncio.create_subprocess_exec(
            hermes, "chat", "-Q", "-q", content,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
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


@router.post("/api/v1/chat/run")
async def run_chat_command(req: ChatRunRequest) -> dict:
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="No message content provided.")

    session = AgentSession(None)
    await session.handle_message(content)

    response = "".join(
        str(event.get("text") or "")
        for event in session.events
        if event.get("type") == "delta"
    ).strip()
    errors = [
        str(event.get("message") or "")
        for event in session.events
        if event.get("type") == "error" and event.get("message")
    ]
    return {
        "session_id": session.session_id,
        "response": response,
        "error": "\n".join(errors).strip() or None,
        "events": session.events,
    }


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
    ensure_hermes_python_path()


def _studio_backend_path() -> Path:
    return Path(__file__).resolve().parents[2]


def _set_studio_process_env() -> dict[str, str]:
    backend_path = str(_studio_backend_path())
    os.environ["HERMES_STUDIO_BACKEND_PATH"] = backend_path
    existing = os.environ.get("PYTHONPATH", "")
    paths = [part for part in existing.split(os.pathsep) if part]
    if backend_path not in paths:
        os.environ["PYTHONPATH"] = os.pathsep.join([backend_path, *paths])
    return studio_env()


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

    hermes = resolve_hermes_executable() or "hermes"
    commands = [
        [hermes, "config", "set", "model.provider", "custom"],
        [hermes, "config", "set", "model.base_url", "https://api.openai.com/v1"],
        [hermes, "config", "set", "model.api_mode", "codex_responses"],
    ]
    for cmd in commands:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=studio_env(),
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

    bridge_url = "http://127.0.0.1:8420/api/v1/computer-use/native"
    lines = [
        "You are running inside Hermes Studio, a desktop GUI for controlling the user's Mac.",
        "For any computer-use request, act through tools and visible UI state. Do not merely describe what the user could do.",
        "Native macOS apps are in scope. Web apps are out of scope unless the user explicitly asks for a website. Do not replace a native app request with a browser version of that app.",
        "Use the generic native bridge below as the default for native macOS apps. AppleScript/JXA is allowed for generic OS automation or when a visible UI path is unavailable and the app has a real scripting dictionary. Do not invent app commands such as WhatsApp send/contact APIs.",
        "Use Accessibility/UI scripting for apps without scripting support, including WhatsApp. If System Events is not authorized, stop and ask the user to grant Accessibility permission.",
        "For browser-only requests, use browser_navigate first, then observe with browser_snapshot or browser_vision, then click/type/press/scroll as needed.",
        "For irreversible or externally visible actions such as sending messages, sending email, posting to social media, calling someone, buying something, deleting data, or changing account settings, prepare the draft/action but ask for explicit confirmation before the final submit/send/post/call click.",
        "If a requested local action needs a permission, dependency, login, or visible UI element that is missing, say exactly what is missing and what the user should enable.",
    ]
    if "browser" in enabled_toolsets:
        lines.append("The browser toolset is enabled, but use it only for explicit website/browser tasks.")
    if "terminal" in enabled_toolsets:
        lines.append("The terminal toolset is enabled for local command, AppleScript, and native app automation tasks.")
        lines.extend([
            "Hermes Studio provides a generic native macOS computer-use bridge through the local backend. Use curl from the terminal tool for native app tasks instead of app-specific shortcuts:",
            f"curl -sS -X POST {bridge_url}/status",
            f"curl -sS -X POST {bridge_url}/observe",
            f'curl -sS -X POST {bridge_url}/open-app -H "Content-Type: application/json" -d \'{{"name":"Notes"}}\'',
            f'curl -sS -X POST {bridge_url}/click -H "Content-Type: application/json" -d \'{{"x":500,"y":300}}\'',
            f'curl -sS -X POST {bridge_url}/paste -H "Content-Type: application/json" -d \'{{"text":"text to insert"}}\'',
            f'curl -sS -X POST {bridge_url}/hotkey -H "Content-Type: application/json" -d \'{{"keys":"command,n"}}\'',
            f'curl -sS -X POST {bridge_url}/press -H "Content-Type: application/json" -d \'{{"key":"return"}}\'',
            f'curl -sS -X POST {bridge_url}/scroll -H "Content-Type: application/json" -d \'{{"direction":"down","amount":2}}\'',
            "For native UI tasks, loop until the visible UI reflects the goal: observe, call vision_analyze with image_url set to the returned screenshot_path when needed, perform one or two bridge actions, then observe again.",
            "Use paste for generated prose, email drafts, notes, and messages. For multi-line text, send the full text in the JSON text field. Use click coordinates only after observing the screen or analyzing a screenshot.",
            "Do not stop after opening an app when the user asked you to write, search, draft, schedule, or change something inside it.",
        ])
    return "\n".join(lines)
