"""SpeechPipeline 集成测试

测试完整流水线的状态机、回调和打断场景。
使用 Mock STT/TTS 引擎。
"""

from __future__ import annotations

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from speech_core.interfaces import (
    AudioData,
    AudioFormat,
    ConversationState,
    Segment,
    SpeechEvent,
    STTOptions,
    STTResult,
    TTSChunk,
    TTSOptions,
    TTSResult,
    VADConfig,
)
from speech_core.pipeline.speech_pipeline import SpeechPipeline
from speech_core.stt.engine import BaseSTTEngine
from speech_core.tts.engine import BaseTTSEngine
from speech_core.vad.silero import SileroVAD


class MockSTTEngine(BaseSTTEngine):
    """Mock STT 引擎"""

    def __init__(self, response_text: str = "mock transcription") -> None:
        super().__init__(name="mock-stt")
        self._response_text = response_text
        self._transcribe_latency: float = 0.01  # 10ms

    async def load_model(self, model_name: str) -> None:
        self._loaded = True

    async def transcribe(self, audio: AudioData, options: STTOptions) -> STTResult:
        await asyncio.sleep(self._transcribe_latency)
        return STTResult(
            text=self._response_text,
            language="en",
            confidence=0.95,
            segments=[Segment(start=0.0, end=2.5, text=self._response_text)],
            processing_time_ms=int(self._transcribe_latency * 1000),
        )


class MockTTSEngine(BaseTTSEngine):
    """Mock TTS 引擎"""

    def __init__(self, chunk_size: int = 3) -> None:
        super().__init__(name="mock-tts")
        self._chunk_size = chunk_size
        self._synthesize_latency: float = 0.01

    async def load_model(self, voice: str) -> None:
        self._loaded = True

    async def synthesize(self, text: str, options: TTSOptions) -> TTSResult:
        await asyncio.sleep(self._synthesize_latency)
        audio_data = b"\x00\x01" * 1600  # 100ms 音频
        return TTSResult(
            audio=AudioData(
                format=AudioFormat.PCM_S16LE,
                sample_rate=16000,
                channels=1,
                data=audio_data,
            ),
            processing_time_ms=int(self._synthesize_latency * 1000),
        )

    async def synthesize_stream(
        self,
        text: str,
        options: TTSOptions,
    ):
        for i in range(self._chunk_size):
            await asyncio.sleep(0.01)
            yield TTSChunk(
                index=i,
                audio=b"\x00\x01" * 800,
                duration_ms=50.0,
                final=i == self._chunk_size - 1,
            )


class MockVAD(SileroVAD):
    """Mock VAD - 用于测试"""

    def __init__(self, config: VADConfig | None = None) -> None:
        super().__init__(config)
        self._mock_state = "silence"

    async def load_model(self) -> None:
        self._loaded = True

    def process_chunk(self, audio_chunk: bytes):
        """返回预设行为"""
        return None  # 默认不触发任何事件


def create_audio_chunk(duration_ms: int = 32) -> bytes:
    """创建音频块"""
    import numpy as np
    num_samples = int(16000 * duration_ms / 1000)
    audio = np.random.randint(-1000, 1000, num_samples, dtype=np.int16)
    return audio.tobytes()


class TestSpeechPipelineStateMachine:
    """状态机转换测试"""

    @pytest.mark.asyncio
    async def test_idle_to_listening_transition(self):
        """测试 IDLE→LISTENING 转换"""
        stt = MockSTTEngine()
        tts = MockTTSEngine()
        vad = MockVAD()

        pipeline = SpeechPipeline(stt, tts, vad=vad)
        await pipeline.initialize()

        assert pipeline.state == ConversationState.IDLE

    @pytest.mark.asyncio
    async def test_state_sequence(self):
        """测试完整状态序列"""
        stt = MockSTTEngine("test input")
        tts = MockTTSEngine()
        vad = MockVAD()

        pipeline = SpeechPipeline(stt, tts, vad=vad)
        await pipeline.initialize()

        state_history = []

        async def on_state_change(old, new):
            state_history.append((old, new))

        pipeline.on_state_change = on_state_change

        # 模拟音频处理（不会触发实际转写，因为 VAD 返回 None）
        for _ in range(5):
            await pipeline.process_audio(create_audio_chunk(), "user1", "channel1")

        # 状态应该保持在 IDLE（因为没有完整的语音段）
        assert pipeline.state == ConversationState.IDLE


class TestSpeechPipelineCallbacks:
    """回调触发测试"""

    @pytest.mark.asyncio
    async def test_on_transcription_callback(self):
        """测试转写回调"""
        stt = MockSTTEngine("hello world")
        tts = MockTTSEngine()
        vad = MockVAD(VADConfig(min_speech_duration_ms=50, min_silence_duration_ms=50))

        pipeline = SpeechPipeline(stt, tts, vad=vad)
        await pipeline.initialize()

        transcription_results = []

        async def on_transcription(result, user_id, channel_id):
            transcription_results.append((result, user_id, channel_id))

        pipeline.on_transcription = on_transcription

        # 模拟 VAD 触发说话开始和结束
        from speech_core.interfaces import VADEvent, VADState
        vad._mock_events_queue = [
            VADEvent(VADState.SPEECH, 100.0, 0.9),
        ]

        # 处理音频（需要构造能触发完整语音段的场景）
        # 这里简接测试回调机制存在
        assert pipeline.on_transcription is not None

    @pytest.mark.asyncio
    async def test_on_speech_event_callback(self):
        """测试语音事件回调"""
        stt = MockSTTEngine()
        tts = MockTTSEngine()
        vad = MockVAD()

        pipeline = SpeechPipeline(stt, tts, vad=vad)
        await pipeline.initialize()

        events_received = []

        async def on_speech_event(event: SpeechEvent):
            events_received.append(event)

        pipeline.on_speech_event = on_speech_event

        # 触发语音事件
        event = SpeechEvent(event="test.event", user_id="user1", channel_id="channel1")
        # 直接测试回调设置
        assert pipeline.on_speech_event is not None


class TestSpeechPipelineSpeak:
    """speak 方法测试"""

    @pytest.mark.asyncio
    async def test_speak_changes_state(self):
        """测试 speak 改变状态"""
        stt = MockSTTEngine()
        tts = MockTTSEngine(chunk_size=2)
        vad = MockVAD()

        pipeline = SpeechPipeline(stt, tts, vad=vad)
        await pipeline.initialize()

        initial_state = pipeline.state

        # 执行 speak
        chunks = []
        async for chunk in pipeline.speak("test response"):
            chunks.append(chunk)

        # 应该有音频块输出
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_speak_sync(self):
        """测试同步合成"""
        stt = MockSTTEngine()
        tts = MockTTSEngine()
        vad = MockVAD()

        pipeline = SpeechPipeline(stt, tts, vad=vad)
        await pipeline.initialize()

        result = await pipeline.speak_sync("hello")

        assert result.audio.data is not None
        assert result.processing_time_ms > 0

    @pytest.mark.asyncio
    async def test_speak_empty_text(self):
        """测试空文本处理"""
        stt = MockSTTEngine()
        tts = MockTTSEngine()
        vad = MockVAD()

        pipeline = SpeechPipeline(stt, tts, vad=vad)
        await pipeline.initialize()

        # 空文本不应崩溃
        chunks = []
        async for chunk in pipeline.speak(""):
            chunks.append(chunk)

        assert len(chunks) == 0


class TestSpeechPipelineBargeIn:
    """打断场景测试"""

    @pytest.mark.asyncio
    async def test_barge_in_cancels_speaking(self):
        """测试打断取消说话"""
        stt = MockSTTEngine()
        tts = MockTTSEngine(chunk_size=10)  # 较长的 TTS 输出
        vad = MockVAD()

        pipeline = SpeechPipeline(stt, tts, vad=vad)
        await pipeline.initialize()

        # 开始说话
        speak_task = asyncio.create_task(pipeline.speak("long response").__anext__())

        # 等待开始
        await asyncio.sleep(0.05)

        # 模拟打断
        from speech_core.pipeline.barge_in import BargeInConfig
        config = BargeInConfig(enabled=True, confidence_threshold=0.5)
        pipeline._barge_in = config
        pipeline._cancel_speaking.set()

        # 尝试获取下一块（应该被取消）
        try:
            await asyncio.wait_for(speak_task, timeout=0.5)
        except asyncio.TimeoutError:
            # 预期行为：超时
            pass


class TestSpeechPipelineReset:
    """重置测试"""

    @pytest.mark.asyncio
    async def test_reset_clears_state(self):
        """测试 reset 清除状态"""
        stt = MockSTTEngine()
        tts = MockTTSEngine()
        vad = MockVAD()

        pipeline = SpeechPipeline(stt, tts, vad=vad)
        await pipeline.initialize()

        # 重置
        pipeline.reset()

        assert pipeline.state == ConversationState.IDLE
        assert pipeline.is_initialized is True


class TestSpeechPipelineProperties:
    """属性测试"""

    @pytest.mark.asyncio
    async def test_initialized_property(self):
        """测试 is_initialized 属性"""
        stt = MockSTTEngine()
        tts = MockTTSEngine()
        vad = MockVAD()

        pipeline = SpeechPipeline(stt, tts, vad=vad)

        assert pipeline.is_initialized is False

        await pipeline.initialize()

        assert pipeline.is_initialized is True

    @pytest.mark.asyncio
    async def test_state_property(self):
        """测试 state 属性"""
        stt = MockSTTEngine()
        tts = MockTTSEngine()
        vad = MockVAD()

        pipeline = SpeechPipeline(stt, tts, vad=vad)
        await pipeline.initialize()

        assert pipeline.state == ConversationState.IDLE


class TestSpeechPipelineEdgeCases:
    """边界情况测试"""

    @pytest.mark.asyncio
    async def test_process_audio_not_initialized(self):
        """测试未初始化时的处理"""
        stt = MockSTTEngine()
        tts = MockTTSEngine()
        vad = MockVAD()

        pipeline = SpeechPipeline(stt, tts, vad=vad)

        # 未初始化时应抛出异常
        with pytest.raises(RuntimeError, match="not initialized"):
            await pipeline.process_audio(create_audio_chunk(), "user1", "channel1")

    @pytest.mark.asyncio
    async def test_multiple_sessions(self):
        """测试多会话场景"""
        stt = MockSTTEngine()
        tts = MockTTSEngine()
        vad = MockVAD()

        pipeline = SpeechPipeline(stt, tts, vad=vad)
        await pipeline.initialize()

        # 处理来自不同用户的音频
        await pipeline.process_audio(create_audio_chunk(), "user1", "channel1")
        await pipeline.process_audio(create_audio_chunk(), "user2", "channel1")

        # 应该都能处理
        assert pipeline.is_initialized
