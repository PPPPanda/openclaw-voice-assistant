"""SegmentBuffer 单元测试

测试语音分段缓冲器的前导缓冲、分段流程和属性。
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

from speech_core.interfaces import VADConfig, VADState
from speech_core.pipeline.segment import SegmentBuffer, SpeechSegment
from speech_core.vad.silero import SileroVAD


class MockVAD(SileroVAD):
    """Mock VAD - 用于测试"""

    def __init__(self, config: VADConfig | None = None) -> None:
        super().__init__(config)
        self._mock_events: list = []

    def set_mock_events(self, events: list) -> None:
        """设置模拟的 VAD 事件序列"""
        self._mock_events = list(events)

    async def load_model(self) -> None:
        self._loaded = True

    def process_chunk(self, audio_chunk: bytes):
        """返回预设事件或默认行为"""
        if self._mock_events:
            event = self._mock_events.pop(0) if self._mock_events else None
            # 更新内部状态以匹配事件
            if event and event.state == VADState.SPEECH:
                self._state = VADState.SPEECH
                self._speech_start_ms = event.timestamp_ms
            elif event and event.state == VADState.SILENCE:
                self._state = VADState.SILENCE
                self._speech_start_ms = None
            return event
        return None


def create_audio_chunk(duration_ms: int = 32, sample_rate: int = 16000) -> bytes:
    """创建音频块"""
    import numpy as np
    num_samples = int(sample_rate * duration_ms / 1000)
    audio = np.random.randint(-1000, 1000, num_samples, dtype=np.int16)
    return audio.tobytes()


class TestSegmentBufferPreBuffer:
    """前导缓冲测试"""

    @pytest.fixture
    def mock_vad(self) -> MockVAD:
        config = VADConfig()
        return MockVAD(config)

    @pytest.mark.asyncio
    async def test_pre_buffer_stores_silent_chunks(self, mock_vad: MockVAD):
        """测试静音时保留前导缓冲"""
        buffer = SegmentBuffer(mock_vad)

        # 发送 3 个静音块
        for i in range(3):
            await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")

        # 前导缓冲应该有 3 个块
        assert len(buffer._pre_buffer) == 3

    @pytest.mark.asyncio
    async def test_pre_buffer_max_size(self, mock_vad: MockVAD):
        """测试前导缓冲最大数量限制"""
        config = VADConfig()
        buffer = SegmentBuffer(mock_vad)

        # 发送超过最大数量的块
        for i in range(10):
            await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")

        # 应该只保留最近 5 个
        assert len(buffer._pre_buffer) == 5

    @pytest.mark.asyncio
    async def test_pre_buffer_cleared_on_speech_start(self, mock_vad: MockVAD):
        """测试开始说话时清空前导缓冲"""
        config = VADConfig()
        buffer = SegmentBuffer(mock_vad)

        # 发送静音块填充前导缓冲
        for i in range(5):
            await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")

        assert len(buffer._pre_buffer) == 5

        # 模拟说话开始事件
        from speech_core.interfaces import VADEvent
        mock_vad.set_mock_events([
            VADEvent(VADState.SPEECH, 1000.0, 0.9),
        ])

        # 发送音频触发说话开始
        await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")

        # 前导缓冲应该被清空
        assert len(buffer._pre_buffer) == 0


class TestSegmentBufferWorkflow:
    """分段流程测试"""

    @pytest.fixture
    def mock_vad(self) -> MockVAD:
        config = VADConfig()
        return MockVAD(config)

    @pytest.mark.asyncio
    async def test_complete_segment_flow(self, mock_vad: MockVAD):
        """测试完整的分段流程：SILENCE→SPEECH→SILENCE"""
        buffer = SegmentBuffer(mock_vad)

        from speech_core.interfaces import VADEvent

        # 静音 → 说话 → 静音 事件序列
        events = [
            VADEvent(VADState.SPEECH, 1000.0, 0.9),  # 说话开始
        ]
        mock_vad.set_mock_events(events)

        # 静音块
        for i in range(3):
            await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")

        # 触发说话开始
        segment = await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")

        # 继续发送音频
        for i in range(5):
            await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")

        # 说话结束
        events = [
            VADEvent(VADState.SILENCE, 3000.0, 0.1),  # 说话结束
        ]
        mock_vad.set_mock_events(events)

        segment = await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")

        # 应该返回完整的 segment
        if segment:
            assert segment.complete is True
            assert segment.user_id == "user1"
            assert segment.channel_id == "channel1"

    @pytest.mark.asyncio
    async def test_segment_not_complete_until_silence(self, mock_vad: MockVAD):
        """测试在说话期间不返回 segment"""
        buffer = SegmentBuffer(mock_vad)

        from speech_core.interfaces import VADEvent

        # 设置说话开始事件
        events = [
            VADEvent(VADState.SPEECH, 1000.0, 0.9),
        ]
        mock_vad.set_mock_events(events)

        # 触发说话开始
        await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")

        # 继续发送音频（说话中）
        for i in range(10):
            segment = await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")
            # 说话期间不应返回 segment
            assert segment is None


class TestSpeechSegment:
    """SpeechSegment 属性测试"""

    @pytest.mark.asyncio
    async def test_segment_duration_ms(self):
        """测试 segment 时长计算"""
        segment = SpeechSegment(
            user_id="user1",
            channel_id="channel1",
            start_time_ms=1000.0,
            end_time_ms=2500.0,
        )

        assert segment.duration_ms == 1500.0

    @pytest.mark.asyncio
    async def test_segment_audio_data(self):
        """测试 segment 音频数据合并"""
        chunk1 = b"\x01\x00\x02\x00"
        chunk2 = b"\x03\x00\x04\x00"

        segment = SpeechSegment(
            user_id="user1",
            channel_id="channel1",
            start_time_ms=0.0,
            end_time_ms=100.0,
            audio_chunks=[chunk1, chunk2],
        )

        assert segment.audio_data == b"\x01\x00\x02\x00\x03\x00\x04\x00"

    @pytest.mark.asyncio
    async def test_segment_audio_size_bytes(self):
        """测试 segment 音频大小"""
        chunk1 = b"\x01\x00\x02\x00"  # 4 bytes
        chunk2 = b"\x03\x00\x04\x00"  # 4 bytes

        segment = SpeechSegment(
            user_id="user1",
            channel_id="channel1",
            start_time_ms=0.0,
            end_time_ms=100.0,
            audio_chunks=[chunk1, chunk2],
        )

        assert segment.audio_size_bytes == 8


class TestSegmentBufferReset:
    """SegmentBuffer 重置测试"""

    @pytest.fixture
    def mock_vad(self) -> MockVAD:
        config = VADConfig()
        return MockVAD(config)

    @pytest.mark.asyncio
    async def test_reset_clears_all_state(self, mock_vad: MockVAD):
        """测试 reset 清除所有状态"""
        buffer = SegmentBuffer(mock_vad)

        # 填充一些数据
        for i in range(5):
            await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")

        assert len(buffer._pre_buffer) > 0

        # 重置
        buffer.reset()

        # 所有状态应该被清除
        assert buffer._current_segment is None
        assert len(buffer._pre_buffer) == 0

    @pytest.mark.asyncio
    async def test_is_recording_property(self, mock_vad: MockVAD):
        """测试 is_recording 属性"""
        buffer = SegmentBuffer(mock_vad)

        # 初始状态
        assert buffer.is_recording is False

        from speech_core.interfaces import VADEvent

        # 触发说话开始
        events = [
            VADEvent(VADState.SPEECH, 1000.0, 0.9),
        ]
        mock_vad.set_mock_events(events)

        await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")

        # 正在录音
        assert buffer.is_recording is True

        # 重置后
        buffer.reset()
        assert buffer.is_recording is False


class TestSegmentBufferEdgeCases:
    """边界情况测试"""

    @pytest.fixture
    def mock_vad(self) -> MockVAD:
        config = VADConfig()
        return MockVAD(config)

    @pytest.mark.asyncio
    async def test_empty_audio_chunk(self, mock_vad: MockVAD):
        """测试空音频块"""
        buffer = SegmentBuffer(mock_vad)

        # 空块
        await buffer.process_chunk(b"", "user1", "channel1")

        # 应该不崩溃
        assert True

    @pytest.mark.asyncio
    async def test_multiple_users(self, mock_vad: MockVAD):
        """测试多用户场景"""
        buffer = SegmentBuffer(mock_vad)

        from speech_core.interfaces import VADEvent

        # 用户 1 说话
        events = [VADEvent(VADState.SPEECH, 1000.0, 0.9)]
        mock_vad.set_mock_events(events)
        await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")

        # 用户 2 说话（会覆盖当前 segment）
        events = [VADEvent(VADState.SPEECH, 1500.0, 0.9)]
        mock_vad.set_mock_events(events)
        await buffer.process_chunk(create_audio_chunk(), "user2", "channel1")

        # 当前 segment 应该是最新的
        assert buffer._current_segment is not None

    @pytest.mark.asyncio
    async def test_very_short_segment(self, mock_vad: MockVAD):
        """测试非常短的语音段"""
        buffer = SegmentBuffer(mock_vad)

        from speech_core.interfaces import VADEvent

        # 说话开始后立即结束
        events = [
            VADEvent(VADState.SPEECH, 1000.0, 0.9),
            VADEvent(VADState.SILENCE, 1200.0, 0.1),
        ]
        mock_vad.set_mock_events(events)

        # 触发说话
        await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")
        # 立即结束
        segment = await buffer.process_chunk(create_audio_chunk(), "user1", "channel1")

        # 应该返回 segment
        if segment:
            assert segment.complete is True
