"""Silero VAD 实现

基于 Silero VAD v5 的语音活动检测，轻量、准确、易集成。
支持 16kHz 单声道 PCM 音频输入。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import torch

from speech_core.interfaces import (
    VADConfig as VADConfigInterface,
    VADEvent,
    VADState,
)

logger = logging.getLogger(__name__)


class SileroVAD:
    """Silero VAD 语音活动检测器

    使用 Silero VAD 模型检测音频流中的语音活动。
    支持流式处理，每次接收一个音频块（window_size_samples）。

    状态转换：
        SILENCE → SPEECH: 当连续帧概率 > threshold 持续 >= min_speech_ms
        SPEECH → SILENCE: 当连续帧概率 < threshold 持续 >= min_silence_ms
    """

    def __init__(self, config: VADConfigInterface | None = None) -> None:
        self._config = config or VADConfigInterface()
        self._model: torch.jit.ScriptModule | None = None
        self._state: VADState = VADState.SILENCE
        self._loaded = False

        # 内部追踪
        self._speech_start_ms: float | None = None
        self._silence_start_ms: float | None = None
        self._current_time_ms: float = 0.0
        self._samples_processed: int = 0

    async def load_model(self) -> None:
        """加载 Silero VAD 模型"""
        if self._loaded:
            return

        logger.info("Loading Silero VAD model...")
        start = time.monotonic()

        try:
            # 使用 torch.hub 加载 Silero VAD
            self._model, _utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
            )
            self._loaded = True
            elapsed = (time.monotonic() - start) * 1000
            logger.info(f"Silero VAD loaded in {elapsed:.0f}ms")
        except Exception:
            logger.exception("Failed to load Silero VAD model")
            raise

    def process_chunk(self, audio_chunk: bytes) -> VADEvent | None:
        """处理一个音频块

        Args:
            audio_chunk: PCM s16le 音频数据，16kHz 单声道

        Returns:
            VADEvent 如果状态发生转换，否则 None
        """
        if not self._loaded or self._model is None:
            raise RuntimeError("VAD model not loaded. Call load_model() first.")

        # 将 PCM bytes 转换为 float32 tensor
        audio_array = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        audio_tensor = torch.from_numpy(audio_array)

        # 计算当前时间戳
        chunk_duration_ms = (len(audio_array) / self._config.sample_rate) * 1000
        self._current_time_ms += chunk_duration_ms
        self._samples_processed += len(audio_array)

        # Silero VAD 推理
        confidence = self._model(audio_tensor, self._config.sample_rate).item()

        is_speech = confidence >= self._config.threshold
        event: VADEvent | None = None

        if self._state == VADState.SILENCE:
            if is_speech:
                if self._speech_start_ms is None:
                    self._speech_start_ms = self._current_time_ms

                # 检查是否持续说话足够长
                speech_duration = self._current_time_ms - self._speech_start_ms
                if speech_duration >= self._config.min_speech_duration_ms:
                    self._state = VADState.SPEECH
                    self._silence_start_ms = None
                    event = VADEvent(
                        state=VADState.SPEECH,
                        timestamp_ms=self._speech_start_ms,
                        confidence=confidence,
                    )
                    logger.debug(
                        f"Speech started at {self._speech_start_ms:.0f}ms "
                        f"(confidence={confidence:.2f})"
                    )
            else:
                self._speech_start_ms = None

        elif self._state == VADState.SPEECH:
            if not is_speech:
                if self._silence_start_ms is None:
                    self._silence_start_ms = self._current_time_ms

                # 检查是否安静足够长 → 结束说话
                silence_duration = self._current_time_ms - self._silence_start_ms
                if silence_duration >= self._config.min_silence_duration_ms:
                    self._state = VADState.SILENCE
                    self._speech_start_ms = None
                    event = VADEvent(
                        state=VADState.SILENCE,
                        timestamp_ms=self._silence_start_ms,
                        confidence=confidence,
                    )
                    logger.debug(
                        f"Speech ended at {self._silence_start_ms:.0f}ms "
                        f"(silence={silence_duration:.0f}ms)"
                    )
                    self._silence_start_ms = None
            else:
                self._silence_start_ms = None

            # 检查最长语音时间限制
            if (
                self._state == VADState.SPEECH
                and self._speech_start_ms is not None
            ):
                total_speech = self._current_time_ms - self._speech_start_ms
                if total_speech >= self._config.max_speech_duration_s * 1000:
                    self._state = VADState.SILENCE
                    event = VADEvent(
                        state=VADState.SILENCE,
                        timestamp_ms=self._current_time_ms,
                        confidence=confidence,
                    )
                    logger.warning(
                        f"Speech exceeded max duration "
                        f"({self._config.max_speech_duration_s}s), forcing end"
                    )
                    self._speech_start_ms = None
                    self._silence_start_ms = None

        return event

    def reset(self) -> None:
        """重置 VAD 状态"""
        self._state = VADState.SILENCE
        self._speech_start_ms = None
        self._silence_start_ms = None
        self._current_time_ms = 0.0
        self._samples_processed = 0
        if self._model is not None:
            self._model.reset_states()
        logger.debug("VAD state reset")

    def is_loaded(self) -> bool:
        """模型是否已加载"""
        return self._loaded

    @property
    def current_state(self) -> VADState:
        """当前 VAD 状态"""
        return self._state

    @property
    def current_time_ms(self) -> float:
        """当前处理到的时间（毫秒）"""
        return self._current_time_ms
