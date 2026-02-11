"""whisper.cpp STT 引擎实现

基于 whisper.cpp 的 CPU 优化 Whisper 实现。
作为 faster-whisper 的 CPU 环境备选方案。
参考：https://github.com/ggerganov/whisper.cpp
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
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


class WhisperCppEngine(BaseSTTEngine):
    """whisper.cpp STT 引擎

    通过调用 whisper-cli 命令行工具实现转写。
    适用于纯 CPU 环境，延迟约 300-800ms。
    """

    def __init__(self, cli_path: str | None = None) -> None:
        super().__init__(name="whisper.cpp")
        self._cli_path: str | None = cli_path
        self._model_path: str | None = None

    async def load_model(self, model_name: str) -> None:
        """检测 whisper.cpp CLI 并准备模型

        Args:
            model_name: 模型名称（需要是 ggml 格式模型文件路径或名称）
        """
        # 查找 CLI 工具
        if self._cli_path is None:
            for cmd in ["whisper-cli", "whisper-cpp", "main"]:
                found = shutil.which(cmd)
                if found:
                    self._cli_path = found
                    break

        if self._cli_path is None:
            raise FileNotFoundError(
                "whisper.cpp CLI not found. Install whisper.cpp and ensure "
                "'whisper-cli' is in PATH."
            )

        # 检查模型文件
        model_path = Path(model_name)
        if model_path.exists():
            self._model_path = str(model_path)
        else:
            # 尝试常见路径
            common_paths = [
                Path.home() / ".cache" / "whisper" / f"ggml-{model_name}.bin",
                Path("models") / f"ggml-{model_name}.bin",
            ]
            for p in common_paths:
                if p.exists():
                    self._model_path = str(p)
                    break

        if self._model_path is None:
            logger.warning(
                f"Model file not found for '{model_name}'. "
                "Will pass model name directly to CLI."
            )
            self._model_path = model_name

        self._loaded = True
        logger.info(f"whisper.cpp ready: cli={self._cli_path}, model={self._model_path}")

    async def transcribe(self, audio: AudioData, options: STTOptions) -> STTResult:
        """通过 whisper.cpp CLI 转写音频"""
        if not self._loaded:
            raise RuntimeError("Engine not loaded. Call load_model() first.")

        start = time.monotonic()

        # 将音频写入临时 WAV 文件
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name
            self._write_wav(f, audio)

        try:
            # 构建命令
            cmd = [
                self._cli_path,
                "-m", self._model_path,
                "-f", temp_path,
                "--output-json",
                "--no-timestamps",
            ]

            if options.language != "auto":
                cmd.extend(["-l", options.language])

            # 在线程池中运行 CLI
            loop = asyncio.get_event_loop()

            def _run():
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return result

            proc = await loop.run_in_executor(None, _run)

            elapsed_ms = int((time.monotonic() - start) * 1000)

            if proc.returncode != 0:
                logger.error(f"whisper.cpp failed: {proc.stderr}")
                return STTResult(
                    text="",
                    language="unknown",
                    confidence=0.0,
                    segments=[],
                    processing_time_ms=elapsed_ms,
                )

            # 解析输出
            text = proc.stdout.strip()

            return STTResult(
                text=text,
                language=options.language if options.language != "auto" else "unknown",
                confidence=0.8,  # whisper.cpp 不返回置信度
                segments=[Segment(start=0.0, end=0.0, text=text)] if text else [],
                processing_time_ms=elapsed_ms,
            )

        finally:
            Path(temp_path).unlink(missing_ok=True)

    @staticmethod
    def _write_wav(f, audio: AudioData) -> None:  # type: ignore[no-untyped-def]
        """将 PCM 数据写为 WAV 文件"""
        import struct

        data = audio.data
        sample_rate = audio.sample_rate
        channels = audio.channels
        bits_per_sample = 16

        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8
        data_size = len(data)

        # WAV header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 1))  # PCM
        f.write(struct.pack("<H", channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", bits_per_sample))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(data)
