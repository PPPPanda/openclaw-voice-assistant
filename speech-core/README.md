# OpenClaw Speech Core

Python service providing STT/TTS/VAD capabilities for OpenClaw Voice Assistant.

## Features

- **STT**: faster-whisper (GPU) / whisper.cpp (CPU)
- **TTS**: Piper (local) / ElevenLabs (cloud)
- **VAD**: Silero VAD

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

```bash
python -m speech_core.server
```

Service starts at `ws://localhost:9001/speech`.

## Protocol

JSON-RPC 2.0 over WebSocket.

### Methods

- `speech.stt` - Speech to text
- `speech.tts` - Text to speech
- `speech.status` - Service status
- `speech.models` - Available models

## License

MIT
