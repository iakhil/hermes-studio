import subprocess
from fastapi import APIRouter

from app.models.ws_messages import HealthResponse
from app.services.hermes import ensure_hermes_python_path, resolve_hermes_executable, studio_env

router = APIRouter()


def _check_hermes() -> tuple[bool, str | None]:
    """Check if hermes-agent is installed and get its version."""
    hermes_path = resolve_hermes_executable()
    if not hermes_path:
        return False, None
    try:
        result = subprocess.run(
            [hermes_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            env=studio_env(),
        )
        version = result.stdout.strip() if result.returncode == 0 else None
        return True, version
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, None


def _get_current_config() -> dict:
    """Try to read the current hermes configuration."""
    try:
        ensure_hermes_python_path()
        from hermes_cli.config import load_config
        config = load_config()
        model = config.get("model")
        current_model = model.get("default") if isinstance(model, dict) else model
        current_provider = model.get("provider") if isinstance(model, dict) else config.get("provider")
        return {
            "configured": bool(current_model),
            "current_model": current_model,
            "current_provider": current_provider,
        }
    except Exception:
        return {"configured": False, "current_model": None, "current_provider": None}


@router.get("/health", response_model=HealthResponse)
async def health_check():
    installed, version = _check_hermes()
    config_info = _get_current_config() if installed else {}
    return HealthResponse(
        hermes_installed=installed,
        hermes_version=version,
        **config_info,
    )
