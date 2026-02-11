"""Piper TTS 引擎实现

基于 Piper 的本地 TTS 引擎，延迟低、无需 GPU。
参考：https://github.com/rhasspy/piper
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
import wave
from typing import AsyncIterator

from speech_core.interfaces import (
    AudioData,
    AudioFormat,
    TTSChunk,
    TTSOptions,
    TTSResult,
)
from speech_core.tts.engine import BaseTTSEngine

logger = logging.getLogger(__name__)


class PiperTTSEngine(BaseTTSEngine):
    """Piper TTS 引擎

    本地 TTS 方案，延迟约 200-500ms，音质中等。
    支持多种语言和语音角色。
    """

    def __init__(self) -> None:
        super().__init__(name="piper")
        self._voice: str | None = None
        self._piper = None

    async def load_model(self, voice: str) -> None:
        """加载 Piper 语音模型

        Args:
            voice: 语音名称（如 'zh_CN-huayan-medium'）或完整路径
        """
        if self._loaded and self._voice == voice:
            logger.info(f"Piper voice {voice} already loaded")
            return

        logger.info(f"Loading Piper voice: {voice}")
        start = time.monotonic()

        loop = asyncio.get_event_loop()

        def _load():
            import os
            from pathlib import Path
            from piper import PiperVoice

            # 查找模型文件
            model_path = voice
            
            # 如果不是完整路径，在标准目录中查找
            if not os.path.exists(voice) and not os.path.exists(f"{voice}.onnx"):
                search_dirs = [
                    Path.home() / ".local/share/piper-voices",
                    Path("/usr/share/piper-voices"),
                    Path.cwd(),
                ]
                for search_dir in search_dirs:
                    candidate = search_dir / f"{voice}.onnx"
                    if candidate.exists():
                        model_path = str(candidate)
                        logger.info(f"Found model at: {model_path}")
                        break
                else:
                    logger.warning(f"Model {voice} not found in standard paths, trying as-is")

            return PiperVoice.load(model_path)

        try:
            self._piper = await loop.run_in_executor(None, _load)
            self._voice = voice
            self._loaded = True
            elapsed = (time.monotonic() - start) * 1000
            logger.info(f"Piper voice loaded in {elapsed:.0f}ms")
        except ImportError:
            logger.error(
                "piper-tts not installed. Install with: pip install piper-tts"
            )
            raise
        except Exception:
            logger.exception(f"Failed to load Piper voice: {voice}")
            raise

    async def synthesize(self, text: str, options: TTSOptions) -> TTSResult:
        """合成语音

        Args:
            text: 要合成的文本
            options: 合成选项

        Returns:
            合成结果（PCM s16le, 22050Hz）
        """
        if not self._loaded or self._piper is None:
            raise RuntimeError("Piper not loaded. Call load_model() first.")

        start = time.monotonic()
        loop = asyncio.get_event_loop()

        def _synthesize():
            from piper.config import SynthesisConfig
            
            # 创建合成配置
            syn_config = SynthesisConfig(
                length_scale=1.0 / options.speed if options.speed > 0 else 1.0,
            )
            
            # synthesize 返回 AudioChunk 迭代器
            audio_chunks = list(self._piper.synthesize(text, syn_config))
            
            # 合并所有音频数据（使用 audio_int16_bytes）
            pcm_data = b"".join(chunk.audio_int16_bytes for chunk in audio_chunks)
            sample_rate = self._piper.config.sample_rate
            channels = 1  # Piper 输出单声道

            return pcm_data, sample_rate, channels

        pcm_data, sample_rate, channels = await loop.run_in_executor(None, _synthesize)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        audio = AudioData(
            format=AudioFormat.PCM_S16LE,
            sample_rate=sample_rate,
            channels=channels,
            data=pcm_data,
        )

        result = TTSResult(audio=audio, processing_time_ms=elapsed_ms)

        logger.info(
            f"TTS complete: {elapsed_ms}ms, "
            f"{audio.duration_ms:.0f}ms audio, "
            f"text='{text[:30]}...'" if len(text) > 30 else
            f"TTS complete: {elapsed_ms}ms, {audio.duration_ms:.0f}ms audio, text='{text}'"
        )

        return result

    async def synthesize_stream(
        self,
        text: str,
        options: TTSOptions,
    ) -> AsyncIterator[TTSChunk]:
        """流式合成（句子级）

        将文本拆分成句子，逐句合成并输出。
        """
        sentences = self.split_sentences(text)
        if not sentences:
            return

        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence:
                continue

            result = await self.synthesize(sentence, options)
            is_final = i == len(sentences) - 1

            yield TTSChunk(
                index=i,
                audio=result.audio.data,
                duration_ms=result.audio.duration_ms,
                final=is_final,
            )
