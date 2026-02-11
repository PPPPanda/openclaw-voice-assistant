"""VAD 测试"""

from __future__ import annotations

import numpy as np
import pytest

from speech_core.interfaces import VADConfig, VADState


class TestVADConfig:
    """VAD 配置测试"""

    def test_defaults(self):
        config = VADConfig()
        assert config.threshold == 0.5
        assert config.min_silence_duration_ms == 600
        assert config.min_speech_duration_ms == 300
        assert config.max_speech_duration_s == 8.0
        assert config.sample_rate == 16000

    def test_custom_config(self):
        config = VADConfig(threshold=0.7, min_silence_duration_ms=400)
        assert config.threshold == 0.7
        assert config.min_silence_duration_ms == 400


class TestVADState:
    """VAD 状态枚举测试"""

    def test_states(self):
        assert VADState.SILENCE.value == "silence"
        assert VADState.SPEECH.value == "speech"
