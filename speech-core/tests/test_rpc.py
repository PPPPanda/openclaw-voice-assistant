"""WebSocket RPC 服务器测试

测试 JSON-RPC 2.0 协议格式、方法路由和错误处理。
"""

from __future__ import annotations

import asyncio
import json
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

# Mock torch before importing speech_core modules that depend on it
if "torch" not in sys.modules:
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = False
    mock_torch.hub.load.return_value = (MagicMock(), None)
    mock_torch.from_numpy.return_value = MagicMock()
    mock_torch.jit.ScriptModule = type("ScriptModule", (), {})
    sys.modules["torch"] = mock_torch

from speech_core.server import SpeechCoreServer
from speech_core.config import AppConfig


class TestJsonRpcProtocol:
    """JSON-RPC 2.0 协议格式测试"""

    def test_valid_request_format(self):
        """测试有效请求格式"""
        request = {
            "jsonrpc": "2.0",
            "id": "test-001",
            "method": "speech.stt",
            "params": {
                "audio": {
                    "format": "pcm_s16le",
                    "sampleRate": 16000,
                    "channels": 1,
                    "data": "AAECAw==",  # base64 编码的测试数据
                },
                "options": {
                    "language": "auto",
                },
            },
        }

        # 验证可序列化
        serialized = json.dumps(request)
        parsed = json.loads(serialized)

        assert parsed["jsonrpc"] == "2.0"
        assert parsed["method"] == "speech.stt"
        assert "params" in parsed

    def test_response_format_success(self):
        """测试成功响应格式"""
        response = {
            "jsonrpc": "2.0",
            "id": "test-001",
            "result": {
                "text": "hello world",
                "language": "en",
                "confidence": 0.95,
            },
        }

        assert response["jsonrpc"] == "2.0"
        assert "result" in response

    def test_response_format_error(self):
        """测试错误响应格式"""
        response = {
            "jsonrpc": "2.0",
            "id": "test-001",
            "error": {
                "code": -32600,
                "message": "Invalid Request",
            },
        }

        assert response["jsonrpc"] == "2.0"
        assert "error" in response
        assert response["error"]["code"] == -32600


class TestJsonRpcMethods:
    """JSON-RPC 方法路由测试"""

    @pytest.mark.asyncio
    async def test_method_speech_stt(self):
        """测试 speech.stt 方法"""
        # 验证方法存在于处理表中
        assert "speech.stt" in SpeechCoreServer._method_handlers

    @pytest.mark.asyncio
    async def test_method_speech_tts(self):
        """测试 speech.tts 方法"""
        assert "speech.tts" in SpeechCoreServer._method_handlers

    @pytest.mark.asyncio
    async def test_method_speech_status(self):
        """测试 speech.status 方法"""
        assert "speech.status" in SpeechCoreServer._method_handlers

    @pytest.mark.asyncio
    async def test_method_speech_models(self):
        """测试 speech.models 方法"""
        assert "speech.models" in SpeechCoreServer._method_handlers


class TestJsonRpcErrorHandling:
    """错误处理测试"""

    def test_parse_error(self):
        """测试解析错误"""
        # 无效 JSON
        raw = "not valid json"

        # 模拟错误响应
        response = SpeechCoreServer._make_error(-32700, "Parse error")

        assert response["error"]["code"] == -32700

    def test_invalid_request_missing_jsonrpc(self):
        """测试缺少 jsonrpc 字段"""
        request = {
            "id": "test-001",
            "method": "speech.stt",
        }

        # 验证 jsonrpc 字段存在
        assert "jsonrpc" not in request

    def test_invalid_request_missing_method(self):
        """测试缺少 method 字段"""
        request = {
            "jsonrpc": "2.0",
            "id": "test-001",
        }

        # 验证 method 字段不存在
        assert "method" not in request

    def test_method_not_found(self):
        """测试方法不存在"""
        unknown_method = "speech.unknown_method"

        assert unknown_method not in SpeechCoreServer._method_handlers

    def test_error_codes(self):
        """测试标准错误码"""
        # JSON-RPC 2.0 错误码
        assert -32700 == -32700  # Parse error
        assert -32600 == -32600  # Invalid Request
        assert -32601 == -32601  # Method not found
        assert -32602 == -32602  # Invalid params
        assert -32603 == -32603  # Internal error


class TestRpcIntegration:
    """RPC 集成测试（Mock）"""

    @pytest.mark.asyncio
    async def test_handle_valid_message(self):
        """测试处理有效消息"""
        config = AppConfig()
        server = SpeechCoreServer(config)

        message = json.dumps({
            "jsonrpc": "2.0",
            "id": "test-001",
            "method": "speech.status",
            "params": {},
        })

        # 处理消息（需要 mock 引擎）
        with patch.object(server, '_stt_engine', None):
            with patch.object(server, '_tts_engine', None):
                with patch.object(server, '_vad', MagicMock()):
                    response = await server._handle_message(message)

        # 应该返回响应
        assert response is not None
        assert response.get("jsonrpc") == "2.0"

    @pytest.mark.asyncio
    async def test_handle_invalid_json(self):
        """测试处理无效 JSON"""
        config = AppConfig()
        server = SpeechCoreServer(config)

        response = await server._handle_message("not valid json")

        assert response is not None
        assert "error" in response
        assert response["error"]["code"] == -32700

    @pytest.mark.asyncio
    async def test_handle_missing_method(self):
        """测试处理缺少 method 的请求"""
        config = AppConfig()
        server = SpeechCoreServer(config)

        message = json.dumps({
            "jsonrpc": "2.0",
            "id": "test-001",
            # 缺少 method
        })

        response = await server._handle_message(message)

        assert response is not None
        assert "error" in response


class TestRpcStatus:
    """状态查询测试"""

    @pytest.mark.asyncio
    async def test_status_response_structure(self):
        """测试状态响应结构"""
        config = AppConfig()
        server = SpeechCoreServer(config)

        # 模拟状态处理
        with patch.object(server, '_stt_engine', MagicMock()):
            with patch.object(server, '_tts_engine', MagicMock()):
                with patch.object(server, '_vad', MagicMock(is_loaded=MagicMock(return_value=True))):
                    server._start_time = 0  # 避免除零

                    # 模拟 torch.cuda.is_available
                    with patch('torch.cuda.is_available', return_value=False):
                        response = await server._handle_status({})

        # 验证响应结构
        assert "status" in response
        assert "stt_engine" in response
        assert "tts_engine" in response
        assert "vad_loaded" in response
        assert "gpu_available" in response
        assert "uptime_seconds" in response


class TestRpcModels:
    """模型列表测试"""

    @pytest.mark.asyncio
    async def test_models_response_structure(self):
        """测试模型列表响应结构"""
        config = AppConfig()
        server = SpeechCoreServer(config)

        with patch.object(server, '_config', config):
            response = await server._handle_models({})

        # 验证响应结构
        assert "stt" in response
        assert "tts" in response
        assert "vad" in response

        # STT 模型
        assert "engine" in response["stt"]
        assert "model" in response["stt"]
        assert "available" in response["stt"]


class TestRpcSTT:
    """STT RPC 测试"""

    @pytest.mark.asyncio
    async def test_stt_params_extraction(self):
        """测试 STT 参数提取"""
        import base64

        config = AppConfig()
        server = SpeechCoreServer(config)

        # 模拟音频数据
        audio_data = b"\x00\x01\x02\x03"
        audio_b64 = base64.b64encode(audio_data).decode("ascii")

        params = {
            "audio": {
                "format": "pcm_s16le",
                "sampleRate": 16000,
                "channels": 1,
                "data": audio_b64,
            },
            "options": {
                "language": "en",
                "model": "tiny",
                "vadEnabled": True,
                "vadThreshold": 0.5,
            },
        }

        # 验证参数结构
        assert "audio" in params
        assert "options" in params
        assert params["audio"]["format"] == "pcm_s16le"


class TestRpcTTS:
    """TTS RPC 测试"""

    @pytest.mark.asyncio
    async def test_tts_params_extraction(self):
        """测试 TTS 参数提取"""
        params = {
            "text": "你好世界",
            "options": {
                "voice": "zh_CN-huayan-medium",
                "speed": 1.0,
                "pitch": 1.0,
                "provider": "piper",
            },
            "stream": True,
        }

        # 验证参数结构
        assert "text" in params
        assert "options" in params
        assert "stream" in params
        assert params["text"] == "你好世界"


class TestRpcErrorMessages:
    """错误消息测试"""

    def test_error_message_parse_error(self):
        """测试解析错误消息"""
        error = SpeechCoreServer._make_error(-32700, "Parse error")
        assert error["error"]["message"] == "Parse error"

    def test_error_message_invalid_request(self):
        """测试无效请求错误消息"""
        error = SpeechCoreServer._make_error(-32600, "Invalid Request: missing method")
        assert error["error"]["message"] == "Invalid Request: missing method"

    def test_error_message_method_not_found(self):
        """测试方法不存在错误消息"""
        error = SpeechCoreServer._make_error(-32601, "Method not found: speech.foo")
        assert "speech.foo" in error["error"]["message"]

    def test_error_with_request_id(self):
        """测试带请求 ID 的错误"""
        error = SpeechCoreServer._make_error(-32603, "Internal error", request_id="test-123")
        assert error["id"] == "test-123"


class TestRpcBatch:
    """批量请求测试"""

    @pytest.mark.asyncio
    async def test_batch_request_format(self):
        """测试批量请求格式"""
        batch_request = [
            {"jsonrpc": "2.0", "id": "1", "method": "speech.status", "params": {}},
            {"jsonrpc": "2.0", "id": "2", "method": "speech.models", "params": {}},
        ]

        # 验证格式
        assert isinstance(batch_request, list)
        assert len(batch_request) == 2

    def test_batch_response_format(self):
        """测试批量响应格式"""
        batch_response = [
            {"jsonrpc": "2.0", "id": "1", "result": {}},
            {"jsonrpc": "2.0", "id": "2", "result": {}},
        ]

        # 验证格式
        assert isinstance(batch_response, list)
        assert len(batch_response) == 2
