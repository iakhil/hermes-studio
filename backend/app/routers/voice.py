import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.services.hermes import HermesConfig

router = APIRouter(prefix="/voice")


class TtsConfigRequest(BaseModel):
    provider: str | None = None
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    mlx_model: str | None = None


class SpeakRequest(BaseModel):
    text: str
    provider: str | None = None


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


@router.get("/tts/status")
async def tts_status() -> dict[str, Any]:
    engines = _tts_engine_status()
    active = _selected_tts_engine(engines)
    return {
        "configured": active is not None,
        "active_engine": active["id"] if active else None,
        "engines": engines,
        "elevenlabs_configured": bool(_env_value("ELEVENLABS_API_KEY")),
        "privacy": "Local engines run on this Mac. ElevenLabs sends assistant text to ElevenLabs when selected.",
    }


@router.post("/tts/config")
async def configure_tts(req: TtsConfigRequest) -> dict[str, Any]:
    updates: dict[str, str | None] = {}
    if req.provider is not None:
        updates["HERMES_STUDIO_TTS_PROVIDER"] = req.provider.strip() or None
    if req.elevenlabs_api_key is not None:
        updates["ELEVENLABS_API_KEY"] = req.elevenlabs_api_key.strip() or None
    if req.elevenlabs_voice_id is not None:
        updates["ELEVENLABS_VOICE_ID"] = req.elevenlabs_voice_id.strip() or None
    if req.mlx_model is not None:
        updates["MLX_AUDIO_TTS_MODEL"] = req.mlx_model.strip() or None

    HermesConfig().write_env_values(updates)
    for key, value in updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    return await tts_status()


@router.post("/speak")
async def speak(req: SpeakRequest) -> Response:
    text = _clean_tts_text(req.text)
    if not text:
        raise HTTPException(status_code=400, detail="No text to speak.")

    try:
        audio, media_type, engine = _synthesize_speech(text, req.provider)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return Response(
        content=audio,
        media_type=media_type,
        headers={
            "X-Hermes-Voice-Engine": engine,
            "Cache-Control": "no-store",
        },
    )


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


def _tts_engine_status() -> list[dict[str, Any]]:
    return [
        {
            "id": "mlx-audio",
            "name": "MLX Audio",
            "available": importlib.util.find_spec("mlx_audio") is not None,
            "configured": importlib.util.find_spec("mlx_audio") is not None,
            "detail": "Local Apple Silicon TTS models through MLX.",
            "install_hint": "python3 -m pip install mlx-audio-plus",
        },
        {
            "id": "elevenlabs",
            "name": "ElevenLabs",
            "available": bool(_env_value("ELEVENLABS_API_KEY")),
            "configured": bool(_env_value("ELEVENLABS_API_KEY")),
            "detail": "Hosted high-quality voices. Requires ELEVENLABS_API_KEY.",
            "install_hint": "Add an ElevenLabs API key.",
        },
        {
            "id": "macos-say",
            "name": "macOS Say",
            "available": shutil.which("say") is not None,
            "configured": shutil.which("say") is not None,
            "detail": "Built-in local macOS speech fallback.",
            "install_hint": "Available by default on macOS.",
        },
    ]


def _selected_tts_engine(engines: list[dict[str, Any]]) -> dict[str, Any] | None:
    preferred = _env_value("HERMES_STUDIO_TTS_PROVIDER", "auto").strip().lower()
    if preferred and preferred != "auto":
        selected = next((engine for engine in engines if engine["id"] == preferred and engine["available"]), None)
        if selected:
            return selected
    return next((engine for engine in engines if engine["available"]), None)


def _synthesize_speech(text: str, requested_provider: str | None = None) -> tuple[bytes, str, str]:
    engines = ["mlx-audio", "elevenlabs", "macos-say"]
    preferred = (requested_provider or _env_value("HERMES_STUDIO_TTS_PROVIDER", "auto")).strip().lower()
    if preferred and preferred != "auto":
        engines = [preferred, *[engine for engine in engines if engine != preferred]]

    errors: list[str] = []
    for engine in engines:
        try:
            if engine == "mlx-audio" and importlib.util.find_spec("mlx_audio") is not None:
                return _synthesize_mlx_audio(text), "audio/wav", "mlx-audio"
            if engine == "elevenlabs" and _env_value("ELEVENLABS_API_KEY"):
                return _synthesize_elevenlabs(text), "audio/mpeg", "elevenlabs"
            if engine == "macos-say" and shutil.which("say"):
                return _synthesize_macos_say(text), "audio/aiff", "macos-say"
        except Exception as exc:
            errors.append(f"{engine}: {exc}")

    hint = (
        "No text-to-speech engine is available. Install MLX Audio with "
        "python3 -m pip install mlx-audio-plus, add ELEVENLABS_API_KEY, or run on macOS with the say command."
    )
    if errors:
        hint += " Last errors: " + " | ".join(errors[-3:])
    raise RuntimeError(hint)


def _synthesize_mlx_audio(text: str) -> bytes:
    model = _env_value("MLX_AUDIO_TTS_MODEL", "mlx-community/Kokoro-82M-bf16")
    voice = _env_value("MLX_AUDIO_TTS_VOICE", "af_heart")
    with tempfile.TemporaryDirectory(prefix="hermes-studio-tts-") as tmpdir:
        out_dir = Path(tmpdir)
        commands = [
            [
                sys.executable,
                "-m",
                "mlx_audio.tts.generate",
                "--model",
                model,
                "--voice",
                voice,
                "--text",
                text,
                "--output_path",
                str(out_dir),
            ],
            [
                "mlx-audio",
                "tts",
                "--model",
                model,
                "--voice",
                voice,
                "--text",
                text,
                "--output_path",
                str(out_dir),
            ],
        ]
        last_error = ""
        for command in commands:
            executable = command[0]
            if executable != sys.executable and shutil.which(executable) is None:
                continue
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            if result.returncode == 0:
                audio_path = _newest_audio_file(out_dir)
                if audio_path:
                    return audio_path.read_bytes()
            last_error = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(last_error[:500] or "MLX Audio did not create an audio file.")


def _synthesize_elevenlabs(text: str) -> bytes:
    api_key = _env_value("ELEVENLABS_API_KEY")
    voice_id = _env_value("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    model_id = _env_value("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
    output_format = _env_value("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured.")

    response = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        params={"output_format": output_format},
        headers={
            "xi-api-key": api_key,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        },
        json={
            "text": text,
            "model_id": model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(response.text[:500] or f"ElevenLabs returned HTTP {response.status_code}.")
    return response.content


def _synthesize_macos_say(text: str) -> bytes:
    with tempfile.NamedTemporaryFile(prefix="hermes-studio-say-", suffix=".aiff", delete=False) as tmp:
        out_path = Path(tmp.name)
    try:
        voice = _env_value("MACOS_SAY_VOICE", "")
        command = ["say", "-o", str(out_path)]
        if voice:
            command.extend(["-v", voice])
        command.append(text)
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip()[:500] or "macOS say failed.")
        return out_path.read_bytes()
    finally:
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass


def _newest_audio_file(directory: Path) -> Path | None:
    candidates = [
        path for path in directory.rglob("*")
        if path.suffix.lower() in {".wav", ".mp3", ".m4a", ".aiff", ".aif"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _env_value(key: str, default: str = "") -> str:
    value = os.getenv(key)
    if value is not None:
        return value.strip()
    return HermesConfig().read_env().get(key, default).strip()


def _clean_tts_text(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", "code block", str(text or ""))
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2000]
