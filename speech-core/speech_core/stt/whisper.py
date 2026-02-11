"""faster-whisper STT 引擎实现

使用 CTranslate2 加速的 Whisper 模型，支持 GPU/CPU 推理。
参考：https://github.com/guillaumekln/faster-whisper
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

import numpy as np

from speech_core.interfaces import (
    AudioData,
    AudioFormat,
    Segment,
    STTOptions,
    STTResult,
)
from speech_core.stt.engine import BaseSTTEngine

logger = logging.getLogger(__name__)


class FasterWhisperEngine(BaseSTTEngine):
    """faster-whisper STT 引擎

    基于 CTranslate2 的高性能 Whisper 实现。
    GPU 模式下 base 模型延迟约 200-500ms。
    """

    def __init__(
        self,
        device: str = "auto",
        compute_type: str = "auto",
    ) -> None:
        super().__init__(name="faster-whisper")
        self._device = device
        self._compute_type = compute_type
        self._model = None
        self._model_name: str | None = None

    async def load_model(self, model_name: str) -> None:
        """加载 faster-whisper 模型

        Args:
            model_name: 模型大小 ('tiny', 'base', 'small', 'medium', 'large-v3')
        """
        if self._loaded and self._model_name == model_name:
            logger.info(f"Model {model_name} already loaded")
            return

        logger.info(f"Loading faster-whisper model: {model_name} (device={self._device})")
        start = time.monotonic()

        def _load():
            from faster_whisper import WhisperModel

            device = self._device
            compute_type = self._compute_type

            if device == "auto":
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"

            if compute_type == "auto":
                compute_type = "float16" if device == "cuda" else "int8"

            return WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
            )

        loop = asyncio.get_event_loop()
        self._model = await loop.run_in_executor(None, _load)
        self._model_name = model_name
        self._loaded = True

        elapsed = (time.monotonic() - start) * 1000
        logger.info(f"faster-whisper model loaded in {elapsed:.0f}ms")

    async def transcribe(self, audio: AudioData, options: STTOptions) -> STTResult:
        """转写音频

        Args:
            audio: PCM s16le 音频数据
            options: 转写选项

        Returns:
            转写结果
        """
        if not self._loaded or self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        start = time.monotonic()

        # 将 PCM bytes 转换为 float32 numpy array
        audio_array = np.frombuffer(audio.data, dtype=np.int16).astype(np.float32) / 32768.0

        # 如果不是 16kHz，需要重采样
        if audio.sample_rate != 16000:
            audio_array = self._resample(audio_array, audio.sample_rate, 16000)

        # 在线程池中运行转写（避免阻塞事件循环）
        loop = asyncio.get_event_loop()

        language = options.language if options.language != "auto" else None

        def _transcribe():
            segments_gen, info = self._model.transcribe(
                audio_array,
                language=language,
                beam_size=5,
                vad_filter=options.vad_enabled,
                vad_parameters={
                    "threshold": options.vad_threshold,
                    "min_silence_duration_ms": 500,
                },
            )
            segments = list(segments_gen)
            return segments, info

        segments, info = await loop.run_in_executor(None, _transcribe)

        elapsed_ms = int((time.monotonic() - start) * 1000)

        # 组装结果
        result_segments = [
            Segment(start=seg.start, end=seg.end, text=seg.text.strip())
            for seg in segments
        ]

        full_text = " ".join(seg.text for seg in result_segments)

        # 计算平均概率作为置信度
        avg_confidence = 0.0
        if segments:
            avg_confidence = sum(
                getattr(seg, "avg_logprob", -0.5) for seg in segments
            ) / len(segments)
            # 将 log prob 转换为大致概率
            avg_confidence = max(0.0, min(1.0, 1.0 + avg_confidence))

        result = STTResult(
            text=full_text,
            language=info.language if info.language else "unknown",
            confidence=avg_confidence,
            segments=result_segments,
            processing_time_ms=elapsed_ms,
        )

        logger.info(
            f"STT complete: {elapsed_ms}ms, lang={result.language}, "
            f"text='{full_text[:50]}...'" if len(full_text) > 50 else
            f"STT complete: {elapsed_ms}ms, lang={result.language}, text='{full_text}'"
        )

        return result

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        options: STTOptions,
    ) -> AsyncIterator[STTResult]:
        """流式转写

        当前实现：缓冲完整音频后转写。
        TODO: Phase 3 实现真正的实时流式转写。
        """
        chunks: list[bytes] = []
        async for chunk in audio_stream:
            chunks.append(chunk)

        if not chunks:
            return

        combined = b"".join(chunks)
        audio = AudioData(
            format=AudioFormat.PCM_S16LE,
            sample_rate=16000,
            channels=1,
            data=combined,
        )

        result = await self.transcribe(audio, options)
        yield result

    @staticmethod
    def _resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """简单的线性重采样"""
        if orig_sr == target_sr:
            return audio

        duration = len(audio) / orig_sr
        target_length = int(duration * target_sr)
        indices = np.linspace(0, len(audio) - 1, target_length)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)
