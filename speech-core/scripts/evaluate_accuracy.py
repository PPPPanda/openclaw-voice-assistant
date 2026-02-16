"""STT Accuracy Evaluation

评估 STT 准确率：计算 WER (Word Error Rate) 和 CER (Character Error Rate)。
支持中文和英文测试。
从 tests/fixtures/audio/ 读取测试音频。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class TestSample:
    """单个测试样本"""
    audio_file: str
    reference_text: str
    language: str


@dataclass
class EvaluationResult:
    """单个样本的评估结果"""
    sample: TestSample
    transcribed_text: str
    wer: float = 0.0  # Word Error Rate
    cer: float = 0.0  # Character Error Rate
    words_matched: int = 0
    words_total: int = 0
    chars_matched: int = 0
    chars_total: int = 0


def levenshtein_distance(s1: str, s2: str) -> int:
    """计算编辑距离（Levenshtein Distance）

    Args:
        s1: 字符串1
        s2: 字符串2

    Returns:
        编辑距离
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # insertions, deletions, substitutions
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def calculate_wer(reference: str, hypothesis: str) -> float:
    """计算词错误率 (Word Error Rate)

    WER = (编辑距离 / 参考词数) * 100%

    Args:
        reference: 参考文本
        hypothesis: 识别文本

    Returns:
        WER 百分比 (0-100)
    """
    ref_words = reference.lower().split()
    hyp_words = hypothesis.lower().split()

    if not ref_words:
        return 0.0 if not hyp_words else 100.0

    # 将词列表转换为字符串计算编辑距离
    ref_str = " ".join(ref_words)
    hyp_str = " ".join(hyp_words)

    distance = levenshtein_distance(ref_str, hyp_str)
    wer = (distance / len(ref_words)) * 100

    return min(wer, 100.0)  # 上限 100%


def calculate_cer(reference: str, hypothesis: str) -> float:
    """计算字符错误率 (Character Error Rate)

    CER = (编辑距离 / 参考字符数) * 100%

    Args:
        reference: 参考文本
        hypothesis: 识别文本

    Returns:
        CER 百分比 (0-100)
    """
    ref_chars = list(reference.lower())
    hyp_chars = list(hypothesis.lower())

    if not ref_chars:
        return 0.0 if not hyp_chars else 100.0

    distance = levenshtein_distance(ref_chars, hyp_chars)
    cer = (distance / len(ref_chars)) * 100

    return min(cer, 100.0)  # 上限 100%


async def transcribe_audio(
    audio_path: Path,
    language: str,
) -> str:
    """转写音频文件

    使用 faster-whisper 进行转写。

    Args:
        audio_path: 音频文件路径
        language: 语言代码

    Returns:
        转写文本
    """
    from faster_whisper import WhisperModel
    import torch

    # 自动选择设备
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"

    # 使用 tiny 模型快速测试
    model = WhisperModel("tiny", device=device, compute_type=compute_type)

    # 读取音频
    import wave
    with wave.open(str(audio_path), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    # 转写
    segments, info = model.transcribe(
        audio,
        language=language if language != "auto" else None,
        beam_size=5,
    )
    segments = list(segments)

    text = " ".join(seg.text.strip() for seg in segments)
    return text


def load_test_samples(fixtures_dir: Path) -> list[TestSample]:
    """从 fixtures 目录加载测试样本

    期望目录结构:
        fixtures/audio/
            sample_001.wav
            sample_001.json  # 包含 reference_text 和 language
            sample_002.wav
            sample_002.json
            ...

    Args:
        fixtures_dir: fixtures 目录路径

    Returns:
        测试样本列表
    """
    audio_dir = fixtures_dir / "audio"
    if not audio_dir.exists():
        return []

    samples = []

    # 查找所有 .wav 文件
    for wav_file in sorted(audio_dir.glob("*.wav")):
        json_file = wav_file.with_suffix(".json")

        if not json_file.exists():
            print(f"  Warning: Missing {json_file.name}, skipping")
            continue

        try:
            with open(json_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            sample = TestSample(
                audio_file=str(wav_file),
                reference_text=metadata.get("reference_text", ""),
                language=metadata.get("language", "en"),
            )

            if sample.reference_text:
                samples.append(sample)
            else:
                print(f"  Warning: Empty reference_text in {json_file.name}")

        except Exception as e:
            print(f"  Error loading {json_file.name}: {e}")

    return samples


async def evaluate_sample(sample: TestSample) -> EvaluationResult:
    """评估单个样本

    Args:
        sample: 测试样本

    Returns:
        评估结果
    """
    audio_path = Path(sample.audio_file)

    if not audio_path.exists():
        return EvaluationResult(
            sample=sample,
            transcribed_text="",
            wer=100.0,
            cer=100.0,
        )

    try:
        # 转写
        transcribed = await transcribe_audio(
            audio_path,
            sample.language,
        )

        # 计算 WER/CER
        wer = calculate_wer(sample.reference_text, transcribed)
        cer = calculate_cer(sample.reference_text, transcribed)

        return EvaluationResult(
            sample=sample,
            transcribed_text=transcribed,
            wer=wer,
            cer=cer,
            words_matched=len(sample.reference_text.split()),
            words_total=len(transcribed.split()),
            chars_matched=len(sample.reference_text),
            chars_total=len(transcribed),
        )

    except Exception as e:
        print(f"  Error transcribing {audio_path.name}: {e}")
        return EvaluationResult(
            sample=sample,
            transcribed_text="",
            wer=100.0,
            cer=100.0,
        )


def format_result(result: EvaluationResult) -> str:
    """格式化单个结果"""
    status = "✓" if result.wer < 50 else "✗"
    return (
        f"{status} {Path(result.sample.audio_file).name}\n"
        f"  Reference:     \"{result.sample.reference_text}\"\n"
        f"  Transcribed:    \"{result.transcribed_text}\"\n"
        f"  WER: {result.wer:.1f}%  CER: {result.cer:.1f}%"
    )


async def main():
    parser = argparse.ArgumentParser(description="STT Accuracy Evaluation")
    parser.add_argument(
        "--fixtures-dir",
        type=str,
        default=None,
        help="测试音频 fixtures 目录路径",
    )
    parser.add_argument(
        "--language",
        type=str,
        default="auto",
        choices=["auto", "en", "zh"],
        help="强制语言",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出结果 JSON 文件路径",
    )
    args = parser.parse_args()

    # 确定 fixtures 目录
    if args.fixtures_dir:
        fixtures_dir = Path(args.fixtures_dir)
    else:
        # 默认使用项目中的 fixtures 目录
        fixtures_dir = Path(__file__).parent.parent / "tests" / "fixtures"

    print("=" * 60)
    print("STT Accuracy Evaluation")
    print("=" * 60)
    print(f"\nFixtures directory: {fixtures_dir}")

    # 加载测试样本
    samples = load_test_samples(fixtures_dir)

    if not samples:
        print("\nNo test samples found!")
        print(f"\nPlease create test audio files in: {fixtures_dir / 'audio'}")
        print("Each sample should have:")
        print("  - sample_xxx.wav: Audio file (16kHz, mono, PCM)")
        print("  - sample_xxx.json: Metadata with 'reference_text' and 'language'")
        sys.exit(1)

    print(f"\nFound {len(samples)} test samples:")
    for s in samples:
        print(f"  - {Path(s.audio_file).name}: [{s.language}] {s.reference_text[:50]}...")

    # 评估
    print("\n" + "=" * 60)
    print("Running Evaluation")
    print("=" * 60)

    results: list[EvaluationResult] = []

    for i, sample in enumerate(samples):
        print(f"\n[{i + 1}/{len(samples)}] Evaluating: {Path(sample.audio_file).name}")
        result = await evaluate_sample(sample)
        results.append(result)
        print(format_result(result))

    # 统计
    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)

    # 按语言分组统计
    by_language: dict[str, list[EvaluationResult]] = {}
    for r in results:
        lang = r.sample.language
        if lang not in by_language:
            by_language[lang] = []
        by_language[lang].append(r)

    for lang, lang_results in by_language.items():
        wer_values = [r.wer for r in lang_results if r.wer < 200]
        cer_values = [r.cer for r in lang_results if r.cer < 200]

        print(f"\nLanguage: {lang.upper()}")
        print(f"  Samples: {len(lang_results)}")
        if wer_values:
            print(f"  Average WER: {np.mean(wer_values):.1f}%")
            print(f"  Average CER: {np.mean(cer_values):.1f}%")
            print(f"  Min WER: {min(wer_values):.1f}%")
            print(f"  Max WER: {max(wer_values):.1f}%")

    # 总体统计
    all_wer = [r.wer for r in results if r.wer < 200]
    all_cer = [r.cer for r in results if r.cer < 200]

    print(f"\nOverall ({len(results)} samples)")
    print(f"  Average WER: {np.mean(all_wer):.1f}%")
    print(f"  Average CER: {np.mean(all_cer):.1f}%")

    # 保存结果
    if args.output:
        output_data = {
            "summary": {
                "total_samples": len(results),
                "average_wer": float(np.mean(all_wer)),
                "average_cer": float(np.mean(all_cer)),
            },
            "samples": [
                {
                    "audio_file": r.sample.audio_file,
                    "reference_text": r.sample.reference_text,
                    "transcribed_text": r.transcribed_text,
                    "language": r.sample.language,
                    "wer": r.wer,
                    "cer": r.cer,
                }
                for r in results
            ],
        }

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
