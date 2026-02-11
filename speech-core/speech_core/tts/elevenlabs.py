"""ElevenLabs TTS 云端实现

高质量云端 TTS 备选方案。
参考：https://docs.elevenlabs.io/
"""

from __future__ import annotations

import asyncio
import logging
import time
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


class ElevenLabsTTSEngine(BaseTTSEngine):
    """ElevenLabs TTS 云端引擎

    高质量语音合成，延迟 300-800ms。
    需要 API Key。
    """

    def __init__(self, api_key: str, default_voice_id: str = "") -> None:
        super().__init__(name="elevenlabs")
        self._api_key = api_key
        self._default_voice_id = default_voice_id
        self._client = None

    async def load_model(self, voice: str) -> None:
        """初始化 ElevenLabs 客户端

        Args:
            voice: 语音 ID
        """
        if not self._api_key:
            raise ValueError("ElevenLabs API key not configured")

        logger.info(f"Initializing ElevenLabs client with voice: {voice}")

        try:
            from elevenlabs.client import AsyncElevenLabs

            self._client = AsyncElevenLabs(api_key=self._api_key)
            self._default_voice_id = voice
            self._loaded = True
            logger.info("ElevenLabs client initialized")
        except ImportError:
            logger.error(
                "elevenlabs package not installed. "
                "Install with: pip install 'openclaw-speech-core[elevenlabs]'"
            )
            raise

    async def synthesize(self, text: str, options: TTSOptions) -> TTSResult:
        """通过 ElevenLabs API 合成语音"""
        if not self._loaded or self._client is None:
            raise RuntimeError("ElevenLabs not initialized. Call load_model() first.")

        start = time.monotonic()

        voice_id = self._default_voice_id

        try:
            audio_generator = await self._client.generate(
                text=text,
                voice=voice_id,
                model="eleven_multilingual_v2",
            )

            # 收集所有音频数据
            audio_chunks: list[bytes] = []
            async for chunk in audio_generator:
                audio_chunks.append(chunk)

            audio_data = b"".join(audio_chunks)
            elapsed_ms = int((time.monotonic() - start) * 1000)

            audio = AudioData(
                format=AudioFormat.MP3,
                sample_rate=44100,
                channels=1,
                data=audio_data,
            )

            result = TTSResult(audio=audio, processing_time_ms=elapsed_ms)
            logger.info(f"ElevenLabs TTS: {elapsed_ms}ms, {len(audio_data)} bytes")
            return result

        except Exception:
            logger.exception("ElevenLabs TTS failed")
            raise

    async def synthesize_stream(
        self,
        text: str,
        options: TTSOptions,
    ) -> AsyncIterator[TTSChunk]:
        """ElevenLabs 流式合成"""
        if not self._loaded or self._client is None:
            raise RuntimeError("ElevenLabs not initialized. Call load_model() first.")

        voice_id = self._default_voice_id

        try:
            audio_generator = await self._client.generate(
                text=text,
                voice=voice_id,
                model="eleven_multilingual_v2",
                stream=True,
            )

            index = 0
            async for chunk in audio_generator:
                yield TTSChunk(
                    index=index,
                    audio=chunk,
                    duration_ms=0,  # 流式模式下无法精确计算
                    final=False,
                )
                index += 1

            # 发送最终标记
            yield TTSChunk(
                index=index,
                audio=b"",
                duration_ms=0,
                final=True,
            )

        except Exception:
            logger.exception("ElevenLabs streaming TTS failed")
            raise
