import asyncio
import subprocess
import time
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.models.ws_messages import (
    ConfigureProviderRequest,
    ModelInfo,
    ProviderInfo,
    SelectModelRequest,
    TestConnectionResponse,
)
from app.services.hermes import (
    OPENAI_BASE_URL,
    OPENAI_GATEWAY_DEFAULT_MODEL,
    resolve_hermes_executable,
    studio_env,
)

router = APIRouter(prefix="/setup")

PROVIDERS = [
    ProviderInfo(
        id="openrouter",
        name="OpenRouter",
        description="Access 200+ models from a single API. Most popular choice.",
        requires_key=True,
        icon="openrouter",
    ),
    ProviderInfo(
        id="openai",
        name="OpenAI",
        description="Direct OpenAI API through Hermes' custom OpenAI-compatible provider.",
        requires_key=True,
        icon="openai",
    ),
    ProviderInfo(
        id="anthropic",
        name="Anthropic",
        description="Claude 4.6, Claude 4.5 Sonnet, and other Claude models.",
        requires_key=True,
        icon="anthropic",
    ),
    ProviderInfo(
        id="nous",
        name="Nous Research",
        description="Nous Portal with Hermes models. Free tier available.",
        requires_key=True,
        icon="nous",
    ),
    ProviderInfo(
        id="ollama",
        name="Ollama (Local)",
        description="Run models locally. No API key needed.",
        requires_key=False,
        icon="ollama",
    ),
]

# Common models per provider (subset for setup wizard)
PROVIDER_MODELS: dict[str, list[ModelInfo]] = {
    "openrouter": [
        ModelInfo(id="nousresearch/hermes-3-llama-3.1-405b", name="Hermes 3 405B", provider="openrouter", context_length=131072),
        ModelInfo(id="anthropic/claude-sonnet-4-6", name="Claude Sonnet 4.6", provider="openrouter", context_length=200000),
        ModelInfo(id="openai/gpt-4o", name="GPT-4o", provider="openrouter", context_length=128000),
        ModelInfo(id="google/gemini-2.5-pro-preview", name="Gemini 2.5 Pro", provider="openrouter", context_length=1000000),
        ModelInfo(id="deepseek/deepseek-r1", name="DeepSeek R1", provider="openrouter", context_length=65536),
    ],
    "openai": [
        ModelInfo(id="gpt-5.4-mini", name="GPT-5.4 Mini", provider="openai", context_length=400000),
        ModelInfo(id="gpt-5.4", name="GPT-5.4", provider="openai", context_length=400000),
        ModelInfo(id="gpt-5.4-pro", name="GPT-5.4 Pro", provider="openai", context_length=400000),
        ModelInfo(id="gpt-5.4-nano", name="GPT-5.4 Nano", provider="openai", context_length=400000),
    ],
    "anthropic": [
        ModelInfo(id="claude-opus-4-6", name="Claude Opus 4.6", provider="anthropic", context_length=200000),
        ModelInfo(id="claude-sonnet-4-6", name="Claude Sonnet 4.6", provider="anthropic", context_length=200000),
        ModelInfo(id="claude-haiku-4-5-20251001", name="Claude Haiku 4.5", provider="anthropic", context_length=200000),
    ],
    "nous": [
        ModelInfo(id="hermes-3-llama-3.1-405b", name="Hermes 3 405B", provider="nous", context_length=131072),
        ModelInfo(id="hermes-3-llama-3.1-70b", name="Hermes 3 70B", provider="nous", context_length=131072),
        ModelInfo(id="deephermes-3-llama-3.3-70b", name="DeepHermes 3 70B", provider="nous", context_length=131072),
    ],
    "ollama": [
        ModelInfo(id="hermes3:latest", name="Hermes 3", provider="ollama"),
        ModelInfo(id="llama3.1:latest", name="Llama 3.1", provider="ollama"),
        ModelInfo(id="mistral:latest", name="Mistral", provider="ollama"),
        ModelInfo(id="codellama:latest", name="Code Llama", provider="ollama"),
    ],
}


@router.get("/check-install")
async def check_install():
    hermes_path = resolve_hermes_executable()
    if not hermes_path:
        return {"installed": False}
    try:
        result = subprocess.run(
            [hermes_path, "--version"], capture_output=True, text=True, timeout=5, env=studio_env()
        )
        return {
            "installed": True,
            "version": result.stdout.strip() if result.returncode == 0 else "unknown",
        }
    except Exception:
        return {"installed": False}


@router.post("/install")
async def install_hermes():
    """Run the hermes-agent install script, streaming output line by line."""

    async def stream_install():
        if resolve_hermes_executable():
            yield "data: Hermes Agent is already installed.\n\n"
            yield "data: [DONE]\n\n"
            return

        process = await asyncio.create_subprocess_exec(
            "bash", "-c",
            "curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=studio_env(),
        )

        if process.stdout:
            async for line in process.stdout:
                text = line.decode("utf-8", errors="replace")
                yield f"data: {text}\n\n"

        await process.wait()

        if process.returncode == 0:
            yield "data: [DONE]\n\n"
        else:
            yield f"data: [ERROR] Install failed with exit code {process.returncode}\n\n"

    return StreamingResponse(stream_install(), media_type="text/event-stream")


@router.get("/providers", response_model=list[ProviderInfo])
async def get_providers():
    providers = []
    for p in PROVIDERS:
        provider = p.model_copy()
        # Check if this provider is already configured
        try:
            from hermes_cli.config import load_config
            config = load_config()
            if config.get("provider") == p.id:
                provider.configured = True
        except Exception:
            pass
        providers.append(provider)
    return providers


@router.get("/models", response_model=list[ModelInfo])
async def get_models(provider: str = Query(...)):
    return PROVIDER_MODELS.get(provider, [])


@router.post("/configure-provider")
async def configure_provider(req: ConfigureProviderRequest):
    provider = _hermes_provider(req.provider)
    try:
        from hermes_cli.config import load_config, save_config
        config = load_config()
        model = config.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            config["model"] = model
        model["provider"] = provider
        if req.provider == "openai":
            model["base_url"] = OPENAI_BASE_URL
            model["api_mode"] = "codex_responses"
            if not _is_openai_reasoning_model(model.get("default")):
                model["default"] = OPENAI_GATEWAY_DEFAULT_MODEL
        if req.api_key:
            from hermes_cli.config import save_env_value
            env_key = _provider_env_key(provider)
            if env_key:
                save_env_value(env_key, req.api_key)
        if req.base_url:
            model["base_url"] = req.base_url
        save_config(config)
        return {"success": True}
    except ImportError:
        # Hermes not installed as library — fall back to CLI
        try:
            hermes = resolve_hermes_executable() or "hermes"
            result = subprocess.run(
                [hermes, "config", "set", "model.provider", provider],
                capture_output=True,
                text=True,
                timeout=10,
                env=studio_env(),
            )
            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()[:500] or result.stdout.strip()[:500]}
            if req.provider == "openai":
                for key, value in [
                    ("model.base_url", OPENAI_BASE_URL),
                    ("model.api_mode", "codex_responses"),
                    ("model.default", OPENAI_GATEWAY_DEFAULT_MODEL),
                ]:
                    result = subprocess.run(
                        [hermes, "config", "set", key, value],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        env=studio_env(),
                    )
                    if result.returncode != 0:
                        return {"success": False, "error": result.stderr.strip()[:500] or result.stdout.strip()[:500]}
            if req.api_key:
                from app.services.hermes import HermesConfig
                env_key = _provider_env_key(provider)
                if env_key:
                    HermesConfig().write_env_values({env_key: req.api_key})
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}


@router.post("/select-model")
async def select_model(req: SelectModelRequest):
    selected_model = _gateway_safe_model(req.model_id, req.provider)
    try:
        from hermes_cli.config import load_config, save_config
        config = load_config()
        model = config.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            config["model"] = model
        model["default"] = selected_model
        inferred_provider = _infer_provider_from_model(selected_model, req.provider)
        if inferred_provider:
            model["provider"] = inferred_provider
            if inferred_provider == "openrouter":
                from hermes_constants import OPENROUTER_BASE_URL
                model["base_url"] = OPENROUTER_BASE_URL
                model["api_mode"] = "chat_completions"
            elif req.provider == "openai":
                model["base_url"] = OPENAI_BASE_URL
                model["api_mode"] = "codex_responses"
                if not _is_openai_reasoning_model(model.get("default")):
                    model["default"] = OPENAI_GATEWAY_DEFAULT_MODEL
        save_config(config)
        return {"success": True}
    except ImportError:
        try:
            hermes = resolve_hermes_executable() or "hermes"
            result = subprocess.run(
                [hermes, "config", "set", "model.default", selected_model],
                capture_output=True, text=True, timeout=10,
                env=studio_env(),
            )
            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()[:500] or result.stdout.strip()[:500]}
            inferred_provider = _infer_provider_from_model(selected_model, req.provider)
            if inferred_provider:
                result = subprocess.run(
                    [hermes, "config", "set", "model.provider", inferred_provider],
                    capture_output=True, text=True, timeout=10,
                    env=studio_env(),
                )
                if result.returncode != 0:
                    return {"success": False, "error": result.stderr.strip()[:500] or result.stdout.strip()[:500]}
                if req.provider == "openai":
                    for key, value in [
                        ("model.base_url", OPENAI_BASE_URL),
                        ("model.api_mode", "codex_responses"),
                    ]:
                        result = subprocess.run(
                            [hermes, "config", "set", key, value],
                            capture_output=True, text=True, timeout=10,
                            env=studio_env(),
                        )
                        if result.returncode != 0:
                            return {"success": False, "error": result.stderr.strip()[:500] or result.stdout.strip()[:500]}
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_connection():
    try:
        start = time.time()
        hermes = resolve_hermes_executable() or "hermes"
        result = subprocess.run(
            [hermes, "chat", "-q", "Say 'Hello from Hermes!' and nothing else."],
            capture_output=True,
            text=True,
            timeout=30,
            env=studio_env(),
        )
        latency = int((time.time() - start) * 1000)

        if result.returncode == 0:
            return TestConnectionResponse(
                success=True,
                response=result.stdout.strip()[:200],
                latency_ms=latency,
            )
        else:
            return TestConnectionResponse(
                success=False,
                error=result.stderr.strip()[:200] or "Connection failed",
            )
    except subprocess.TimeoutExpired:
        return TestConnectionResponse(success=False, error="Connection timed out (30s)")
    except FileNotFoundError:
        return TestConnectionResponse(success=False, error="hermes command not found")
    except Exception as e:
        return TestConnectionResponse(success=False, error=str(e))


def _provider_env_key(provider: str) -> str | None:
    return {
        "openrouter": "OPENROUTER_API_KEY",
        "custom": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "nous": "NOUS_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }.get(provider)


def _infer_provider_from_model(model_id: str, selected_provider: str | None = None) -> str | None:
    if selected_provider:
        return _hermes_provider(selected_provider)
    if "/" in model_id:
        return "openrouter"
    return None


def _hermes_provider(provider: str) -> str:
    return "custom" if provider == "openai" else provider


def _is_openai_reasoning_model(model: str | None) -> bool:
    normalized = str(model or "").strip().lower()
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    return normalized.startswith("gpt-5")


def _gateway_safe_model(model_id: str, provider: str | None) -> str:
    if provider == "openai" and not _is_openai_reasoning_model(model_id):
        return OPENAI_GATEWAY_DEFAULT_MODEL
    return model_id
