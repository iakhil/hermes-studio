import asyncio
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.services.hermes import redact

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

        handled = await self._try_handle_native_mac_action(content)
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

    async def _try_handle_native_mac_action(self, content: str) -> Optional[str]:
        action = _native_action_from_prompt(content)
        if not action:
            return None

        tool_id = str(uuid.uuid4())[:8]
        await self.send({
            "type": "tool_start",
            "id": tool_id,
            "name": action["tool"],
            "args": action["args"],
        })
        try:
            result = await asyncio.to_thread(_run_native_action, action)
        except Exception as exc:
            message = _summarize_native_action_error(exc)
            await self.send({
                "type": "tool_complete",
                "id": tool_id,
                "name": action["tool"],
                "result": message,
                "duration_ms": 0,
            })
            await self.send({"type": "error", "message": message})
            await self.send({"type": "done", "usage": None})
            return message

        await self.send({
            "type": "tool_complete",
            "id": tool_id,
            "name": action["tool"],
            "result": result,
            "duration_ms": 0,
        })
        await self.send({"type": "delta", "text": result})
        await self.send({"type": "done", "usage": None})
        return result

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
        "For any computer-use request, act through tools and visible UI state. Do not merely describe what the user could do.",
        "Native macOS apps are in scope. Web apps are out of scope unless the user explicitly asks for a website. Do not replace a native app request with a browser version of that app.",
        "For native macOS apps, prefer AppleScript/JXA through the terminal tool only when an app has a real scripting dictionary for the requested action. Do not invent AppleScript commands such as WhatsApp send/contact APIs.",
        "Use Accessibility/UI scripting for apps without scripting support, including WhatsApp. If System Events is not authorized, stop and ask the user to grant Accessibility permission.",
        "For browser-only requests, use browser_navigate first, then observe with browser_snapshot or browser_vision, then click/type/press/scroll as needed.",
        "For irreversible or externally visible actions such as sending messages, sending email, posting to social media, calling someone, buying something, deleting data, or changing account settings, prepare the draft/action but ask for explicit confirmation before the final submit/send/post/call click.",
        "If a requested local action needs a permission, dependency, login, or visible UI element that is missing, say exactly what is missing and what the user should enable.",
    ]
    if "browser" in enabled_toolsets:
        lines.append("The browser toolset is enabled, but use it only for explicit website/browser tasks.")
    if "terminal" in enabled_toolsets:
        lines.append("The terminal toolset is enabled for local command, AppleScript, and native app automation tasks.")
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


def _native_action_from_prompt(content: str) -> dict | None:
    text = " ".join(str(content or "").strip().split())
    if not text:
        return None
    lowered = text.lower()

    if "notes" in lowered or "note app" in lowered or "notes app" in lowered:
        title = _extract_note_title(text)
        if title and any(phrase in lowered for phrase in ("create", "new note", "make", "add")):
            return {
                "tool": "native_notes_create_note",
                "args": {"title": title},
            }
    if "whatsapp" in lowered and any(phrase in lowered for phrase in ("text", "message", "send", "prepare", "draft")):
        draft = _extract_whatsapp_draft(text)
        if draft:
            return {
                "tool": "native_whatsapp_prepare_message",
                "args": draft,
            }
    return None


def _extract_note_title(text: str) -> str | None:
    patterns = [
        r"(?:called|named|titled)\s+['\"]([^'\"]+)['\"]",
        r"(?:called|named|titled)\s+(.+?)(?:\s+in\s+notes|\s+in\s+the\s+notes\s+app|$)",
        r"note\s+['\"]([^'\"]+)['\"]",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            title = match.group(1).strip(" .")
            if title:
                return title[:120]
    return None


def _run_native_action(action: dict) -> str:
    if action.get("tool") == "native_notes_create_note":
        title = str(action.get("args", {}).get("title") or "").strip()
        if not title:
            raise RuntimeError("Missing note title.")
        _create_notes_note(title)
        return f"Created a new note in Notes called \"{title}\"."
    if action.get("tool") == "native_whatsapp_prepare_message":
        args = action.get("args", {})
        recipient = str(args.get("recipient") or "").strip()
        message = str(args.get("message") or "").strip()
        if not recipient or not message:
            raise RuntimeError("Missing WhatsApp recipient or message.")
        _prepare_whatsapp_message(recipient, message)
        return f"Prepared a WhatsApp draft to {recipient}: \"{message}\". I did not send it."
    raise RuntimeError(f"Unsupported native action: {action.get('tool')}")


def _create_notes_note(title: str) -> None:
    escaped_title = _applescript_string(title)
    body = _applescript_string(f"<h1>{_html_escape(title)}</h1>")
    script = f'''
tell application "Notes"
    activate
    set noteTitle to {escaped_title}
    set noteBody to {body}
    try
        set targetFolder to folder "Notes" of default account
    on error
        set targetFolder to first folder of default account
    end try
    make new note at targetFolder with properties {{name:noteTitle, body:noteBody}}
end tell
'''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "Notes automation failed."
        raise RuntimeError(detail)


def _extract_whatsapp_draft(text: str) -> dict | None:
    normalized = " ".join(str(text or "").strip().split())
    patterns = [
        ("message_first", r"\b(?:send|text|message)\s+['\"]([^'\"]+)['\"]\s+to\s+(.+?)(?:\s+(?:on|in)\s+whatsapp|$)"),
        ("message_first", r"\b(?:send|text|message)\s+(.+?)\s+to\s+(.+?)(?:\s+(?:on|in)\s+whatsapp|$)"),
        ("recipient_first", r"\bprepare\s+(?:a\s+)?message\s+to\s+(.+?)\s+(?:saying|with)\s+['\"]([^'\"]+)['\"]"),
        ("recipient_first", r"\bprepare\s+(?:a\s+)?message\s+to\s+(.+?)\s+(?:saying|with)\s+(.+?)(?:\s+(?:on|in)\s+whatsapp|$)"),
        ("recipient_first", r"\b(?:text|message)\s+(.+?)\s+(?:saying|with)\s+['\"]([^'\"]+)['\"]"),
        ("recipient_first", r"\b(?:text|message)\s+(.+?)\s+(?:saying|with)\s+(.+?)(?:\s+(?:on|in)\s+whatsapp|$)"),
    ]
    for mode, pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        if mode == "message_first":
            message, recipient = match.group(1), match.group(2)
        else:
            recipient, message = match.group(1), match.group(2)
        recipient = _clean_contact_name(recipient)
        message = _clean_message_text(message)
        if recipient and message:
            return {"recipient": recipient[:120], "message": message[:1000]}
    compact_match = re.search(
        r"\b(?:open\s+whatsapp\s+and\s+)?(?:text|message)\s+((?!(?:to|saying|with)\b)[A-Za-z][\w .'-]*?)\s+(.+?)(?:\s+(?:on|in)\s+whatsapp|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if compact_match:
        recipient = _clean_contact_name(compact_match.group(1))
        message = _clean_message_text(compact_match.group(2))
        if recipient and message:
            return {"recipient": recipient[:120], "message": message[:1000]}
    return None


def _clean_contact_name(value: str) -> str:
    value = re.sub(r"^(?:open\s+whatsapp\s+and\s+)?", "", value.strip(), flags=re.IGNORECASE)
    value = re.sub(r"\s+(?:on|in)\s+whatsapp$", "", value, flags=re.IGNORECASE)
    return value.strip(" .'\"")


def _clean_message_text(value: str) -> str:
    value = re.sub(r"\s+(?:on|in)\s+whatsapp$", "", value.strip(), flags=re.IGNORECASE)
    return value.strip(" .'\"")


def _prepare_whatsapp_message(recipient: str, message: str) -> None:
    script = f'''
tell application "WhatsApp" to activate
delay 1.0
tell application "System Events"
    if not (exists process "WhatsApp") then error "WhatsApp is not running."
    tell process "WhatsApp"
        set frontmost to true
    end tell
    delay 0.4
    keystroke "f" using {{command down}}
    delay 0.3
    keystroke {_applescript_string(recipient)}
    delay 1.0
    key code 125
    key code 36
    delay 0.6
    keystroke {_applescript_string(message)}
end tell
'''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "WhatsApp automation failed."
        raise RuntimeError(detail)


def _applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _summarize_native_action_error(exc: Exception) -> str:
    raw = redact(str(exc))
    if (
        "not authorized to send Apple events" in raw
        or "Not authorized" in raw
        or "not allowed assistive access" in raw
        or "assistive access" in raw
    ):
        return (
            "Hermes Studio is not allowed to control native apps yet. Open macOS "
            "Privacy & Security > Accessibility and Automation, then allow Hermes Studio or the launching terminal."
        )
    if "Can’t get process \"WhatsApp\"" in raw or "WhatsApp is not running" in raw:
        return "Could not control WhatsApp. Make sure WhatsApp is installed, open, and logged in."
    if "Application isn’t running" in raw or "Can’t get application" in raw:
        return "Could not control the native app. Make sure the app is installed and try again."
    return f"Native app automation failed: {raw[:500]}"
