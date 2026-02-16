"""STT Benchmark Script

测试 faster-whisper 不同模型的加载时间和推理延迟。
使用合成音频（正弦波 + 噪声）作为测试输入。
自动检测 CUDA 可用性。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class BenchmarkResult:
    """单个模型的基准测试结果"""
    model_name: str
    device: str
    load_time_ms: float
    inference_time_ms: float
    rtf: float  # Real-Time Factor (音频时长 / 推理时间)
    audio_duration_s: float


def generate_test_audio(
    duration_s: float = 3.0,
    sample_rate: int = 16000,
) -> bytes:
    """生成测试音频（正弦波 + 噪声）

    Args:
        duration_s: 音频时长（秒）
        sample_rate: 采样率

    Returns:
        PCM s16le 格式音频数据
    """
    t = np.linspace(0, duration_s, int(sample_rate * duration_s))

    # 混合频率的正弦波（模拟人声频谱）
    sine1 = np.sin(2 * np.pi * 200 * t) * 0.3
    sine2 = np.sin(2 * np.pi * 400 * t) * 0.2
    sine3 = np.sin(2 * np.pi * 600 * t) * 0.1

    # 添加噪声
    noise = np.random.normal(0, 0.05, len(t))

    # 混合并归一化
    audio = sine1 + sine2 + sine3 + noise
    audio = np.clip(audio, -1.0, 1.0)

    # 转换为 int16
    audio_int16 = (audio * 32767).astype(np.int16)

    return audio_int16.tobytes()


def check_cuda_available() -> bool:
    """检测 CUDA 是否可用"""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


async def benchmark_model(
    model_name: str,
    audio_data: bytes,
    sample_rate: int,
    compute_type: str = "auto",
) -> BenchmarkResult:
    """测试单个模型的性能

    Args:
        model_name: 模型名称 (tiny/base/small/medium)
        audio_data: 测试音频数据
        sample_rate: 采样率
        compute_type: 计算类型

    Returns:
        基准测试结果
    """
    import torch
    from faster_whisper import WhisperModel

    # 确定设备
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"

    print(f"\n  Loading model: {model_name} (device={device}, compute={compute_type})")

    # 加载模型
    load_start = time.monotonic()
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    load_time_ms = (time.monotonic() - load_start) * 1000

    # 准备音频
    audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

    # 推理
    inference_start = time.monotonic()
    segments, info = model.transcribe(
        audio_array,
        language="en",  # 强制英文以加快检测
        beam_size=5,
        vad_filter=False,  # 关闭 VAD 加速测试
    )
    # 强制执行生成器
    segments = list(segments)
    inference_time_ms = (time.monotonic() - inference_start) * 1000

    # 计算 RTF
    audio_duration_s = len(audio_array) / sample_rate
    rtf = audio_duration_s / (inference_time_ms / 1000)

    return BenchmarkResult(
        model_name=model_name,
        device=device,
        load_time_ms=load_time_ms,
        inference_time_ms=inference_time_ms,
        rtf=rtf,
        audio_duration_s=audio_duration_s,
    )


def format_table(results: list[BenchmarkResult]) -> str:
    """格式化结果表格"""
    # 表头
    header = f"{'Model':<10} {'Device':<8} {'Load Time':<12} {'Inference':<12} {'RTF':<8} {'Audio Len':<10}"
    separator = "-" * len(header)

    lines = [header, separator]

    # 数据行
    for r in results:
        line = (
            f"{r.model_name:<10} "
            f"{r.device:<8} "
            f"{r.load_time_ms:>8.0f} ms  "
            f"{r.inference_time_ms:>8.0f} ms  "
            f"{r.rtf:>7.2f}x "
            f"{r.audio_duration_s:>7.1f} s  "
        )
        lines.append(line)

    return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser(description="STT Benchmark Script")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["tiny", "base", "small", "medium"],
        choices=["tiny", "base", "small", "medium"],
        help="要测试的模型列表",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=3.0,
        help="测试音频时长（秒）",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        help="音频采样率",
    )
    parser.add_argument(
        "--compute-type",
        default="auto",
        choices=["auto", "int8", "float16"],
        help="计算类型",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("STT Benchmark - faster-whisper Model Performance")
    print("=" * 60)

    # 检测 CUDA
    cuda_available = check_cuda_available()
    print(f"\nCUDA Available: {cuda_available}")

    # 生成测试音频
    print(f"\nGenerating test audio: {args.duration}s, {args.sample_rate}Hz")
    audio_data = generate_test_audio(args.duration, args.sample_rate)
    print(f"Audio size: {len(audio_data)} bytes")

    # 运行基准测试
    results: list[BenchmarkResult] = []

    for model_name in args.models:
        try:
            result = await benchmark_model(
                model_name,
                audio_data,
                args.sample_rate,
                args.compute_type,
            )
            results.append(result)
            print(f"  -> Load: {result.load_time_ms:.0f}ms, "
                  f"Inference: {result.inference_time_ms:.0f}ms, "
                  f"RTF: {result.rtf:.2f}x")
        except Exception as e:
            print(f"  -> Error: {e}")

    # 打印结果表格
    if results:
        print("\n" + "=" * 60)
        print("Results Summary")
        print("=" * 60)
        print(format_table(results))

        # 统计信息
        print("\nStatistics:")
        print(f"  - Fastest load: {min(r.load_time_ms for r in results):.0f}ms ({min(results, key=lambda r: r.load_time_ms).model_name})")
        print(f"  - Fastest inference: {min(r.inference_time_ms for r in results):.0f}ms ({min(results, key=lambda r: r.inference_time_ms).model_name})")
        print(f"  - Best RTF: {max(r.rtf for r in results):.2f}x ({max(results, key=lambda r: r.rtf).model_name})")
    else:
        print("\nNo results - all models failed to load.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
