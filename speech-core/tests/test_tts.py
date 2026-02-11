"""TTS 引擎测试"""

from __future__ import annotations

import pytest

from speech_core.interfaces import TTSOptions
from speech_core.tts.engine import BaseTTSEngine


class TestTTSOptions:
    """TTS 选项测试"""

    def test_defaults(self):
        options = TTSOptions()
        assert options.voice == "zh_CN-huayan-medium"
        assert options.speed == 1.0
        assert options.pitch == 1.0
        assert options.provider == "piper"

    def test_custom_options(self):
        options = TTSOptions(
            voice="en_US-amy-medium",
            speed=1.2,
            provider="elevenlabs",
        )
        assert options.voice == "en_US-amy-medium"
        assert options.speed == 1.2
        assert options.provider == "elevenlabs"


class TestSentenceSplitter:
    """句子分割测试"""

    def test_chinese_sentences(self):
        text = "你好。今天天气怎么样？很好！"
        sentences = BaseTTSEngine.split_sentences(text)
        assert len(sentences) == 3
        assert sentences[0] == "你好。"
        assert sentences[1] == "今天天气怎么样？"
        assert sentences[2] == "很好！"

    def test_english_sentences(self):
        text = "Hello. How are you? I'm fine!"
        sentences = BaseTTSEngine.split_sentences(text)
        assert len(sentences) == 3

    def test_mixed_sentences(self):
        text = "你好，我是 OpenClaw。Nice to meet you!"
        sentences = BaseTTSEngine.split_sentences(text)
        assert len(sentences) == 2

    def test_single_sentence(self):
        text = "这是一个没有结束标点的句子"
        sentences = BaseTTSEngine.split_sentences(text)
        assert len(sentences) == 1
        assert sentences[0] == text

    def test_empty_text(self):
        sentences = BaseTTSEngine.split_sentences("")
        assert len(sentences) == 0


class TestPiperEngine:
    """Piper TTS 引擎测试（需要安装）"""

    @pytest.mark.skipif(
        True,  # 设为 False 以启用集成测试
        reason="Integration test - requires piper-tts",
    )
    @pytest.mark.asyncio
    async def test_synthesize(self):
        from speech_core.tts.piper import PiperTTSEngine

        engine = PiperTTSEngine()
        await engine.load_model("en_US-amy-medium")

        options = TTSOptions(voice="en_US-amy-medium")
        result = await engine.synthesize("Hello world", options)

        assert result.processing_time_ms > 0
        assert len(result.audio.data) > 0
        assert result.audio.sample_rate > 0
