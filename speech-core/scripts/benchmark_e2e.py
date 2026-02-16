"""E2E Latency Benchmark

端到端延迟测试：测量 STT + Mock LLM + TTS 各阶段耗时。
使用合成音频模拟用户说话。
输出 P50/P95 统计。
"""

from __future__ import annotations

import argparse
import asyncio
import time
import numpy as np
from dataclasses import dataclass, field
from typing import AsyncIterator

from speech_core.interfaces import (
    AudioData,
    AudioFormat,
    ConversationState,
    SpeechEvent,
    STTOptions,
    TTSChunk,
    TTSOptions,
)
from speech_core.pipeline.speech_pipeline import SpeechPipeline
from speech_core.stt.engine import BaseSTTEngine
from speech_core.tts.engine import BaseTTSEngine


@dataclass
class StageLatency:
    """各阶段延迟"""
    vad_detection_ms: float = 0.0
    stt_transcribe_ms: float = 0.0
    llm_process_ms: float = 0.0
    tts_synthesize_ms: float = 0.0
    total_ms: float = 0.0


@dataclass
class BenchmarkRun:
    """单次基准测试结果"""
    stage_latency: StageLatency
    text_transcribed: str = ""
    text_response: str = ""
    success: bool = True
    error: str = ""


def generate_speech_audio(
    duration_s: float = 3.0,
    sample_rate: int = 16000,
) -> bytes:
    """生成模拟语音音频

    Args:
        duration_s: 音频时长（秒）
        sample_rate: 采样率

    Returns:
        PCM s16le 格式音频数据
    """
    t = np.linspace(0, duration_s, int(sample_rate * duration_s))

    # 模拟语音频谱（多频率混合）
    fundamental = 150  # 基频
    audio = np.zeros_like(t)
    for i in range(1, 6):
        audio += np.sin(2 * np.pi * fundamental * i * t) * (0.3 / i)

    # 添加噪声
    noise = np.random.normal(0, 0.02, len(t))

    # 包络（模拟语音的起伏）
    envelope = np.exp(-((t - duration_s / 2) ** 2) / (duration_s / 4))
    audio = audio * envelope + noise

    # 归一化并转换
    audio = np.clip(audio, -1.0, 1.0)
    audio_int16 = (audio * 32767).astype(np.int16)

    return audio_int16.tobytes()


class MockSTTEngine(BaseSTTEngine):
    """Mock STT 引擎（用于测试）"""

    def __init__(self, latency_ms: int = 50) -> None:
        super().__init__(name="mock-stt")
        self._latency_ms = latency_ms

    async def load_model(self, model_name: str) -> None:
        self._loaded = True

    async def transcribe(self, audio: AudioData, options: STTOptions) -> "STTResult":
        await asyncio.sleep(self._latency_ms / 1000)
        from speech_core.interfaces import Segment, STTResult
        return STTResult(
            text="hello world test",
            language="en",
            confidence=0.95,
            segments=[Segment(start=0.0, end=2.5, text="hello world test")],
            processing_time_ms=self._latency_ms,
        )

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        options: STTOptions,
    ) -> AsyncIterator[STTResult]:
        # Mock 实现
        result = await self.transcribe(AudioData(AudioFormat.PCM_S16LE, 16000, 1, b""), options)
        yield result


class MockTTSEngine(BaseTTSEngine):
    """Mock TTS 引擎（用于测试）"""

    def __init__(self, latency_ms: int = 100, chunk_size: int = 5) -> None:
        super().__init__(name="mock-tts")
        self._latency_ms = latency_ms
        self._chunk_size = chunk_size

    async def load_model(self, voice: str) -> None:
        self._loaded = True

    async def synthesize(self, text: str, options: TTSOptions) -> "TTSResult":
        await asyncio.sleep(self._latency_ms / 1000)
        from speech_core.interfaces import AudioData, TTSResult
        # 生成静音/噪声作为合成音频
        audio_data = np.random.randint(-1000, 1000, 1600, dtype=np.int16).tobytes()
        return TTSResult(
            audio=AudioData(
                format=AudioFormat.PCM_S16LE,
                sample_rate=16000,
                channels=1,
                data=audio_data,
            ),
            processing_time_ms=self._latency_ms,
        )

    async def synthesize_stream(
        self,
        text: str,
        options: TTSOptions,
    ) -> AsyncIterator[TTSChunk]:
        # 流式返回
        for i in range(self._chunk_size):
            await asyncio.sleep(self._latency_ms / 1000 / self._chunk_size)
            audio_data = np.random.randint(-1000, 1000, 800, dtype=np.int16).tobytes()
            yield TTSChunk(
                index=i,
                audio=audio_data,
                duration_ms=50.0,
                final=i == self._chunk_size - 1,
            )


async def mock_llm(text: str) -> str:
    """Mock LLM 处理

    Args:
        text: 输入文本

    Returns:
        Mock 响应文本
    """
    # 模拟 LLM 处理延迟
    await asyncio.sleep(0.05)
    # 简单的 mock 响应
    return f"You said: {text}"


async def run_e2e_benchmark(
    stt_engine: BaseSTTEngine,
    tts_engine: BaseTTSEngine,
    audio_data: bytes,
    sample_rate: int,
) -> BenchmarkRun:
    """运行单次 E2E 基准测试

    Args:
        stt_engine: STT 引擎
        tts_engine: TTS 引擎
        audio_data: 测试音频
        sample_rate: 采样率

    Returns:
        基准测试结果
    """
    start_time = time.monotonic()
    stage_latency = StageLatency()
    result = BenchmarkRun()

    try:
        # 创建 Pipeline
        from speech_core.vad.silero import SileroVAD
        from speech_core.interfaces import VADConfig

        vad = SileroVAD(VADConfig(
            min_speech_duration_ms=100,
            min_silence_duration_ms=200,
        ))
        await vad.load_model()

        pipeline = SpeechPipeline(stt_engine, tts_engine, vad=vad)

        # 回调
        transcribed_text = ""
        async def on_transcription(result, user_id, channel_id):
            nonlocal transcribed_text
            transcribed_text = result.text

        pipeline.on_transcription = on_transcription

        # 模拟音频输入
        # 将音频分成小块输入
        chunk_size = 512  # 32ms at 16kHz
        audio_chunks = [
            audio_data[i:i + chunk_size]
            for i in range(0, len(audio_data), chunk_size)
        ]

        # VAD 检测阶段
        vad_start = time.monotonic()
        for chunk in audio_chunks[:20]:  # 只用前 20 个块测试
            vad.process_chunk(chunk)
        stage_latency.vad_detection_ms = (time.monotonic() - vad_start) * 1000

        # STT 阶段
        stt_start = time.monotonic()
        audio = AudioData(
            format=AudioFormat.PCM_S16LE,
            sample_rate=sample_rate,
            channels=1,
            data=audio_data,
        )
        stt_result = await stt_engine.transcribe(audio, STTOptions())
        stage_latency.stt_transcribe_ms = (time.monotonic() - stt_start) * 1000

        result.text_transcribed = stt_result.text
        stage_latency.stt_transcribe_ms = stt_result.processing_time_ms

        # LLM 阶段
        llm_start = time.monotonic()
        llm_response = await mock_llm(stt_result.text)
        stage_latency.llm_process_ms = (time.monotonic() - llm_start) * 1000
        result.text_response = llm_response

        # TTS 阶段
        tts_start = time.monotonic()
        tts_result = await tts_engine.synthesize(llm_response, TTSOptions())
        stage_latency.tts_synthesize_ms = (time.monotonic() - tts_start) * 1000

        stage_latency.total_ms = (time.monotonic() - start_time) * 1000
        result.success = True

    except Exception as e:
        result.success = False
        result.error = str(e)

    result.stage_latency = stage_latency
    return result


def calculate_percentile(values: list[float], percentile: float) -> float:
    """计算百分位数

    Args:
        values: 数值列表
        percentile: 百分位 (0-100)

    Returns:
        百分位数值
    """
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = int(len(sorted_values) * percentile / 100)
    return sorted_values[min(index, len(sorted_values) - 1)]


async def main():
    parser = argparse.ArgumentParser(description="E2E Latency Benchmark")
    parser.add_argument(
        "--runs",
        type=int,
        default=10,
        help="测试轮次",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=3.0,
        help="测试音频时长（秒）",
    )
    parser.add_argument(
        "--stt-latency",
        type=int,
        default=50,
        help="Mock STT 延迟（毫秒）",
    )
    parser.add_argument(
        "--tts-latency",
        type=int,
        default=100,
        help="Mock TTS 延迟（毫秒）",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("E2E Latency Benchmark")
    print("=" * 60)

    # 生成测试音频
    sample_rate = 16000
    audio_data = generate_speech_audio(args.duration, sample_rate)
    print(f"\nTest audio: {args.duration}s, {len(audio_data)} bytes")

    # 创建引擎
    stt_engine = MockSTTEngine(latency_ms=args.stt_latency)
    tts_engine = MockTTSEngine(latency_ms=args.tts_latency)

    # 加载模型
    print("Loading engines...")
    await stt_engine.load_model("tiny")
    await tts_engine.load_model("zh_CN-huayan-medium")

    # 运行基准测试
    print(f"\nRunning {args.runs} benchmark iterations...")
    results: list[BenchmarkRun] = []

    for i in range(args.runs):
        result = await run_e2e_benchmark(
            stt_engine,
            tts_engine,
            audio_data,
            sample_rate,
        )
        results.append(result)
        status = "✓" if result.success else "✗"
        print(f"  Run {i + 1}/{args.runs}: {status} "
              f"Total: {result.stage_latency.total_ms:.0f}ms")

    # 统计
    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)

    # 提取各阶段延迟
    vad_times = [r.stage_latency.vad_detection_ms for r in results if r.success]
    stt_times = [r.stage_latency.stt_transcribe_ms for r in results if r.success]
    llm_times = [r.stage_latency.llm_process_ms for r in results if r.success]
    tts_times = [r.stage_latency.tts_synthesize_ms for r in results if r.success]
    total_times = [r.stage_latency.total_ms for r in results if r.success]

    def print_stats(name: str, values: list[float]):
        if values:
            print(f"  {name}:")
            print(f"    - Mean: {np.mean(values):.1f}ms")
            print(f"    - P50:  {calculate_percentile(values, 50):.1f}ms")
            print(f"    - P95:  {calculate_percentile(values, 95):.1f}ms")
            print(f"    - P99:  {calculate_percentile(values, 99):.1f}ms")
            print(f"    - Min:  {min(values):.1f}ms")
            print(f"    - Max:  {max(values):.1f}ms")

    print_stats("VAD Detection", vad_times)
    print_stats("STT Transcribe", stt_times)
    print_stats("LLM Process", llm_times)
    print_stats("TTS Synthesize", tts_times)
    print_stats("Total E2E", total_times)

    # 成功率
    success_count = sum(1 for r in results if r.success)
    print(f"\nSuccess Rate: {success_count}/{args.runs} ({success_count / args.runs * 100:.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())
