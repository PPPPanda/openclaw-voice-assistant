"""Server RPC 协议测试"""

from __future__ import annotations

import base64
import json

import numpy as np
import pytest

from speech_core.config import AppConfig


class TestJsonRpcProtocol:
    """JSON-RPC 2.0 协议格式测试"""

    def test_stt_request_format(self):
        """验证 STT 请求格式"""
        # 生成测试音频
        audio = np.zeros(16000, dtype=np.int16)
        audio_b64 = base64.b64encode(audio.tobytes()).decode("ascii")

        request = {
            "jsonrpc": "2.0",
            "id": "stt-001",
            "method": "speech.stt",
            "params": {
                "audio": {
                    "format": "pcm_s16le",
                    "sampleRate": 16000,
                    "channels": 1,
                    "data": audio_b64,
                },
                "options": {
                    "language": "auto",
                    "model": "base",
                    "vadEnabled": True,
                    "vadThreshold": 0.5,
                },
                "stream": False,
            },
        }

        # 验证可序列化
        serialized = json.dumps(request)
        parsed = json.loads(serialized)
        assert parsed["jsonrpc"] == "2.0"
        assert parsed["method"] == "speech.stt"

    def test_tts_request_format(self):
        """验证 TTS 请求格式"""
        request = {
            "jsonrpc": "2.0",
            "id": "tts-001",
            "method": "speech.tts",
            "params": {
                "text": "你好，世界。",
                "options": {
                    "voice": "zh_CN-huayan-medium",
                    "speed": 1.0,
                    "pitch": 1.0,
                    "provider": "piper",
                },
                "output": {
                    "format": "opus",
                    "sampleRate": 48000,
                    "channels": 1,
                },
                "stream": True,
            },
        }

        serialized = json.dumps(request)
        parsed = json.loads(serialized)
        assert parsed["method"] == "speech.tts"
        assert parsed["params"]["text"] == "你好，世界。"

    def test_error_response_format(self):
        """验证错误响应格式"""
        error_response = {
            "jsonrpc": "2.0",
            "id": "stt-001",
            "error": {
                "code": -32601,
                "message": "Method not found",
            },
        }

        assert error_response["error"]["code"] == -32601


class TestAppConfig:
    """应用配置测试"""

    def test_default_config(self):
        config = AppConfig()
        assert config.server.host == "0.0.0.0"
        assert config.server.port == 9001
        assert config.stt.engine == "faster-whisper"
        assert config.stt.model == "base"
        assert config.tts.engine == "piper"
        assert config.log_level == "INFO"
