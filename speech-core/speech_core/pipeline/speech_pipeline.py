"""语音处理主流水线

协调 VAD → STT → (LLM) → TTS 的完整语音对话流程。
管理半双工对话状态机。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator, Callable, Awaitable

from speech_core.interfaces import (
    AudioData,
    AudioFormat,
    ConversationState,
    STTOptions,
    STTResult,
    SpeechEvent,
    TTSChunk,
    TTSOptions,
    TTSResult,
)
from speech_core.pipeline.barge_in import BargeInConfig, BargeInController
from speech_core.pipeline.segment import SegmentBuffer, SpeechSegment
from speech_core.stt.engine import BaseSTTEngine
from speech_core.tts.engine import BaseTTSEngine
from speech_core.vad.silero import SileroVAD

logger = logging.getLogger(__name__)


class SpeechPipeline:
    """语音处理主流水线

    协调各组件完成完整的语音对话：
    1. 接收音频 → VAD 检测 → 分段
    2. 完整语音段 → STT 转写
    3. 转写文本 → (外部 LLM 处理)
    4. LLM 回复 → TTS 合成 → 音频输出

    半双工状态机：
        IDLE → (user_speech_start) → LISTENING
        LISTENING → (silence_detected) → PROCESSING
        PROCESSING → (llm_response_ready) → SPEAKING
        SPEAKING → (playback_complete) → IDLE

    Usage:
        pipeline = SpeechPipeline(stt_engine, tts_engine)
        await pipeline.initialize()

        # 设置回调
        pipeline.on_transcription = handle_transcription
        pipeline.on_tts_audio = handle_tts_audio
        pipeline.on_state_change = handle_state_change

        # 在音频接收循环中
        async for chunk in audio_stream:
            await pipeline.process_audio(chunk, user_id, channel_id)

        # 当 LLM 回复就绪时
        async for tts_chunk in pipeline.speak(text, options):
            send_audio(tts_chunk)
    """

    def __init__(
        self,
        stt_engine: BaseSTTEngine,
        tts_engine: BaseTTSEngine,
        vad: SileroVAD | None = None,
        barge_in_config: BargeInConfig | None = None,
    ) -> None:
        self._stt = stt_engine
        self._tts = tts_engine
        self._vad = vad or SileroVAD()
        self._segment_buffer = SegmentBuffer(self._vad)
        self._barge_in = BargeInController(barge_in_config)
        self._state = ConversationState.IDLE
        self._initialized = False

        # 回调函数
        self.on_transcription: Callable[[STTResult, str, str], Awaitable[None]] | None = None
        self.on_tts_audio: Callable[[TTSChunk], Awaitable[None]] | None = None
        self.on_state_change: Callable[[ConversationState, ConversationState], Awaitable[None]] | None = None
        self.on_speech_event: Callable[[SpeechEvent], Awaitable[None]] | None = None

        # 打断回调
        self._barge_in.set_callback(self._handle_barge_in)

        # 内部状态
        self._speaking_task: asyncio.Task | None = None
        self._cancel_speaking = asyncio.Event()

    async def initialize(self) -> None:
        """初始化流水线（加载 VAD 模型）"""
        if self._initialized:
            return

        logger.info("Initializing speech pipeline...")
        await self._vad.load_model()
        self._initialized = True
        logger.info(
            f"Speech pipeline ready: STT={self._stt.name}, TTS={self._tts.name}"
        )

    async def process_audio(
        self,
        audio_chunk: bytes,
        user_id: str,
        channel_id: str,
    ) -> STTResult | None:
        """处理一个音频块

        将音频输入 VAD → 分段 → STT 转写。

        Args:
            audio_chunk: PCM s16le 音频（16kHz 单声道）
            user_id: 用户 ID
            channel_id: 频道 ID

        Returns:
            如果完成一次转写，返回结果；否则返回 None
        """
        if not self._initialized:
            raise RuntimeError("Pipeline not initialized. Call initialize() first.")

        # 如果 Bot 正在说话，检查是否需要打断
        if self._state == ConversationState.SPEAKING:
            vad_event = self._vad.process_chunk(audio_chunk)
            if vad_event and vad_event.state.value == "speech":
                triggered = await self._barge_in.on_user_speech_detected(
                    user_id, channel_id, vad_event.confidence
                )
                if triggered:
                    return None
            return None

        # 正常流程：VAD → 分段
        segment = await self._segment_buffer.process_chunk(
            audio_chunk, user_id, channel_id
        )

        # 状态更新
        if self._segment_buffer.is_recording and self._state == ConversationState.IDLE:
            await self._set_state(ConversationState.LISTENING)
            if self.on_speech_event:
                await self.on_speech_event(
                    SpeechEvent(
                        event="speech.started",
                        user_id=user_id,
                        channel_id=channel_id,
                    )
                )

        if segment and segment.complete:
            # 语音段完成 → STT 转写
            await self._set_state(ConversationState.PROCESSING)

            if self.on_speech_event:
                await self.on_speech_event(
                    SpeechEvent(
                        event="speech.ended",
                        user_id=user_id,
                        channel_id=channel_id,
                        data={"duration_ms": segment.duration_ms},
                    )
                )

            # 执行 STT
            audio = AudioData(
                format=AudioFormat.PCM_S16LE,
                sample_rate=16000,
                channels=1,
                data=segment.audio_data,
            )

            stt_options = STTOptions()
            result = await self._stt.transcribe(audio, stt_options)

            logger.info(
                f"Transcription: '{result.text}' "
                f"(lang={result.language}, conf={result.confidence:.2f}, "
                f"time={result.processing_time_ms}ms)"
            )

            # 触发回调
            if self.on_transcription:
                await self.on_transcription(result, user_id, channel_id)

            # 如果没有外部处理，自动回到 IDLE
            if self._state == ConversationState.PROCESSING:
                await self._set_state(ConversationState.IDLE)

            return result

        return None

    async def speak(
        self,
        text: str,
        options: TTSOptions | None = None,
    ) -> AsyncIterator[TTSChunk]:
        """合成并输出语音

        将文本通过 TTS 引擎合成为音频流。

        Args:
            text: 要合成的文本
            options: TTS 选项

        Yields:
            TTS 音频块
        """
        if not text.strip():
            return

        options = options or TTSOptions()
        await self._set_state(ConversationState.SPEAKING)
        self._barge_in.on_bot_start_speaking()
        self._cancel_speaking.clear()

        try:
            async for chunk in self._tts.synthesize_stream(text, options):
                # 检查是否被打断
                if self._cancel_speaking.is_set():
                    logger.info("TTS playback interrupted by barge-in")
                    break

                if self.on_tts_audio:
                    await self.on_tts_audio(chunk)

                yield chunk
        finally:
            self._barge_in.on_bot_stop_speaking()
            await self._set_state(ConversationState.IDLE)

    async def speak_sync(self, text: str, options: TTSOptions | None = None) -> TTSResult:
        """同步合成完整音频

        Args:
            text: 要合成的文本
            options: TTS 选项

        Returns:
            完整的 TTS 结果
        """
        options = options or TTSOptions()
        return await self._tts.synthesize(text, options)

    async def _handle_barge_in(self, event: SpeechEvent) -> None:
        """处理打断事件"""
        logger.info(f"Handling barge-in from user={event.user_id}")
        self._cancel_speaking.set()

        if self.on_speech_event:
            await self.on_speech_event(event)

        # 重置 VAD 和分段器
        self._segment_buffer.reset()

    async def _set_state(self, new_state: ConversationState) -> None:
        """更新对话状态"""
        if new_state == self._state:
            return

        old_state = self._state
        self._state = new_state
        logger.debug(f"State: {old_state.value} → {new_state.value}")

        if self.on_state_change:
            try:
                await self.on_state_change(old_state, new_state)
            except Exception:
                logger.exception("Error in state change callback")

    @property
    def state(self) -> ConversationState:
        """当前对话状态"""
        return self._state

    @property
    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._initialized

    def reset(self) -> None:
        """重置流水线状态"""
        self._segment_buffer.reset()
        self._barge_in.reset()
        self._state = ConversationState.IDLE
        self._cancel_speaking.clear()
        logger.info("Speech pipeline reset")
