import asyncio
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
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app.services.hermes import HermesConfig, studio_env, studio_path

router = APIRouter(prefix="/voice")


class TtsConfigRequest(BaseModel):
    provider: str | None = None
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    mlx_model: str | None = None


class SpeakRequest(BaseModel):
    text: str
    provider: str | None = None


class SttInstallRequest(BaseModel):
    engine: str = "whisper.cpp"
    model: str = "base.en"


WHISPER_CPP_MODELS: dict[str, dict[str, str]] = {
    "base.en": {
        "name": "Base English",
        "filename": "ggml-base.en.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin",
        "detail": "Recommended balance for voice commands.",
    },
    "tiny.en": {
        "name": "Tiny English",
        "filename": "ggml-tiny.en.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin",
        "detail": "Fastest local model. Good for quick commands.",
    },
    "small.en": {
        "name": "Small English",
        "filename": "ggml-small.en.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin",
        "detail": "More accurate, slower, and a larger download.",
    },
}


@router.get("/status")
async def voice_status() -> dict[str, Any]:
    engines = _engine_status()
    configured = next((engine for engine in engines if engine["available"]), None)
    return {
        "configured": configured is not None,
        "active_engine": configured["id"] if configured else None,
        "engines": engines,
        "install_options": _stt_install_options(),
        "recording": {
            "format": "m4a/mp4 or webm/opus",
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


@router.post("/stt/install")
async def install_stt(req: SttInstallRequest) -> StreamingResponse:
    async def stream_install():
        async for line in _install_stt_stream(req):
            yield f"data: {line}\n\n"

    return StreamingResponse(stream_install(), media_type="text/event-stream")


def _engine_status() -> list[dict[str, Any]]:
    whisper_cpp_path = _whisper_cpp_binary()
    whisper_cpp_model = _whisper_cpp_model_path()
    mlx_python = _external_python_with_module("mlx_whisper")
    faster_python = _external_python_with_module("faster_whisper")
    return [
        {
            "id": "mlx-whisper",
            "name": "MLX Whisper",
            "available": importlib.util.find_spec("mlx_whisper") is not None or mlx_python is not None,
            "detail": (
                "Apple Silicon local Whisper via MLX."
                if mlx_python is None
                else f"Apple Silicon local Whisper via {mlx_python}."
            ),
            "install_hint": "python3 -m pip install mlx-whisper",
        },
        {
            "id": "faster-whisper",
            "name": "faster-whisper",
            "available": importlib.util.find_spec("faster_whisper") is not None or faster_python is not None,
            "detail": (
                "Local Whisper runtime. Uses CPU on any Mac and can use accelerated backends when installed."
                if faster_python is None
                else f"Local Whisper runtime via {faster_python}."
            ),
            "install_hint": "python3 -m pip install faster-whisper",
        },
        {
            "id": "whisper.cpp",
            "name": "whisper.cpp",
            "available": bool(whisper_cpp_path and whisper_cpp_model),
            "detail": (
                f"Native local speech-to-text at {whisper_cpp_path}."
                if whisper_cpp_path and whisper_cpp_model
                else "Native local speech-to-text for packaged Hermes Studio."
            ),
            "install_hint": "Use Setup to install local voice.",
        },
    ]


def _transcribe_local(audio_path: Path) -> tuple[str, str]:
    preferred = os.getenv("HERMES_STUDIO_STT_ENGINE", "auto").strip().lower()
    engines = ["mlx-whisper", "faster-whisper", "whisper.cpp"]
    # Earlier setup builds pinned whisper.cpp. Prefer MLX/faster-whisper when
    # they exist because that matches the dev backend and is much more usable.
    if preferred and preferred not in {"auto", "whisper.cpp"}:
        engines = [preferred, *[engine for engine in engines if engine != preferred]]

    errors: list[str] = []
    attempted: list[str] = []
    for engine in engines:
        try:
            if engine == "mlx-whisper" and _mlx_whisper_available():
                attempted.append(engine)
                return _transcribe_mlx(audio_path), "mlx-whisper"
            if engine == "faster-whisper" and _faster_whisper_available():
                attempted.append(engine)
                return _transcribe_faster_whisper(audio_path), "faster-whisper"
            if engine == "whisper.cpp":
                if _whisper_cpp_available():
                    attempted.append(engine)
                    return _transcribe_whisper_cpp(audio_path), "whisper.cpp"
        except Exception as exc:
            errors.append(f"{engine}: {exc}")

    if attempted:
        hint = "Local speech-to-text was available, but it could not decode this recording."
    else:
        hint = (
            "No local speech-to-text engine is available. Install one of: "
            "python3 -m pip install faster-whisper, python3 -m pip install mlx-whisper, "
            "or brew install whisper-cpp with WHISPER_CPP_MODEL set."
        )
    if errors:
        hint += " Last errors: " + " | ".join(errors[-3:])
    raise RuntimeError(hint)


def _whisper_cpp_available() -> bool:
    binary = _whisper_cpp_binary()
    model = _whisper_cpp_model_path()
    return bool(binary and model)


def _transcribe_mlx(audio_path: Path) -> str:
    if importlib.util.find_spec("mlx_whisper") is None:
        return _transcribe_mlx_external(audio_path)

    mlx_whisper = importlib.import_module("mlx_whisper")

    model = os.getenv("MLX_WHISPER_MODEL", "mlx-community/whisper-base.en-mlx")
    result = mlx_whisper.transcribe(str(audio_path), path_or_hf_repo=model)
    return str(result.get("text", "") if isinstance(result, dict) else result)


def _transcribe_faster_whisper(audio_path: Path) -> str:
    if importlib.util.find_spec("faster_whisper") is None:
        return _transcribe_faster_whisper_external(audio_path)

    faster_whisper = importlib.import_module("faster_whisper")

    model_size = os.getenv("FASTER_WHISPER_MODEL", "base.en")
    device = os.getenv("FASTER_WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8")
    model = faster_whisper.WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, _info = model.transcribe(str(audio_path), beam_size=1, vad_filter=False)
    return " ".join(segment.text.strip() for segment in segments).strip()


def _mlx_whisper_available() -> bool:
    return importlib.util.find_spec("mlx_whisper") is not None or _external_python_with_module("mlx_whisper") is not None


def _faster_whisper_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None or _external_python_with_module("faster_whisper") is not None


def _external_python_with_module(module: str) -> str | None:
    for executable in _python_candidates():
        result = subprocess.run(
            [
                executable,
                "-c",
                f"import importlib.util, sys; sys.exit(0 if importlib.util.find_spec({module!r}) else 1)",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            env=studio_env(),
        )
        if result.returncode == 0:
            return executable
    return None


def _python_candidates() -> list[str]:
    candidates = [
        os.getenv("HERMES_STUDIO_VOICE_PYTHON", "").strip(),
        shutil.which("python3", path=studio_path()) or "",
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
    ]
    framework_dir = Path("/Library/Frameworks/Python.framework/Versions")
    if framework_dir.exists():
        candidates.extend(
            str(path)
            for path in sorted(framework_dir.glob("*/bin/python3"), reverse=True)
        )
    result: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in result and Path(candidate).exists():
            result.append(candidate)
    return result


def _transcribe_mlx_external(audio_path: Path) -> str:
    python = _external_python_with_module("mlx_whisper")
    if not python:
        raise RuntimeError("mlx-whisper is not available to the packaged app.")

    model = os.getenv("MLX_WHISPER_MODEL", "mlx-community/whisper-base.en-mlx")
    script = (
        "import mlx_whisper, sys; "
        "result = mlx_whisper.transcribe(sys.argv[1], path_or_hf_repo=sys.argv[2]); "
        "print(result.get('text', '') if isinstance(result, dict) else result)"
    )
    return _run_external_transcriber([python, "-c", script, str(audio_path), model])


def _transcribe_faster_whisper_external(audio_path: Path) -> str:
    python = _external_python_with_module("faster_whisper")
    if not python:
        raise RuntimeError("faster-whisper is not available to the packaged app.")

    model_size = os.getenv("FASTER_WHISPER_MODEL", "base.en")
    device = os.getenv("FASTER_WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8")
    script = (
        "from faster_whisper import WhisperModel; import sys; "
        "model = WhisperModel(sys.argv[2], device=sys.argv[3], compute_type=sys.argv[4]); "
        "segments, _ = model.transcribe(sys.argv[1], beam_size=1, vad_filter=False); "
        "print(' '.join(segment.text.strip() for segment in segments).strip())"
    )
    return _run_external_transcriber([python, "-c", script, str(audio_path), model_size, device, compute_type])


def _run_external_transcriber(command: list[str]) -> str:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=180,
        env=studio_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:500] or "External speech-to-text failed.")
    return result.stdout.strip()


def _transcribe_whisper_cpp(audio_path: Path) -> str:
    binary = _whisper_cpp_binary()
    model = _whisper_cpp_model_path()
    if not binary or not model:
        raise RuntimeError("whisper.cpp needs whisper-cli and WHISPER_CPP_MODEL.")

    prepared_audio = _prepare_audio_for_whisper_cpp(audio_path)
    try:
        result = subprocess.run(
            [binary, "-m", model, "-f", str(prepared_audio), "-nt", "-np"],
            capture_output=True,
            text=True,
            timeout=120,
            env=studio_env(),
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip()[:500] or "whisper.cpp failed.")
        return result.stdout.strip()
    finally:
        if prepared_audio != audio_path:
            try:
                prepared_audio.unlink(missing_ok=True)
            except OSError:
                pass


def _whisper_cpp_binary() -> str | None:
    path = studio_path()
    return (
        shutil.which("whisper-cli", path=path)
        or shutil.which("whisper-cpp", path=path)
        or shutil.which("main", path=path)
    )


def _whisper_cpp_model_path() -> str:
    configured = _env_value("WHISPER_CPP_MODEL", "").strip()
    if configured and Path(configured).expanduser().exists():
        return str(Path(configured).expanduser())
    default_path = _default_whisper_cpp_model_path("base.en")
    return str(default_path) if default_path.exists() else ""


def _default_whisper_cpp_model_path(model_id: str) -> Path:
    info = WHISPER_CPP_MODELS.get(model_id, WHISPER_CPP_MODELS["base.en"])
    return HermesConfig().home / "models" / "whisper.cpp" / info["filename"]


def _prepare_audio_for_whisper_cpp(audio_path: Path) -> Path:
    if audio_path.suffix.lower() == ".wav":
        return audio_path

    wav_path = audio_path.with_suffix(".wav")
    if shutil.which("afconvert"):
        result = subprocess.run(
            [
                "afconvert",
                "-f",
                "WAVE",
                "-d",
                "LEI16@16000",
                str(audio_path),
                str(wav_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and wav_path.exists() and wav_path.stat().st_size > 0:
            return wav_path

    ffmpeg = shutil.which("ffmpeg", path=studio_path())
    if ffmpeg:
        result = subprocess.run(
            [ffmpeg, "-y", "-i", str(audio_path), "-ar", "16000", "-ac", "1", str(wav_path)],
            capture_output=True,
            text=True,
            timeout=30,
            env=studio_env(),
        )
        if result.returncode == 0 and wav_path.exists() and wav_path.stat().st_size > 0:
            return wav_path

    raise RuntimeError("Could not convert this recording to WAV for whisper.cpp.")


def _stt_install_options() -> list[dict[str, str]]:
    return [
        {"id": model_id, **info}
        for model_id, info in WHISPER_CPP_MODELS.items()
    ]


async def _install_stt_stream(req: SttInstallRequest):
    if req.engine != "whisper.cpp":
        yield "[ERROR] Hermes Studio can only auto-install whisper.cpp right now."
        return
    if sys.platform != "darwin":
        yield "[ERROR] Automatic local voice setup is currently macOS-only."
        return

    model_id = req.model if req.model in WHISPER_CPP_MODELS else "base.en"
    model_info = WHISPER_CPP_MODELS[model_id]
    model_path = _default_whisper_cpp_model_path(model_id)

    binary = _whisper_cpp_binary()
    if binary:
        yield f"Found whisper.cpp at {binary}."
    else:
        brew = shutil.which("brew", path=studio_path())
        if not brew:
            yield "[ERROR] Homebrew was not found. Install Homebrew first, then return here to install local voice."
            return
        yield "Installing whisper.cpp with Homebrew..."
        process = await asyncio.create_subprocess_exec(
            brew,
            "install",
            "whisper-cpp",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=studio_env(),
        )
        if process.stdout:
            async for raw_line in process.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    yield line[:500]
        await process.wait()
        if process.returncode != 0:
            yield f"[ERROR] Homebrew could not install whisper.cpp. Exit code {process.returncode}."
            return
        binary = _whisper_cpp_binary()
        if not binary:
            yield "[ERROR] whisper.cpp installed, but whisper-cli was not found on PATH."
            return
        yield f"Installed whisper.cpp at {binary}."

    model_path.parent.mkdir(parents=True, exist_ok=True)
    if model_path.exists() and model_path.stat().st_size > 1024 * 1024:
        yield f"Found local model at {model_path}."
    else:
        yield f"Downloading {model_info['name']} model..."
        tmp_path = model_path.with_suffix(model_path.suffix + ".part")
        try:
            async for line in _download_model(model_info["url"], tmp_path, model_path):
                yield line
        except RuntimeError as exc:
            yield f"[ERROR] {exc}"
            return
        yield f"Saved model at {model_path}."

    updates = {
        "HERMES_STUDIO_STT_ENGINE": "whisper.cpp",
        "WHISPER_CPP_MODEL": str(model_path),
    }
    HermesConfig().write_env_values(updates)
    os.environ.update(updates)
    yield "Local voice is configured."
    yield "[DONE]"


async def _download_model(url: str, tmp_path: Path, final_path: Path):
    last_reported_mb = -1
    bytes_written = 0
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
            async with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise RuntimeError(f"Model download failed with HTTP {response.status_code}.")
                total = int(response.headers.get("content-length") or 0)
                with tmp_path.open("wb") as out:
                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue
                        out.write(chunk)
                        bytes_written += len(chunk)
                        current_mb = bytes_written // (1024 * 1024)
                        if current_mb >= last_reported_mb + 25:
                            last_reported_mb = current_mb
                            if total:
                                yield f"Downloaded {current_mb} MB of {total // (1024 * 1024)} MB."
                            else:
                                yield f"Downloaded {current_mb} MB."
    except Exception as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(str(exc)[:500]) from exc

    if bytes_written < 1024 * 1024:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError("Downloaded model file was unexpectedly small.")
    tmp_path.replace(final_path)


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
