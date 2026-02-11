# OpenClaw Voice Assistant

<p align="center">
  <strong>Real-time voice conversations for OpenClaw</strong>
</p>

<p align="center">
  <a href="#installation">Installation</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#api-reference">API Reference</a>
</p>

---

## Features

- 🎤 **Real-time Voice Chat** — Talk to your AI assistant in Discord voice channels
- 🔊 **High-Quality TTS** — Local (Piper) or cloud (ElevenLabs, OpenAI) text-to-speech
- 🎯 **Accurate STT** — faster-whisper or whisper.cpp for speech recognition
- 🔌 **OpenClaw Native** — Seamless integration as Gateway plugins
- ⚡ **Low Latency** — P50 < 1.0s end-to-end response time
- 🌐 **Multi-language** — Chinese and English support out of the box

## Installation

### One-liner Install (Linux/macOS)

```bash
curl -fsSL https://raw.githubusercontent.com/PPPPanda/openclaw-voice-assistant/main/scripts/install.sh | bash
```

### Manual Installation

#### Prerequisites

- Python 3.11+
- Node.js 20+
- FFmpeg (`apt install ffmpeg` / `brew install ffmpeg`)
- OpenClaw installed and configured
- CUDA Toolkit (optional, for GPU-accelerated STT)

#### Step 1: Clone Repository

```bash
git clone https://github.com/PPPPanda/openclaw-voice-assistant.git
cd openclaw-voice-assistant
```

#### Step 2: Install Speech Core Service

```bash
cd speech-core
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

#### Step 3: Install Gateway Plugins

```bash
# Speech Core Plugin
cd gateway-plugins/speech-core
npm install && npm run build

# Discord Voice Plugin
cd ../discord-voice
npm install && npm run build
```

#### Step 4: Configure Environment

```bash
cp .env.example .env
# Edit .env with your configuration
```

### npm Install (Coming Soon)

```bash
openclaw plugins install @openclaw/discord-voice-plugin
```

## Quick Start

### 1. Start Speech Core Service

```bash
cd speech-core
source .venv/bin/activate
python -m speech_core.server
```

The service will start at `ws://localhost:9001/speech`.

### 2. Configure OpenClaw

Add to your OpenClaw config (`~/.openclaw/config.yaml`):

```yaml
plugins:
  load:
    paths:
      - "/path/to/openclaw-voice-assistant/gateway-plugins/speech-core"
      - "/path/to/openclaw-voice-assistant/gateway-plugins/discord-voice"
  entries:
    speech-core:
      enabled: true
      config:
        endpoint: "ws://localhost:9001/speech"
    discord-voice:
      enabled: true
      config:
        botToken: "YOUR_DISCORD_BOT_TOKEN"
        guildId: "YOUR_DISCORD_GUILD_ID"
        # Optional: auto-join a voice channel on startup
        # defaultChannelId: "YOUR_VOICE_CHANNEL_ID"
```

### 3. Restart OpenClaw Gateway

```bash
openclaw gateway restart
```

### 4. Join a Voice Channel

Use the CLI:
```bash
openclaw voice join <channelId>
```

Or use the agent tool:
```
/voice_channel_join channel_id=123456789
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Transport Layer                          │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │ Discord Voice   │  │ Voice Message   │  (Future: WebRTC)│
│  │ Adapter         │  │ Adapter         │                  │
│  └────────┬────────┘  └────────┬────────┘                  │
└───────────┼────────────────────┼────────────────────────────┘
            │                    │
            └─────────┬──────────┘
                      │ PCM Audio / Events
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                  Speech Core Layer                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │   VAD   │→ │   STT   │→ │  Text   │→ │OpenClaw │        │
│  │ (Silero)│  │(Whisper)│  │         │  │ Gateway │        │
│  └─────────┘  └─────────┘  └─────────┘  └────┬────┘        │
│                                               │             │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐       │             │
│  │  Audio  │← │   TTS   │← │  Text   │←──────┘             │
│  │ Output  │  │ (Piper) │  │         │                     │
│  └─────────┘  └─────────┘  └─────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

### Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Speech Core** | Python, WebSocket | STT/TTS/VAD service |
| **speech-core-plugin** | TypeScript | Gateway RPC client |
| **discord-voice-plugin** | TypeScript | Discord voice adapter |
| **STT Engine** | faster-whisper | Speech-to-text |
| **TTS Engine** | Piper / ElevenLabs | Text-to-speech |
| **VAD** | Silero VAD | Voice activity detection |

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Speech Core
SPEECH_CORE_HOST=0.0.0.0
SPEECH_CORE_PORT=9001

# STT
STT_ENGINE=faster-whisper  # or whisper-cpp
STT_MODEL=base             # tiny, base, small, medium, large
STT_DEVICE=auto            # auto, cpu, cuda
STT_LANGUAGE=auto          # auto, zh, en, etc.

# TTS
TTS_ENGINE=piper           # piper, elevenlabs, openai
TTS_VOICE=zh_CN-huayan-medium

# Optional: ElevenLabs
ELEVENLABS_API_KEY=your_api_key
ELEVENLABS_VOICE_ID=your_voice_id

# Discord
DISCORD_BOT_TOKEN=your_bot_token
DISCORD_GUILD_ID=your_guild_id
```

### OpenClaw Plugin Config

```yaml
plugins:
  entries:
    speech-core:
      enabled: true
      config:
        endpoint: "ws://localhost:9001/speech"
        reconnectIntervalMs: 3000
        maxReconnectAttempts: 10
        healthCheckIntervalMs: 30000

    discord-voice:
      enabled: true
      config:
        botToken: "YOUR_BOT_TOKEN"
        guildId: "YOUR_GUILD_ID"
        speechCoreEndpoint: "ws://localhost:9001/speech"
        ttsProvider: "piper"  # piper, elevenlabs, openai
        sttLanguage: "auto"
```

## API Reference

### Gateway RPC Methods

| Method | Description |
|--------|-------------|
| `speech.stt` | Convert audio to text |
| `speech.tts` | Convert text to audio |
| `speech.status` | Get service status |
| `speech.models` | List available models |
| `voice.join` | Join a voice channel |
| `voice.leave` | Leave voice channel(s) |
| `voice.speak` | Speak text in channel |
| `voice.status` | Get voice plugin status |

### Agent Tools

| Tool | Description |
|------|-------------|
| `speech_to_text` | Convert audio to text |
| `text_to_speech` | Convert text to audio |
| `voice_channel_join` | Join a voice channel |
| `voice_channel_leave` | Leave voice channel(s) |
| `voice_speak` | Speak text in channel |
| `voice_status` | Get plugin status |

### CLI Commands

```bash
openclaw voice join <channelId>   # Join a voice channel
openclaw voice leave              # Leave all voice channels
openclaw voice status             # Show plugin status
```

See [docs/api-reference.md](docs/api-reference.md) for detailed API documentation.

## Performance

| Metric | Target (P50) | Target (P95) |
|--------|--------------|--------------|
| End-to-end latency | ≤ 1.0s | ≤ 2.0s |
| STT processing | 300ms | 500ms |
| TTS first byte | 200ms | 400ms |

## Roadmap

- [x] Phase 0: Voice message STT validation
- [x] Phase 1: Half-duplex voice chat (current)
- [ ] Phase 2: Plugin marketplace distribution
- [ ] Phase 3: Full-duplex with barge-in
- [ ] WebRTC support
- [ ] More platforms (Slack, Teams, etc.)

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) first.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Links

- [OpenClaw Documentation](https://docs.openclaw.ai)
- [Architecture Report](reports/openclaw-voice-architecture-report.md)
- [API Reference](docs/api-reference.md)
- [Deployment Guide](docs/deployment.md)
