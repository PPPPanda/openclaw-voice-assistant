"""STT 引擎测试"""

from __future__ import annotations

import numpy as np
import pytest
import pytest_asyncio

from speech_core.interfaces import AudioData, AudioFormat, STTOptions
from speech_core.stt.whisper import FasterWhisperEngine


def _generate_silent_audio(duration_s: float = 1.0, sample_rate: int = 16000) -> AudioData:
    """生成静音 PCM 音频用于测试"""
    samples = int(duration_s * sample_rate)
    # 静音 + 微小噪声
    noise = np.random.randint(-10, 10, size=samples, dtype=np.int16)
    return AudioData(
        format=AudioFormat.PCM_S16LE,
        sample_rate=sample_rate,
        channels=1,
        data=noise.tobytes(),
    )


def _generate_tone_audio(
    frequency: float = 440.0,
    duration_s: float = 1.0,
    sample_rate: int = 16000,
) -> AudioData:
    """生成正弦波音频用于测试"""
    t = np.linspace(0, duration_s, int(duration_s * sample_rate), endpoint=False)
    tone = (np.sin(2 * np.pi * frequency * t) * 16000).astype(np.int16)
    return AudioData(
        format=AudioFormat.PCM_S16LE,
        sample_rate=sample_rate,
        channels=1,
        data=tone.tobytes(),
    )


class TestAudioData:
    """AudioData 类型测试"""

    def test_duration_calculation(self):
        """测试 PCM 音频时长计算"""
        audio = _generate_silent_audio(duration_s=2.0, sample_rate=16000)
        assert abs(audio.duration_ms - 2000.0) < 1.0

    def test_duration_non_pcm(self):
        """非 PCM 格式时长为 0"""
        audio = AudioData(
            format=AudioFormat.OPUS,
            sample_rate=48000,
            channels=1,
            data=b"\x00" * 100,
        )
        assert audio.duration_ms == 0.0


class TestSTTOptions:
    """STT 选项测试"""

    def test_defaults(self):
        options = STTOptions()
        assert options.language == "auto"
        assert options.model == "base"
        assert options.vad_enabled is True
        assert options.vad_threshold == 0.5

    def test_custom_options(self):
        options = STTOptions(language="zh", model="large-v3", vad_enabled=False)
        assert options.language == "zh"
        assert options.model == "large-v3"
        assert options.vad_enabled is False


class TestFasterWhisperEngine:
    """faster-whisper 引擎测试（需要模型）"""

    def test_engine_init(self):
        engine = FasterWhisperEngine(device="cpu", compute_type="int8")
        assert engine.name == "faster-whisper"
        assert engine.is_loaded() is False

    @pytest.mark.skipif(
        True,  # 设为 False 以启用集成测试
        reason="Integration test - requires model download",
    )
    @pytest.mark.asyncio
    async def test_transcribe_silent_audio(self):
        """转写静音音频应返回空文本"""
        engine = FasterWhisperEngine(device="cpu", compute_type="int8")
        await engine.load_model("tiny")

        audio = _generate_silent_audio(duration_s=1.0)
        options = STTOptions(vad_enabled=False)
        result = await engine.transcribe(audio, options)

        assert result.processing_time_ms > 0
        assert isinstance(result.text, str)
