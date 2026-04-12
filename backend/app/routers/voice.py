import importlib.util
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/voice")


@router.get("/status")
async def voice_status() -> dict[str, Any]:
    engines = _engine_status()
    configured = next((engine for engine in engines if engine["available"]), None)
    return {
        "configured": configured is not None,
        "active_engine": configured["id"] if configured else None,
        "engines": engines,
        "recording": {
            "format": "webm/opus",
            "privacy": "Audio is sent only to the local Hermes Studio backend.",
        },
    }


@router.post("/transcribe")
async def transcribe(request: Request) -> dict[str, Any]:
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="No audio data received.")

    suffix = _suffix_for_content_type(request.headers.get("content-type", ""))
    with tempfile.NamedTemporaryFile(prefix="hermes-studio-voice-", suffix=suffix, delete=False) as tmp:
        tmp.write(audio)
        audio_path = Path(tmp.name)

    started = time.time()
    try:
        transcript, engine = _transcribe_local(audio_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        try:
            audio_path.unlink(missing_ok=True)
        except OSError:
            pass

    return {
        "text": transcript.strip(),
        "engine": engine,
        "duration_ms": int((time.time() - started) * 1000),
    }


def _engine_status() -> list[dict[str, Any]]:
    whisper_cpp_path = (
        shutil.which("whisper-cli")
        or shutil.which("whisper-cpp")
        or shutil.which("main")
    )
    whisper_cpp_model = os.getenv("WHISPER_CPP_MODEL", "").strip()
    return [
        {
            "id": "mlx-whisper",
            "name": "MLX Whisper",
            "available": importlib.util.find_spec("mlx_whisper") is not None,
            "detail": "Apple Silicon local Whisper via MLX.",
            "install_hint": "python3 -m pip install mlx-whisper",
        },
        {
            "id": "faster-whisper",
            "name": "faster-whisper",
            "available": importlib.util.find_spec("faster_whisper") is not None,
            "detail": "Local Whisper runtime. Uses CPU on any Mac and can use accelerated backends when installed.",
            "install_hint": "python3 -m pip install faster-whisper",
        },
        {
            "id": "whisper.cpp",
            "name": "whisper.cpp",
            "available": bool(whisper_cpp_path and whisper_cpp_model),
            "detail": "Native local whisper.cpp binary. Requires WHISPER_CPP_MODEL to point at a .bin model.",
            "install_hint": "brew install whisper-cpp and set WHISPER_CPP_MODEL=/path/to/ggml-base.en.bin",
        },
    ]


def _transcribe_local(audio_path: Path) -> tuple[str, str]:
    preferred = os.getenv("HERMES_STUDIO_STT_ENGINE", "auto").strip().lower()
    engines = ["mlx-whisper", "faster-whisper", "whisper.cpp"]
    if preferred and preferred != "auto":
        engines = [preferred, *[engine for engine in engines if engine != preferred]]

    errors: list[str] = []
    for engine in engines:
        try:
            if engine == "mlx-whisper" and importlib.util.find_spec("mlx_whisper") is not None:
                return _transcribe_mlx(audio_path), "mlx-whisper"
            if engine == "faster-whisper" and importlib.util.find_spec("faster_whisper") is not None:
                return _transcribe_faster_whisper(audio_path), "faster-whisper"
            if engine == "whisper.cpp":
                return _transcribe_whisper_cpp(audio_path), "whisper.cpp"
        except Exception as exc:
            errors.append(f"{engine}: {exc}")

    hint = (
        "No local speech-to-text engine is available. Install one of: "
        "python3 -m pip install faster-whisper, python3 -m pip install mlx-whisper, "
        "or brew install whisper-cpp with WHISPER_CPP_MODEL set."
    )
    if errors:
        hint += " Last errors: " + " | ".join(errors[-3:])
    raise RuntimeError(hint)


def _transcribe_mlx(audio_path: Path) -> str:
    import mlx_whisper

    model = os.getenv("MLX_WHISPER_MODEL", "mlx-community/whisper-base.en-mlx")
    result = mlx_whisper.transcribe(str(audio_path), path_or_hf_repo=model)
    return str(result.get("text", "") if isinstance(result, dict) else result)


def _transcribe_faster_whisper(audio_path: Path) -> str:
    from faster_whisper import WhisperModel

    model_size = os.getenv("FASTER_WHISPER_MODEL", "base.en")
    device = os.getenv("FASTER_WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, _info = model.transcribe(str(audio_path), beam_size=1, vad_filter=False)
    return " ".join(segment.text.strip() for segment in segments).strip()


def _transcribe_whisper_cpp(audio_path: Path) -> str:
    binary = shutil.which("whisper-cli") or shutil.which("whisper-cpp") or shutil.which("main")
    model = os.getenv("WHISPER_CPP_MODEL", "").strip()
    if not binary or not model:
        raise RuntimeError("whisper.cpp needs whisper-cli and WHISPER_CPP_MODEL.")

    result = subprocess.run(
        [binary, "-m", model, "-f", str(audio_path), "-nt", "-np"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:500] or "whisper.cpp failed.")
    return result.stdout.strip()


def _suffix_for_content_type(content_type: str) -> str:
    content_type = content_type.lower()
    if "wav" in content_type:
        return ".wav"
    if "aiff" in content_type or "aif" in content_type:
        return ".aiff"
    if "mp4" in content_type or "m4a" in content_type:
        return ".m4a"
    if "ogg" in content_type:
        return ".ogg"
    return ".webm"
