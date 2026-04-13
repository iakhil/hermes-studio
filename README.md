<div align="center">

# Hermes Studio

### Control Hermes Agent from your desktop, voice, and phone

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab.svg)](https://www.python.org)
[![React 19](https://img.shields.io/badge/react-19-61dafb.svg)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/fastapi-0.115+-009688.svg)](https://fastapi.tiangolo.com)

**Hermes Studio** is the missing setup and control plane for [Hermes Agent](https://github.com/NousResearch/hermes-agent). It turns Hermes' CLI-first power into guided flows for computer-use, model setup, tool presets, and persistent phone access.

</div>

## Why

Hermes can already browse, use tools, remember context, schedule work, and connect to messaging platforms. The hard part is getting all of that configured without living in terminal docs.

Hermes Studio focuses on the high-value path:

1. Install or verify Hermes Agent.
2. Configure your model provider.
3. Enable the Computer Use preset.
4. Connect Telegram so your agent is reachable from your phone.
5. Chat or speak to Hermes while it works through native apps, browser, terminal, files, memory, and scheduled tasks.

## Current Features

- Guided Hermes install and provider setup.
- Web chat with streamed agent responses.
- Computer Use preset for native app automation, browser, terminal, vision, files, memory, TTS, web, and cron tools.
- Generic native macOS computer-use bridge for screen observation, app launching, clicks, keys, and text entry.
- Optional live Chrome connection for explicit website control through Hermes browser tools.
- macOS permission checklist for local computer-use workflows.
- Native macOS shell scaffold with Accessibility status checks and deep links to Privacy & Security panes.
- Telegram configuration with token and allowed-user storage in `~/.hermes/.env`.
- Gateway start/stop controls with live logs.
- Raw tool manager for enabling and disabling Hermes toolsets.
- Local voice input for computer-use commands through on-device STT engines.

## Quick Start

Prerequisites:

- macOS, Linux, or WSL2
- Node.js 20+
- Python 3.11+
- Hermes Agent, or let Hermes Studio install it

```bash
git clone https://github.com/YOUR_USERNAME/hermes-studio.git
cd hermes-studio
make install
make dev
```

Open [http://localhost:5173](http://localhost:5173).

The backend runs on `127.0.0.1:8420`; Vite proxies API and websocket traffic during development.

## Local Voice

Hermes Studio records microphone audio in the app and sends it to the local backend for transcription. No hosted speech API is required when one of these local engines is installed:

```bash
# Good default on any Mac
python3 -m pip install faster-whisper

# Apple Silicon optimized option
python3 -m pip install mlx-whisper
```

Advanced users can also use `whisper.cpp`:

```bash
brew install whisper-cpp
export WHISPER_CPP_MODEL=/path/to/ggml-base.en.bin
```

Optional environment overrides:

- `HERMES_STUDIO_STT_ENGINE=mlx-whisper|faster-whisper|whisper.cpp|auto`
- `FASTER_WHISPER_MODEL=base.en`
- `MLX_WHISPER_MODEL=mlx-community/whisper-base.en-mlx`

Open **Computer Use** to see whether a local voice engine is ready. Use the mic button in Chat to record a command, transcribe it locally, and send it to Hermes.

In the macOS desktop app, hold **Option+Command** to record a voice command from anywhere in Hermes Studio. Release the keys to stop, transcribe locally, send the command to Hermes, and hear the response.

Talk-back uses the first available TTS engine:

```bash
# Apple Silicon local TTS
python3 -m pip install mlx-audio-plus

# Hosted fallback
export ELEVENLABS_API_KEY=...
```

Optional TTS overrides:

- `HERMES_STUDIO_TTS_PROVIDER=mlx-audio|elevenlabs|macos-say|auto`
- `MLX_AUDIO_TTS_MODEL=mlx-community/Kokoro-82M-bf16`
- `ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb`

## Computer Use

Computer Use keeps native app requests native. Hermes Studio exposes a general macOS computer-use bridge that lets Hermes observe the screen, open apps, click, press keys, paste generated text, and repeat until the requested state is visible. Commands like this should work without opening a browser:

```text
Open Notes and write a short poem.
```

macOS may ask for Automation or Accessibility permission the first time Hermes Studio controls an app.

For explicit website tasks, Studio can also connect Hermes browser tools to a visible Chrome session over the Chrome DevTools Protocol (CDP). That lets Hermes operate real websites through a persistent local profile:

- Gmail: open, compose, fill recipient/body, then ask before sending.
- X: open, draft a post, then ask before posting.
- WhatsApp Web: open, search a chat, draft a message, then ask before sending.

Open **Computer Use** and click **Connect Chrome** only when you want website control. Studio launches a separate persistent Chrome profile at `~/.hermes/studio-chrome-profile` with CDP on `127.0.0.1:9222`, then stores `BROWSER_CDP_URL` in `~/.hermes/.env` so Hermes browser tools use that visible session.

For authenticated sites, log in once inside that Chrome profile. Hermes should stop and ask when login, permissions, or human confirmation is needed.

## Native macOS App

Hermes Studio now includes a Tauri shell. It loads the existing React app while adding native macOS capabilities that a browser cannot provide.

```bash
npm install
cd frontend && npm install
cd ..
npm run desktop:dev
```

The native shell currently adds:

- Accessibility permission status checks.
- Shortcuts to Accessibility, Screen Recording, Microphone, and Automation settings.
- A path toward Keychain secrets, LaunchAgent persistence, menu bar controls, and a signed `.dmg`.

Rust is pinned in `rust-toolchain.toml` because current Tauri dependencies require Rust 1.88+.

## Apple Intelligence And Local Models

Apple's Foundation Models framework exposes the on-device language model behind Apple Intelligence to apps on supported systems. That can help Hermes Studio with lightweight local tasks such as intent routing, structured command extraction, safety classification, and deciding whether a request should go to Hermes or a cloud/local LLM.

It is not a full replacement for Hermes Agent:

- It is Swift-native, so it should live behind Tauri native commands or a small helper.
- It depends on Apple Intelligence availability and user settings.
- Its context window and model control are limited compared with dedicated agent backends.
- It cannot silently bypass macOS privacy permissions.

The practical path is to support multiple local intelligence layers:

- Apple Foundation Models for native on-device planning when available.
- Ollama or llama.cpp for heavier local models.
- Hermes Agent as the main tool-using runtime.

## First Run

1. Open **Setup** and configure Hermes.
2. Open **Computer Use** and click **Enable Preset**.
3. Grant macOS permissions when prompted by your terminal or browser automation stack.
4. Open **Connections**, save your Telegram bot token and allowed user ID, then start the gateway.
5. Message your bot on Telegram or use the web chat.

## Telegram Setup

1. Message [@BotFather](https://t.me/BotFather).
2. Create a bot with `/newbot`.
3. Paste the bot token into Hermes Studio.
4. Message [@userinfobot](https://t.me/userinfobot) to get your numeric Telegram user ID.
5. Add that ID to **Allowed Telegram user IDs**.
6. Start the gateway.

Hermes Agent supports Telegram text, voice memos, images, file attachments, and scheduled task delivery. Hermes Studio stores the required token and allowlist in your local Hermes environment file.

## WhatsApp Status

Hermes Agent supports WhatsApp through a Baileys-based bridge and QR pairing flow. Hermes Studio does not expose the WhatsApp pairing UI yet. Telegram is the first supported phone connection because it is safer, simpler, and uses official bot tokens.

## Architecture

```text
React/Vite frontend
        |
        | REST + WebSocket
        v
FastAPI backend
        |
        | service wrappers
        v
Hermes Agent CLI/config/gateway
        |
        v
LLM providers, tools, Telegram, local machine
```

Frontend:

- React 19
- Vite
- Tailwind CSS
- Zustand
- Framer Motion

Backend:

- FastAPI
- WebSockets
- Hermes CLI subprocess integration
- Local `~/.hermes` config and environment management

## Project Structure

```text
frontend/
  src/pages/              app screens
  src/components/         layout, chat, and UI components
  src/hooks/              websocket and voice hooks
  src/stores/             chat state
  src/lib/                API client and shared types

backend/
  app/routers/            REST and websocket routes
  app/services/           Hermes command, config, tools, gateway services
  app/models/             Pydantic schemas
```

## Development

```bash
make dev           # frontend + backend
make dev-frontend  # Vite only
make dev-backend   # FastAPI only
make build         # production frontend into backend/static
make clean         # remove build artifacts
```

## Docker

```bash
docker compose up
```

The container mounts `~/.hermes` so Hermes configuration and platform sessions persist.

## Roadmap

- [x] Web chat for Hermes
- [x] Guided model setup
- [x] Raw tool manager
- [x] Computer Use preset
- [x] Telegram config and gateway process controls
- [ ] Hermes doctor UI with actionable repair buttons
- [ ] Approval cards for risky tool calls
- [ ] Session history and search
- [ ] WhatsApp QR pairing UI
- [ ] Skills browser
- [ ] Memory editor
- [ ] Cron scheduler UI
- [ ] Tauri desktop app for macOS

## Security Notes

- API keys and bot tokens stay local in Hermes config files.
- Gateway logs are redacted before being returned to the browser.
- Telegram access should always be restricted with `TELEGRAM_ALLOWED_USERS`.
- WhatsApp sessions, once supported in the UI, must be treated like credentials.
- Computer-use features can operate your machine. Keep approval mode on unless you explicitly want unattended execution.

## Acknowledgments

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) by [Nous Research](https://nousresearch.com)
- [shadcn/ui](https://ui.shadcn.com)
- [Lucide](https://lucide.dev)

## License

[MIT](LICENSE)
