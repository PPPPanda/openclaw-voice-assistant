"""STT 引擎抽象基类"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator

from speech_core.interfaces import AudioData, STTOptions, STTResult

logger = logging.getLogger(__name__)


class BaseSTTEngine(ABC):
    """STT 引擎抽象基类

    所有 STT 引擎实现（faster-whisper, whisper.cpp 等）都应继承此类。
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._loaded = False

    @property
    def name(self) -> str:
        return self._name

    @abstractmethod
    async def load_model(self, model_name: str) -> None:
        """加载指定模型

        Args:
            model_name: 模型名称（如 'tiny', 'base', 'small', 'medium', 'large'）
        """
        ...

    @abstractmethod
    async def transcribe(self, audio: AudioData, options: STTOptions) -> STTResult:
        """同步转写整段音频

        Args:
            audio: 音频数据（PCM s16le）
            options: 转写选项

        Returns:
            转写结果
        """
        ...

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        options: STTOptions,
    ) -> AsyncIterator[STTResult]:
        """流式转写

        默认实现：收集所有音频后调用同步转写。
        子类可覆盖以提供真正的流式实现。

        Args:
            audio_stream: 音频流（PCM s16le chunks）
            options: 转写选项

        Yields:
            转写结果（增量或最终）
        """
        # 默认实现：缓冲所有数据后一次性转写
        chunks: list[bytes] = []
        async for chunk in audio_stream:
            chunks.append(chunk)

        if not chunks:
            return

        combined = b"".join(chunks)
        audio = AudioData(
            format=AudioData.__dataclass_fields__["format"].default
            if hasattr(AudioData.__dataclass_fields__["format"], "default")
            else "pcm_s16le",
            sample_rate=16000,
            channels=1,
            data=combined,
        )

        from speech_core.interfaces import AudioFormat

        audio = AudioData(
            format=AudioFormat.PCM_S16LE,
            sample_rate=16000,
            channels=1,
            data=combined,
        )

        result = await self.transcribe(audio, options)
        yield result

    def is_loaded(self) -> bool:
        """模型是否已加载"""
        return self._loaded

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self._name}, loaded={self._loaded})>"
