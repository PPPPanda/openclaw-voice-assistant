"""配置管理"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int = 0) -> int:
    return int(os.getenv(key, str(default)))


def _env_float(key: str, default: float = 0.0) -> float:
    return float(os.getenv(key, str(default)))


def _env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


@dataclass
class ServerConfig:
    """WebSocket RPC 服务配置"""
    host: str = "0.0.0.0"
    port: int = 9001
    max_connections: int = 10
    ping_interval: float = 20.0
    ping_timeout: float = 10.0


@dataclass
class STTConfig:
    """STT 引擎配置"""
    engine: str = "faster-whisper"
    model: str = "base"
    device: str = "auto"
    compute_type: str = "auto"
    language: str = "auto"
    beam_size: int = 5


@dataclass
class TTSConfig:
    """TTS 引擎配置"""
    engine: str = "piper"
    voice: str = "zh_CN-huayan-medium"
    speed: float = 1.0
    # ElevenLabs 备选
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""


@dataclass
class VADConfig:
    """VAD 配置"""
    threshold: float = 0.5
    min_silence_ms: int = 600
    min_speech_ms: int = 300
    max_speech_s: float = 8.0


@dataclass
class AppConfig:
    """应用总配置"""
    server: ServerConfig = field(default_factory=ServerConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> AppConfig:
        """从环境变量加载配置"""
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()

        return cls(
            server=ServerConfig(
                host=_env("SPEECH_CORE_HOST", "0.0.0.0"),
                port=_env_int("SPEECH_CORE_PORT", 9001),
            ),
            stt=STTConfig(
                engine=_env("STT_ENGINE", "faster-whisper"),
                model=_env("STT_MODEL", "base"),
                device=_env("STT_DEVICE", "auto"),
                compute_type=_env("STT_COMPUTE_TYPE", "auto"),
                language=_env("STT_LANGUAGE", "auto"),
            ),
            tts=TTSConfig(
                engine=_env("TTS_ENGINE", "piper"),
                voice=_env("TTS_VOICE", "zh_CN-huayan-medium"),
                speed=_env_float("TTS_SPEED", 1.0),
                elevenlabs_api_key=_env("ELEVENLABS_API_KEY"),
                elevenlabs_voice_id=_env("ELEVENLABS_VOICE_ID"),
            ),
            vad=VADConfig(
                threshold=_env_float("VAD_THRESHOLD", 0.5),
                min_silence_ms=_env_int("VAD_MIN_SILENCE_MS", 600),
                min_speech_ms=_env_int("VAD_MIN_SPEECH_MS", 300),
                max_speech_s=_env_float("VAD_MAX_SPEECH_S", 8.0),
            ),
            log_level=_env("LOG_LEVEL", "INFO"),
        )
