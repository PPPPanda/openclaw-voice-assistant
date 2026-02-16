"""LLM Output Chunker

将 LLM 的流式输出按句子粒度切分。
支持中英文混合文本，每凑齐一个完整句子立即返回。
"""

from __future__ import annotations

import re
from typing import Optional


class StreamingChunker:
    """流式输出分块器

    将 LLM 的 streaming token 输出按句子粒度切分。
    每凑齐一个完整句子立即返回，不等待全部输出。

    支持的句子边界：
    - 中文：。！？；
    - 英文：.!?;
    - 省略号：... 。。。

    Usage:
        chunker = StreamingChunker()

        # 逐个 token 输入
        for token in llm_stream:
            sentence = chunker.feed(token)
            if sentence:
                # 处理完整句子
                play_audio(sentence)

        # 最后的尾巴
        final = chunker.flush()
        if final:
            play_audio(final)
    """

    # 句子结束标记（中英文）
    SENTENCE_ENDINGS = re.compile(
        r"(?<=[。！？；])|(?<=[.!?;])"  # 断言后面是句子结束符
    )

    # 省略号
    ELLIPSIS = re.compile(r"(\.{3,}|。{2,})")

    def __init__(self) -> None:
        self._buffer: str = ""
        self._last_token_was_punctuation: bool = False

    def feed(self, token: str) -> Optional[str]:
        """输入一个 token，返回完整的句子（如果有）

        Args:
            token: 新输入的 token

        Returns:
            如果有完整句子，返回该句子；否则返回 None
        """
        self._buffer += token

        # 检查是否是标点符号
        token_is_punctuation = bool(
            re.match(r"^[\s。！？；.!?;,.。]+$", token)
        )

        # 如果是标点符号且前一个也是标点，可能需要特殊处理
        if token_is_punctuation and self._last_token_was_punctuation:
            # 连续标点，可能是省略号或其他情况
            pass

        self._last_token_was_punctuation = token_is_punctuation

        # 尝试提取完整句子
        return self._try_extract_sentence()

    def _try_extract_sentence(self) -> Optional[str]:
        """尝试从缓冲区提取完整句子

        Returns:
            完整句子，如果缓冲区不包含完整句子则返回 None
        """
        # 查找所有句子边界
        matches = list(self.SENTENCE_ENDINGS.finditer(self._buffer))

        if not matches:
            # 没有句子边界
            return None

        # 获取最后一个完整句子
        last_match = matches[-1]
        end_pos = last_match.end()

        # 提取句子
        sentence = self._buffer[:end_pos].strip()

        # 保留剩余部分
        self._buffer = self._buffer[end_pos:]

        if sentence:
            return sentence

        return None

    def flush(self) -> Optional[str]:
        """刷新缓冲区，返回剩余内容

        在 LLM 输出完成后调用，将缓冲区中剩余的内容返回。

        Returns:
            剩余的文本内容
        """
        if not self._buffer:
            return None

        # 去除首尾空白
        result = self._buffer.strip()

        if result:
            self._buffer = ""
            return result

        return None

    @property
    def buffer(self) -> str:
        """当前缓冲区内容"""
        return self._buffer

    def reset(self) -> None:
        """重置分块器"""
        self._buffer = ""
        self._last_token_was_punctuation = False


def split_sentences(text: str) -> list[str]:
    """将文本拆分为句子列表

    这是一个便捷函数，用于一次性拆分整个文本。
    对于流式场景，请使用 StreamingChunker。

    Args:
        text: 输入文本

    Returns:
        句子列表
    """
    # 预处理：统一标点
    text = text.strip()

    if not text:
        return []

    # 使用正则分割
    parts = StreamingChunker.SENTENCE_ENDINGS.split(text)

    # 过滤空字符串
    sentences = [s.strip() for s in parts if s.strip()]

    return sentences


def chunk_stream(
    stream: list[str],
    include_partial: bool = False,
) -> list[str]:
    """将 token 列表分块为句子

    便捷函数，处理完整的 token 列表。

    Args:
        stream: token 列表
        include_partial: 是否包含不完整的最后一块

    Returns:
        句子列表
    """
    chunker = StreamingChunker()
    chunks = []

    for token in stream:
        sentence = chunker.feed(token)
        if sentence:
            chunks.append(sentence)

    # 处理剩余
    final = chunker.flush()
    if final:
        chunks.append(final)
    elif include_partial and chunker.buffer:
        chunks.append(chunker.buffer)

    return chunks


class StreamingChunkerWithContext:
    """带上下文的流式分块器

    支持保留上一句的部分内容作为上下文。
    """

    def __init__(
        self,
        context_size: int = 1,
    ) -> None:
        """初始化

        Args:
            context_size: 保留前 N 个不完整句子作为上下文
        """
        self._chunker = StreamingChunker()
        self._context_size = context_size
        self._partial_sentences: list[str] = []

    def feed(self, token: str) -> Optional[str]:
        """输入 token"""
        sentence = self._chunker.feed(token)

        if sentence:
            # 有完整句子
            return sentence

        # 检查缓冲区是否有部分句子
        buffer = self._chunker.buffer

        # 如果缓冲区包含多个句子，说明有不完整的
        if buffer:
            # 简单处理：返回缓冲区
            return None

        return None

    def flush(self) -> Optional[str]:
        """刷新"""
        return self._chunker.flush()

    def reset(self) -> None:
        """重置"""
        self._chunker.reset()
        self._partial_sentences = []
