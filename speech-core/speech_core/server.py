"""Speech Core WebSocket JSON-RPC 2.0 服务

提供 STT/TTS/VAD 功能的 WebSocket RPC 服务。
协议：JSON-RPC 2.0 over WebSocket
地址：ws://localhost:9001/speech
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import sys
import time
from dataclasses import asdict
from typing import Any

import structlog
import websockets
from websockets.server import WebSocketServerProtocol

from speech_core.config import AppConfig
from speech_core.interfaces import (
    AudioData,
    AudioFormat,
    STTOptions,
    SpeechCoreStatus,
    TTSOptions,
)
from speech_core.stt.engine import BaseSTTEngine
from speech_core.stt.whisper import FasterWhisperEngine
from speech_core.tts.engine import BaseTTSEngine
from speech_core.tts.piper import PiperTTSEngine
from speech_core.vad.silero import SileroVAD

logger = structlog.get_logger(__name__)


class SpeechCoreServer:
    """Speech Core RPC 服务

    处理 JSON-RPC 2.0 请求：
    - speech.stt: 语音转文字
    - speech.tts: 文字转语音
    - speech.status: 服务状态
    - speech.models: 可用模型列表
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._stt_engine: BaseSTTEngine | None = None
        self._tts_engine: BaseTTSEngine | None = None
        self._vad: SileroVAD | None = None
        self._start_time = time.monotonic()
        self._connections: set[WebSocketServerProtocol] = set()

    async def initialize(self) -> None:
        """初始化所有引擎"""
        logger.info("Initializing Speech Core engines...")

        # 初始化 STT
        if self._config.stt.engine == "faster-whisper":
            self._stt_engine = FasterWhisperEngine(
                device=self._config.stt.device,
                compute_type=self._config.stt.compute_type,
            )
        elif self._config.stt.engine == "whisper.cpp":
            from speech_core.stt.whisper_cpp import WhisperCppEngine
            self._stt_engine = WhisperCppEngine()
        else:
            raise ValueError(f"Unknown STT engine: {self._config.stt.engine}")

        await self._stt_engine.load_model(self._config.stt.model)

        # 初始化 TTS
        if self._config.tts.engine == "piper":
            self._tts_engine = PiperTTSEngine()
        elif self._config.tts.engine == "elevenlabs":
            from speech_core.tts.elevenlabs import ElevenLabsTTSEngine
            self._tts_engine = ElevenLabsTTSEngine(
                api_key=self._config.tts.elevenlabs_api_key,
                default_voice_id=self._config.tts.elevenlabs_voice_id,
            )
        else:
            raise ValueError(f"Unknown TTS engine: {self._config.tts.engine}")

        await self._tts_engine.load_model(self._config.tts.voice)

        # 初始化 VAD
        self._vad = SileroVAD()
        await self._vad.load_model()

        logger.info(
            "Speech Core initialized",
            stt=self._config.stt.engine,
            tts=self._config.tts.engine,
        )

    async def handle_connection(self, websocket: WebSocketServerProtocol) -> None:
        """处理 WebSocket 连接"""
        self._connections.add(websocket)
        remote = websocket.remote_address
        logger.info("Client connected", remote=str(remote))

        try:
            async for message in websocket:
                try:
                    response = await self._handle_message(message)
                    if response:
                        await websocket.send(json.dumps(response))
                except Exception as e:
                    error_response = self._make_error(-32603, str(e))
                    await websocket.send(json.dumps(error_response))
        except websockets.exceptions.ConnectionClosed:
            logger.info("Client disconnected", remote=str(remote))
        finally:
            self._connections.discard(websocket)

    async def _handle_message(self, raw_message: str | bytes) -> dict[str, Any] | None:
        """处理单条 JSON-RPC 消息"""
        try:
            msg = json.loads(raw_message)
        except json.JSONDecodeError:
            return self._make_error(-32700, "Parse error")

        # 验证 JSON-RPC 格式
        if msg.get("jsonrpc") != "2.0":
            return self._make_error(-32600, "Invalid Request: missing jsonrpc 2.0")

        method = msg.get("method")
        params = msg.get("params", {})
        request_id = msg.get("id")

        if not method:
            return self._make_error(-32600, "Invalid Request: missing method", request_id)

        logger.debug("RPC request", method=method, id=request_id)

        # 路由到处理方法
        handler = self._method_handlers.get(method)
        if not handler:
            return self._make_error(-32601, f"Method not found: {method}", request_id)

        try:
            start = time.monotonic()
            result = await handler(self, params)
            elapsed = (time.monotonic() - start) * 1000

            logger.info("RPC response", method=method, elapsed_ms=f"{elapsed:.0f}")

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
        except Exception as e:
            logger.exception("RPC handler error", method=method)
            return self._make_error(-32603, str(e), request_id)

    # ─── RPC 方法实现 ────────────────────────────────────────────────────────

    async def _handle_stt(self, params: dict[str, Any]) -> dict[str, Any]:
        """speech.stt - 语音转文字"""
        if self._stt_engine is None:
            raise RuntimeError("STT engine not initialized")

        audio_params = params.get("audio", {})
        options_params = params.get("options", {})

        # 解码音频数据
        audio_data = base64.b64decode(audio_params.get("data", ""))
        audio = AudioData(
            format=AudioFormat(audio_params.get("format", "pcm_s16le")),
            sample_rate=audio_params.get("sampleRate", 48000),
            channels=audio_params.get("channels", 1),
            data=audio_data,
        )

        options = STTOptions(
            language=options_params.get("language", "auto"),
            model=options_params.get("model", self._config.stt.model),
            vad_enabled=options_params.get("vadEnabled", True),
            vad_threshold=options_params.get("vadThreshold", 0.5),
        )

        result = await self._stt_engine.transcribe(audio, options)

        return {
            "text": result.text,
            "language": result.language,
            "confidence": result.confidence,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in result.segments
            ],
            "processingTimeMs": result.processing_time_ms,
        }

    async def _handle_tts(self, params: dict[str, Any]) -> dict[str, Any]:
        """speech.tts - 文字转语音"""
        if self._tts_engine is None:
            raise RuntimeError("TTS engine not initialized")

        text = params.get("text", "")
        options_params = params.get("options", {})
        stream = params.get("stream", False)

        options = TTSOptions(
            voice=options_params.get("voice", self._config.tts.voice),
            speed=options_params.get("speed", 1.0),
            pitch=options_params.get("pitch", 1.0),
            provider=options_params.get("provider", self._config.tts.engine),
        )

        if stream:
            # 流式合成 - 返回第一个块的信息
            chunks: list[dict[str, Any]] = []
            async for chunk in self._tts_engine.synthesize_stream(text, options):
                chunks.append({
                    "type": "chunk",
                    "index": chunk.index,
                    "audio": base64.b64encode(chunk.audio).decode("ascii"),
                    "durationMs": chunk.duration_ms,
                    "final": chunk.final,
                })
            return {"chunks": chunks}
        else:
            result = await self._tts_engine.synthesize(text, options)
            return {
                "audio": base64.b64encode(result.audio.data).decode("ascii"),
                "format": result.audio.format.value,
                "sampleRate": result.audio.sample_rate,
                "channels": result.audio.channels,
                "durationMs": result.audio.duration_ms,
                "processingTimeMs": result.processing_time_ms,
            }

    async def _handle_status(self, params: dict[str, Any]) -> dict[str, Any]:
        """speech.status - 服务状态"""
        import torch

        gpu_available = torch.cuda.is_available()
        uptime = time.monotonic() - self._start_time

        status = SpeechCoreStatus(
            status="healthy",
            stt_engine=self._config.stt.engine,
            tts_engine=self._config.tts.engine,
            vad_loaded=self._vad.is_loaded() if self._vad else False,
            gpu_available=gpu_available,
            uptime_seconds=uptime,
        )

        return asdict(status)

    async def _handle_models(self, params: dict[str, Any]) -> dict[str, Any]:
        """speech.models - 可用模型列表"""
        return {
            "stt": {
                "engine": self._config.stt.engine,
                "model": self._config.stt.model,
                "available": ["tiny", "base", "small", "medium", "large-v3"],
            },
            "tts": {
                "engine": self._config.tts.engine,
                "voice": self._config.tts.voice,
            },
            "vad": {
                "engine": "silero",
                "loaded": self._vad.is_loaded() if self._vad else False,
            },
        }

    # 方法路由表
    _method_handlers: dict[str, Any] = {
        "speech.stt": _handle_stt,
        "speech.tts": _handle_tts,
        "speech.status": _handle_status,
        "speech.models": _handle_models,
    }

    # ─── 辅助方法 ────────────────────────────────────────────────────────────

    @staticmethod
    def _make_error(
        code: int,
        message: str,
        request_id: str | int | None = None,
    ) -> dict[str, Any]:
        """构造 JSON-RPC 错误响应"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }

    async def start(self) -> None:
        """启动 WebSocket 服务"""
        host = self._config.server.host
        port = self._config.server.port

        await self.initialize()

        logger.info(f"Starting Speech Core server on ws://{host}:{port}/speech")

        async with websockets.serve(
            self.handle_connection,
            host,
            port,
            ping_interval=self._config.server.ping_interval,
            ping_timeout=self._config.server.ping_timeout,
            max_size=50 * 1024 * 1024,  # 50MB max message size for audio
        ):
            logger.info(f"Speech Core server running on ws://{host}:{port}/speech")
            await asyncio.Future()  # Run forever


def configure_logging(level: str = "INFO") -> None:
    """配置 structlog"""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def main() -> None:
    """服务入口"""
    config = AppConfig.from_env()
    configure_logging(config.log_level)

    server = SpeechCoreServer(config)

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Server shutdown by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
