"""语音分段管理器

管理音频流的 VAD 分段，将连续的 PCM 音频流切割为离散的语音段，
供 STT 引擎处理。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from speech_core.interfaces import AudioFormat, VADEvent, VADState
from speech_core.vad.silero import SileroVAD

logger = logging.getLogger(__name__)


@dataclass
class SpeechSegment:
    """一段完整的语音

    从 VAD 检测到说话开始，到检测到说话结束之间的所有音频数据。
    """

    user_id: str
    channel_id: str
    start_time_ms: float
    end_time_ms: float = 0.0
    audio_chunks: list[bytes] = field(default_factory=list)
    complete: bool = False

    @property
    def duration_ms(self) -> float:
        """语音时长（毫秒）"""
        return self.end_time_ms - self.start_time_ms

    @property
    def audio_data(self) -> bytes:
        """合并所有音频块"""
        return b"".join(self.audio_chunks)

    @property
    def audio_size_bytes(self) -> int:
        """音频数据大小"""
        return sum(len(c) for c in self.audio_chunks)


class SegmentBuffer:
    """语音分段缓冲器

    与 VAD 配合使用，将音频流切割成独立的语音段。

    工作流程：
    1. 接收音频块 → VAD 检测语音活动
    2. 检测到说话开始 → 创建新的 SpeechSegment，开始收集音频
    3. 检测到说话结束 → 标记 segment 完成，触发回调
    4. 超过最大时长 → 强制完成当前 segment

    Usage:
        buffer = SegmentBuffer(vad=silero_vad)
        buffer.on_segment_complete = async_callback

        # 在音频接收循环中：
        for chunk in audio_stream:
            segment = await buffer.process_chunk(chunk, user_id, channel_id)
            if segment and segment.complete:
                # 处理完整的语音段
                process_segment(segment)
    """

    def __init__(self, vad: SileroVAD) -> None:
        self._vad = vad
        self._current_segment: SpeechSegment | None = None
        self._pre_buffer: list[bytes] = []
        self._pre_buffer_max = 5  # 保留最近 5 个块作为前导缓冲

    async def process_chunk(
        self,
        audio_chunk: bytes,
        user_id: str,
        channel_id: str,
    ) -> SpeechSegment | None:
        """处理一个音频块

        Args:
            audio_chunk: PCM s16le 音频数据（16kHz 单声道）
            user_id: 用户 ID
            channel_id: 频道 ID

        Returns:
            如果一个完整的语音段就绪，返回该 segment；否则返回 None
        """
        # VAD 检测
        vad_event = self._vad.process_chunk(audio_chunk)

        if vad_event is None:
            # VAD 状态未变化
            if self._current_segment is not None:
                # 正在录音中，继续收集
                self._current_segment.audio_chunks.append(audio_chunk)
            else:
                # 静音状态，维护前导缓冲
                self._pre_buffer.append(audio_chunk)
                if len(self._pre_buffer) > self._pre_buffer_max:
                    self._pre_buffer.pop(0)
            return None

        if vad_event.state == VADState.SPEECH:
            # 开始说话 → 创建新 segment
            self._current_segment = SpeechSegment(
                user_id=user_id,
                channel_id=channel_id,
                start_time_ms=vad_event.timestamp_ms,
            )
            # 加入前导缓冲（避免丢失开头音频）
            self._current_segment.audio_chunks.extend(self._pre_buffer)
            self._current_segment.audio_chunks.append(audio_chunk)
            self._pre_buffer.clear()

            logger.debug(
                f"Segment started for user={user_id} at {vad_event.timestamp_ms:.0f}ms"
            )
            return None

        elif vad_event.state == VADState.SILENCE:
            # 停止说话 → 完成 segment
            if self._current_segment is not None:
                self._current_segment.audio_chunks.append(audio_chunk)
                self._current_segment.end_time_ms = vad_event.timestamp_ms
                self._current_segment.complete = True

                completed = self._current_segment
                self._current_segment = None

                logger.info(
                    f"Segment complete: user={user_id}, "
                    f"duration={completed.duration_ms:.0f}ms, "
                    f"size={completed.audio_size_bytes} bytes"
                )
                return completed

        return None

    def reset(self) -> None:
        """重置分段器状态"""
        self._current_segment = None
        self._pre_buffer.clear()
        self._vad.reset()
        logger.debug("Segment buffer reset")

    @property
    def is_recording(self) -> bool:
        """是否正在录音"""
        return self._current_segment is not None
