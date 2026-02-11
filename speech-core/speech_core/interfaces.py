"""Speech Core 类型定义与接口"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Protocol


# ─── Audio Formats ───────────────────────────────────────────────────────────


class AudioFormat(Enum):
    """支持的音频格式"""
    PCM_S16LE = "pcm_s16le"
    OPUS = "opus"
    MP3 = "mp3"


@dataclass
class AudioData:
    """音频数据载体"""
    format: AudioFormat
    sample_rate: int
    channels: int
    data: bytes

    @property
    def duration_ms(self) -> float:
        """估算音频时长（仅适用于 PCM）"""
        if self.format != AudioFormat.PCM_S16LE:
            return 0.0
        bytes_per_sample = 2  # s16le = 2 bytes
        total_samples = len(self.data) / (bytes_per_sample * self.channels)
        return (total_samples / self.sample_rate) * 1000


# ─── STT Types ───────────────────────────────────────────────────────────────


@dataclass
class STTOptions:
    """STT 转写选项"""
    language: str = "auto"
    model: str = "base"
    vad_enabled: bool = True
    vad_threshold: float = 0.5


@dataclass
class Segment:
    """转写片段"""
    start: float
    end: float
    text: str


@dataclass
class STTResult:
    """STT 转写结果"""
    text: str
    language: str
    confidence: float
    segments: list[Segment]
    processing_time_ms: int


# ─── TTS Types ───────────────────────────────────────────────────────────────


@dataclass
class TTSOptions:
    """TTS 合成选项"""
    voice: str = "zh_CN-huayan-medium"
    speed: float = 1.0
    pitch: float = 1.0
    provider: str = "piper"


@dataclass
class TTSResult:
    """TTS 合成结果"""
    audio: AudioData
    processing_time_ms: int


@dataclass
class TTSChunk:
    """TTS 流式合成块"""
    index: int
    audio: bytes
    duration_ms: float
    final: bool


# ─── Audio Output Config ─────────────────────────────────────────────────────


@dataclass
class AudioOutputConfig:
    """音频输出配置"""
    format: AudioFormat = AudioFormat.OPUS
    sample_rate: int = 48000
    channels: int = 1


# ─── VAD Types ───────────────────────────────────────────────────────────────


@dataclass
class VADConfig:
    """VAD 配置"""
    threshold: float = 0.5
    min_silence_duration_ms: int = 600
    min_speech_duration_ms: int = 300
    max_speech_duration_s: float = 8.0
    sample_rate: int = 16000
    window_size_samples: int = 512  # 32ms at 16kHz


class VADState(Enum):
    """VAD 状态"""
    SILENCE = "silence"
    SPEECH = "speech"


@dataclass
class VADEvent:
    """VAD 事件"""
    state: VADState
    timestamp_ms: float
    confidence: float


# ─── Speech Pipeline Types ───────────────────────────────────────────────────


class ConversationState(Enum):
    """半双工对话状态机"""
    IDLE = "idle"               # 等待用户说话
    LISTENING = "listening"     # 正在录音
    PROCESSING = "processing"   # STT + LLM 处理中
    SPEAKING = "speaking"       # TTS 播放中


@dataclass
class SpeechEvent:
    """语音事件"""
    event: str
    user_id: str
    channel_id: str
    timestamp: float = field(default_factory=lambda: time.time() * 1000)
    data: dict | None = None


# ─── Service Status ──────────────────────────────────────────────────────────


@dataclass
class SpeechCoreStatus:
    """服务状态"""
    status: str  # "healthy" | "degraded" | "unhealthy"
    stt_engine: str
    tts_engine: str
    vad_loaded: bool
    gpu_available: bool
    uptime_seconds: float


@dataclass
class ModelInfo:
    """模型信息"""
    name: str
    type: str  # "stt" | "tts" | "vad"
    loaded: bool
    size_mb: float | None = None


# ─── Service Interfaces (Protocols) ─────────────────────────────────────────


class STTEngine(Protocol):
    """STT 引擎接口"""

    async def load_model(self, model_name: str) -> None:
        """加载模型"""
        ...

    async def transcribe(self, audio: AudioData, options: STTOptions) -> STTResult:
        """同步转写"""
        ...

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        options: STTOptions,
    ) -> AsyncIterator[STTResult]:
        """流式转写"""
        ...

    def is_loaded(self) -> bool:
        """模型是否已加载"""
        ...


class TTSEngine(Protocol):
    """TTS 引擎接口"""

    async def load_model(self, voice: str) -> None:
        """加载模型/语音"""
        ...

    async def synthesize(self, text: str, options: TTSOptions) -> TTSResult:
        """同步合成"""
        ...

    async def synthesize_stream(
        self,
        text: str,
        options: TTSOptions,
    ) -> AsyncIterator[TTSChunk]:
        """流式合成（句子级）"""
        ...

    def is_loaded(self) -> bool:
        """模型是否已加载"""
        ...


class VADDetector(Protocol):
    """VAD 检测器接口"""

    async def load_model(self) -> None:
        """加载 VAD 模型"""
        ...

    def process_chunk(self, audio_chunk: bytes) -> VADEvent | None:
        """处理一个音频块，返回 VAD 事件（如果状态改变）"""
        ...

    def reset(self) -> None:
        """重置 VAD 状态"""
        ...

    def is_loaded(self) -> bool:
        """模型是否已加载"""
        ...
