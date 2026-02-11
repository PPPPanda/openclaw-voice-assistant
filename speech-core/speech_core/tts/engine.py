"""TTS 引擎抽象基类"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import AsyncIterator

from speech_core.interfaces import TTSChunk, TTSOptions, TTSResult

logger = logging.getLogger(__name__)

# 句子分割正则：中英文句号、问号、感叹号、分号
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[。！？；.!?;])\s*")


class BaseTTSEngine(ABC):
    """TTS 引擎抽象基类

    所有 TTS 引擎实现（Piper, ElevenLabs 等）都应继承此类。
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._loaded = False

    @property
    def name(self) -> str:
        return self._name

    @abstractmethod
    async def load_model(self, voice: str) -> None:
        """加载语音模型

        Args:
            voice: 语音名称/ID
        """
        ...

    @abstractmethod
    async def synthesize(self, text: str, options: TTSOptions) -> TTSResult:
        """同步合成完整音频

        Args:
            text: 要合成的文本
            options: 合成选项

        Returns:
            合成结果
        """
        ...

    async def synthesize_stream(
        self,
        text: str,
        options: TTSOptions,
    ) -> AsyncIterator[TTSChunk]:
        """流式合成（句子级分块）

        默认实现：按句子拆分文本，逐句合成。
        子类可覆盖以提供更细粒度的流式实现。

        Args:
            text: 要合成的文本
            options: 合成选项

        Yields:
            TTS 音频块
        """
        sentences = self.split_sentences(text)
        for i, sentence in enumerate(sentences):
            if not sentence.strip():
                continue

            result = await self.synthesize(sentence, options)
            is_final = i == len(sentences) - 1

            yield TTSChunk(
                index=i,
                audio=result.audio.data,
                duration_ms=result.audio.duration_ms,
                final=is_final,
            )

    @staticmethod
    def split_sentences(text: str) -> list[str]:
        """将文本拆分为句子

        支持中英文标点分割。

        Args:
            text: 输入文本

        Returns:
            句子列表
        """
        sentences = SENTENCE_SPLIT_PATTERN.split(text)
        return [s for s in sentences if s.strip()]

    def is_loaded(self) -> bool:
        """模型是否已加载"""
        return self._loaded

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self._name}, loaded={self._loaded})>"
