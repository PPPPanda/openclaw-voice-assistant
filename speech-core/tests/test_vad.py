"""VAD 单元测试

测试 SileroVAD 的状态转换、边界条件和配置选项。
使用 MockSileroVAD 来控制 VAD 模型输出。
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from speech_core.interfaces import VADConfig, VADEvent, VADState
from speech_core.vad.silero import SileroVAD


class MockSileroVAD(SileroVAD):
    """Mock Silero VAD - 用于测试

    继承 SileroVAD 但覆盖模型推理部分，
    返回可控的 confidence 值。
    """

    def __init__(self, config: VADConfig | None = None) -> None:
        super().__init__(config)
        self._mock_confidence: float = 0.0
        self._mock_confidence_sequence: list[float] = []

    def set_confidence(self, confidence: float) -> None:
        """设置固定的 confidence 值"""
        self._mock_confidence = confidence
        self._mock_confidence_sequence = []

    def set_confidence_sequence(self, sequence: list[float]) -> None:
        """设置 confidence 序列（每次调用返回下一个值）"""
        self._mock_confidence = 0.0
        self._mock_confidence_sequence = list(sequence)

    async def load_model(self) -> None:
        """Mock 模型加载"""
        self._loaded = True
        # 创建一个 mock 模型对象
        self._model = MagicMock()

    def _get_confidence(self, audio_chunk: bytes) -> float:
        """获取 confidence（从序列或固定值）"""
        if self._mock_confidence_sequence:
            if not self._mock_confidence_sequence:
                return 0.0
            return self._mock_confidence_sequence.pop(0)
        return self._mock_confidence


def create_silent_chunk(duration_ms: int = 32, sample_rate: int = 16000) -> bytes:
    """创建静音音频块"""
    num_samples = int(sample_rate * duration_ms / 1000)
    return b"\x00\x00" * num_samples  # PCM s16le 零值


def create_speech_chunk(duration_ms: int = 32, sample_rate: int = 16000) -> bytes:
    """创建模拟语音音频块"""
    import numpy as np
    num_samples = int(sample_rate * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, num_samples)
    # 150Hz 基频的模拟语音
    audio = np.sin(2 * np.pi * 150 * t) * 0.5
    audio_int16 = (audio * 32767).astype(np.int16)
    return audio_int16.tobytes()


class TestVADStateTransitions:
    """VAD 状态转换测试"""

    @pytest.fixture
    def vad(self) -> MockSileroVAD:
        """创建 VAD 实例"""
        config = VADConfig(
            threshold=0.5,
            min_speech_duration_ms=300,
            min_silence_duration_ms=600,
        )
        return MockSileroVAD(config)

    @pytest.mark.asyncio
    async def test_silence_to_speech_transition(self, vad: MockSileroVAD):
        """测试静音→说话状态转换"""
        await vad.load_model()

        # 初始状态应该是 SILENCE
        assert vad.current_state == VADState.SILENCE

        # 设置低 confidence（静音）
        vad.set_confidence(0.1)
        event = vad.process_chunk(create_silent_chunk())
        assert event is None
        assert vad.current_state == VADState.SILENCE

        # 连续几个高 confidence 块，触发说话检测
        vad.set_confidence_sequence([0.6, 0.7, 0.8, 0.9] * 10)

        events = []
        for _ in range(40):
            event = vad.process_chunk(create_speech_chunk())
            if event:
                events.append(event)

        # 应该检测到说话开始
        assert len(events) > 0
        assert events[0].state == VADState.SPEECH
        assert vad.current_state == VADState.SPEECH

    @pytest.mark.asyncio
    async def test_speech_to_silence_transition(self, vad: MockSileroVAD):
        """测试说话→静音状态转换"""
        await vad.load_model()

        # 先进入说话状态
        vad.set_confidence_sequence([0.9] * 20)
        for _ in range(20):
            vad.process_chunk(create_speech_chunk())

        assert vad.current_state == VADState.SPEECH

        # 切换到静音
        vad.set_confidence_sequence([0.1] * 20)

        events = []
        for _ in range(20):
            event = vad.process_chunk(create_silent_chunk())
            if event:
                events.append(event)

        # 应该检测到说话结束
        if events:
            assert events[-1].state == VADState.SILENCE
        assert vad.current_state == VADState.SILENCE

    @pytest.mark.asyncio
    async def test_full_sequence(self, vad: MockSileroVAD):
        """测试完整序列：静音→说话→静音"""
        await vad.load_model()

        events_log = []

        # 静音阶段
        vad.set_confidence(0.1)
        for _ in range(5):
            events_log.append(vad.process_chunk(create_silent_chunk()))

        # 说话开始（需要连续高 confidence）
        vad.set_confidence_sequence([0.8] * 10)
        for _ in range(10):
            event = vad.process_chunk(create_speech_chunk())
            events_log.append(event)

        # 说话中
        vad.set_confidence(0.9)
        for _ in range(20):
            events_log.append(vad.process_chunk(create_speech_chunk()))

        # 静音（结束说话）
        vad.set_confidence(0.1)
        for _ in range(20):
            event = vad.process_chunk(create_silent_chunk())
            events_log.append(event)

        # 应该有 SPEECH 开始和 SILENCE 结束事件
        speech_events = [e for e in events_log if e and e.state == VADState.SPEECH]
        silence_events = [e for e in events_log if e and e.state == VADState.SILENCE]

        assert len(speech_events) >= 1, "Should detect speech start"
        assert len(silence_events) >= 1, "Should detect speech end"


class TestVADConfig:
    """VAD 配置边界测试"""

    @pytest.mark.asyncio
    async def test_min_speech_duration(self):
        """测试最小说话时间阈值"""
        config = VADConfig(
            threshold=0.5,
            min_speech_duration_ms=500,  # 500ms
        )
        vad = MockSileroVAD(config)
        await vad.load_model()

        # 只给 300ms 的高 confidence，不应触发 SPEECH
        vad.set_confidence_sequence([0.9] * 3)  # 约 96ms * 3 < 500ms

        for _ in range(3):
            vad.process_chunk(create_speech_chunk(32))

        assert vad.current_state == VADState.SILENCE

    @pytest.mark.asyncio
    async def test_min_silence_duration(self):
        """测试最小静音时间阈值"""
        config = VADConfig(
            threshold=0.5,
            min_speech_duration_ms=100,
            min_silence_duration_ms=1000,  # 1秒
        )
        vad = MockSileroVAD(config)
        await vad.load_model()

        # 先进入说话状态
        vad.set_confidence_sequence([0.9] * 10)
        for _ in range(10):
            vad.process_chunk(create_speech_chunk())

        # 只给 300ms 的低 confidence，不应触发 SILENCE
        vad.set_confidence_sequence([0.1] * 3)  # 约 96ms * 3 < 1000ms

        for _ in range(3):
            vad.process_chunk(create_silent_chunk())

        assert vad.current_state == VADState.SPEECH


class TestVADMaxDuration:
    """最大时长切断测试"""

    @pytest.mark.asyncio
    async def test_max_speech_duration_force_end(self):
        """测试超过最大时长强制结束"""
        config = VADConfig(
            threshold=0.5,
            min_speech_duration_ms=100,
            max_speech_duration_s=1.0,  # 1秒
        )
        vad = MockSileroVAD(config)
        await vad.load_model()

        # 进入说话状态
        vad.set_confidence_sequence([0.9] * 5)
        for _ in range(5):
            vad.process_chunk(create_speech_chunk())

        assert vad.current_state == VADState.SPEECH

        # 持续说话超过 1 秒
        vad.set_confidence(0.9)
        events = []
        for i in range(50):
            event = vad.process_chunk(create_speech_chunk(32))
            if event:
                events.append(event)
                if event.state == VADState.SILENCE:
                    break

        # 应该触发最大时长切断
        assert any(e.state == VADState.SILENCE for e in events)


class TestVADReset:
    """VAD 重置测试"""

    @pytest.mark.asyncio
    async def test_reset_clears_state(self):
        """测试 reset 清除状态"""
        vad = MockSileroVAD()
        await vad.load_model()

        # 进入说话状态
        vad.set_confidence_sequence([0.9] * 20)
        for _ in range(20):
            vad.process_chunk(create_speech_chunk())

        assert vad.current_state == VADState.SPEECH

        # 重置
        vad.reset()

        assert vad.current_state == VADState.SILENCE
        assert vad.current_time_ms == 0.0

    @pytest.mark.asyncio
    async def test_reset_allows_new_detection(self):
        """测试重置后可以重新检测"""
        vad = MockSileroVAD()
        await vad.load_model()

        # 第一次说话检测
        vad.set_confidence_sequence([0.9] * 10)
        for _ in range(10):
            vad.process_chunk(create_speech_chunk())

        # 重置
        vad.reset()

        # 第二次说话检测
        vad.set_confidence_sequence([0.9] * 10)
        for _ in range(10):
            event = vad.process_chunk(create_speech_chunk())
            if event and event.state == VADState.SPEECH:
                break

        assert vad.current_state == VADState.SPEECH


class TestVADEvent:
    """VAD 事件测试"""

    @pytest.mark.asyncio
    async def test_vad_event_attributes(self):
        """测试 VAD 事件属性"""
        vad = MockSileroVAD()
        await vad.load_model()

        vad.set_confidence_sequence([0.9] * 10)
        event = vad.process_chunk(create_speech_chunk())

        if event:
            assert event.state in [VADState.SPEECH, VADState.SILENCE]
            assert event.timestamp_ms >= 0
            assert 0.0 <= event.confidence <= 1.0


class TestVADTimestamps:
    """VAD 时间戳测试"""

    @pytest.mark.asyncio
    async def test_timestamp_continuity(self):
        """测试时间戳连续性"""
        vad = MockSileroVAD()
        await vad.load_model()

        vad.set_confidence(0.9)

        prev_time = 0.0
        for _ in range(10):
            vad.process_chunk(create_speech_chunk())
            current_time = vad.current_time_ms
            assert current_time > prev_time
            prev_time = current_time
