# OpenClaw Voice Gateway

统一语音网关，为 OpenClaw 生态系统提供可扩展的实时语音对话能力。

## 架构概览

```
Transport Layer  →  Speech Core Layer  →  OpenClaw Orchestrator
(平台适配器)        (语音中台)             (对话编排)
```

三层解耦架构：
- **Transport Layer**: 平台适配器（Discord Voice、Voice Message、WebRTC）
- **Speech Core Layer**: 语音处理中台（VAD、STT、TTS、Pipeline）
- **OpenClaw Orchestrator**: 对话编排（多 LLM 路由、记忆管理、工具调用）

## 项目结构

```
├── speech-core/              # Python Speech Core Service (Port 9001)
│   ├── speech_core/
│   │   ├── server.py         # WebSocket JSON-RPC 2.0 服务
│   │   ├── interfaces.py     # 类型定义
│   │   ├── stt/              # STT 引擎 (faster-whisper / whisper.cpp)
│   │   ├── tts/              # TTS 引擎 (Piper / ElevenLabs)
│   │   ├── vad/              # VAD 检测 (Silero)
│   │   └── pipeline/         # 语音处理流水线
│   └── tests/
│
├── gateway-plugins/          # OpenClaw Gateway 插件 (TypeScript)
│   ├── speech-core/          # Speech Core RPC 客户端插件
│   └── discord-voice/        # Discord 语音适配器插件
│
├── docs/                     # 文档
└── docker-compose.yml        # 本地开发环境
```

## 快速开始

### 前置条件

- Python 3.11+
- Node.js 20+
- FFmpeg（音频处理）
- CUDA（可选，GPU 加速 STT）

### 1. 启动 Speech Core 服务

```bash
cd speech-core
pip install -e ".[dev]"
python -m speech_core.server
```

服务将在 `ws://localhost:9001/speech` 启动。

### 2. 安装 Gateway 插件

```bash
cd gateway-plugins/speech-core
npm install && npm run build

cd ../discord-voice
npm install && npm run build
```

### 3. Docker 一键启动（推荐）

```bash
docker-compose up -d
```

## 实施阶段

| 阶段 | 目标 | 预计工期 |
|------|------|----------|
| Phase 0 | 语音留言验证 (STT + OpenClaw 集成) | 1-2 天 |
| Phase 1 | 半双工对讲 (Discord 语音频道) | 7-14 天 |
| Phase 2 | 插件化重构 (Gateway 集成) | 2-3 周 |
| Phase 3 | 全双工打断 (流式 TTS + Barge-in) | 2-4 周 |

## 性能目标

| 指标 | P50 | P95 |
|------|-----|-----|
| 端到端延迟 | ≤ 1.0s | ≤ 2.0s |
| STT 转写 | 300ms | 500ms |
| TTS 首帧 | 200ms | 400ms |

## 协议

Speech Core 使用 **JSON-RPC 2.0 over WebSocket** 协议。

详细 API 文档见 [docs/api-reference.md](docs/api-reference.md)

## License

MIT
