# OpenClaw 统一语音网关架构技术报告

**版本**: v1.0  
**日期**: 2026-02-10  
**作者**: 高级系统架构师  
**状态**: 综合评估完成

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [材料对比分析](#2-材料对比分析)
3. [GPT 建议评估](#3-gpt-建议评估)
4. [最终推荐架构](#4-最终推荐架构)
5. [技术规格详述](#5-技术规格详述)
6. [实施计划与里程碑](#6-实施计划与里程碑)
7. [风险评估与缓解措施](#7-风险评估与缓解措施)
8. [附录](#8-附录)

---

## 1. 执行摘要

### 1.1 背景

本报告综合评估两份技术方案，目标是为 OpenClaw 生态系统设计一套**可扩展的实时语音对话能力**，支持 Discord 语音频道（优先）及未来其他平台扩展。

### 1.2 关键结论

| 维度 | 结论 |
|------|------|
| **平台可行性** | Discord ✅（@discordjs/voice 支持接收）；KOOK ❌（仅单向推流） |
| **架构方向** | 采用三层解耦架构：Transport → Speech Core → OpenClaw Orchestrator |
| **延迟目标** | 全本地方案 P50 目标 0.8-1.2s，P95 目标 1.5-2.5s |
| **实施路径** | 4 阶段渐进式：MVP 验证 → 半双工 → 插件化 → 全双工打断 |
| **核心风险** | Discord 语音工程复杂度高；本地 TTS 音质/延迟权衡 |

### 1.3 最终推荐

**采用 GPT 建议的三层架构 + 原方案的延迟优化目标**，Phase 0 用语音留言快速验证，Phase 1 实现半双工对讲，后续迭代打磨体验。

---

## 2. 材料对比分析

### 2.1 方案概览

| 维度 | 材料1（原架构评估） | 材料2（GPT 建议） |
|------|---------------------|-------------------|
| **核心架构** | Discord → OpenClaw Gateway → STT/LLM/TTS → Discord 统一网关 | 三层解耦：Transport / Speech Core / OpenClaw Orchestrator |
| **延迟目标** | 全本地方案 0.7-1.8s（明确量化） | 600-1500ms（半双工目标） |
| **实施阶段** | 4 阶段（未展开详细） | 4 阶段详细展开（Phase 0-3） |
| **平台视角** | 统一网关，面向多平台 | 明确指出 KOOK 限制，Discord 优先 |
| **技术深度** | 宏观架构层面 | 具体组件选型（discospeech、Pipecat 等） |

### 2.2 共识点

两份方案在以下核心理念上**高度一致**：

1. **本地优先**：STT/TTS 放本地可控成本、隐私、延迟
2. **模型无关**：OpenClaw 内部已是多模型可配置/可回退范式
3. **平台解耦**：Transport 层与 Speech Core 分离，便于扩展
4. **渐进实施**：从简单场景开始，逐步增加复杂度

### 2.3 差异点

| 差异维度 | 材料1 | 材料2 | 评估 |
|----------|-------|-------|------|
| **起步策略** | 直接语音频道 | 先用语音留言验证 | GPT 更务实 |
| **架构详细度** | 宏观描述 | 具体分层定义 | GPT 更具操作性 |
| **参考项目** | 未列出 | discospeech、Pipecat 等 | GPT 调研更充分 |
| **KOOK 可行性** | 假设可扩展 | 明确指出限制 | GPT 更准确（实测验证） |
| **工程指标** | 延迟目标 0.7-1.8s | 提出 6 个工程指标 | 原方案量化更激进 |

### 2.4 综合判断

**GPT 建议更具可操作性**，原方案的延迟目标作为**技术追求指标**保留。两者互补，非互斥。

---

## 3. GPT 建议评估

### 3.1 合理性评估

#### 3.1.1 三层架构设计 — ✅ 高度认可

```
┌─────────────────────────────────────────────────────────────┐
│                   Transport 层（平台适配器）                  │
│  DiscordVoiceAdapter  │  KookAdapter*  │  WebRTCAdapter    │
│  加入房间/收发音频帧/用户事件/权限管理                          │
└────────────────────────────┬────────────────────────────────┘
                             │ PCM / Events
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   Speech Core 层（语音中台）                  │
│  VAD → STT → 文本输出     │     文本输入 → TTS → PCM 输出    │
│  打断策略/回声消除/采样率变换                                   │
└────────────────────────────┬────────────────────────────────┘
                             │ Text / Commands
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              OpenClaw Orchestrator（对话编排）                │
│  多 LLM 路由 │ 记忆管理 │ 工具调用 │ 会话状态 │ 人格配置       │
└─────────────────────────────────────────────────────────────┘
```

**优势**：
- 平台更换只需重写 Transport 层
- Speech Core 可独立优化（GPU 加速、模型升级）
- OpenClaw 核心能力复用率 100%

**验证**：这与 OpenClaw 官方 Voice Call Plugin 的设计理念一致（插件在 Gateway 内运行、提供 streaming、复用 messages.tts）

#### 3.1.2 Phase 0 语音留言验证 — ✅ 强烈认可

**理由**：
1. 绕开 Discord 语音网关的工程复杂度
2. 验证本地 STT 性能和模型选择
3. 验证 OpenClaw 多 LLM 路由逻辑
4. 风险最低，1-2 天可出结果

**OpenClaw 现有支持**：
- 已支持音频附件自动探测本地 CLI（whisper-cli/whisper/sherpa-onnx-offline）
- 自动写入 `{{Transcript}}` 供 LLM 使用

#### 3.1.3 参考项目推荐 — ✅ 调研充分

| 项目 | 定位 | 参考价值 |
|------|------|----------|
| **discospeech** | Discord 语音端到端实现 | 音频采集、VAD、Whisper 集成方案 |
| **Discord-VC-LLM** | 典型 STT→LLM→TTS 结构 | 架构参考 |
| **Pipecat** | 通用实时语音 Agent 框架 | pipeline + transport 抽象 |

**建议**：优先参考 discospeech 的音频采集方案，架构上借鉴 Pipecat 的 pipeline 抽象。

#### 3.1.4 6 个工程指标 — ✅ 关键约束

| 指标 | GPT 建议 | 调整建议 |
|------|----------|----------|
| 端到端延迟 P50/P95 | 1.2s / 2.5s | P50 目标压到 0.9s |
| STT 断句策略 | 静音阈值+最长语句 | 补充：起始阈值 300ms、静音 600ms、最长 8s |
| 多人并发策略 | 3 种方案 | 优先 active speaker，降低复杂度 |
| TTS 选型 | 待定 | Piper（本地）+ ElevenLabs（云端备选） |
| 会话模型 | 按频道/按人 | 按 voiceChannelId 为主，可选叠加 active speaker |
| 部署形态 | 先分离后内聚 | ✅ 认可 |

### 3.2 风险点识别

#### 3.2.1 低估的风险

| 风险点 | GPT 描述 | 实际评估 | 严重度 |
|--------|----------|----------|--------|
| **Discord 语音采集难度** | "很多库里不是一等公民" | 实测 @discordjs/voice 支持 `receiver.subscribe()`，但文档不完善 | 中 |
| **多人混流/分流** | 简略提及 | 实时混流需要额外工程量，建议 Phase 1 只支持单人 | 中 |
| **TTS 延迟与音质权衡** | 未量化 | Piper 本地 TTS 约 200-500ms RTF，音质中等；高质量需云端 | 高 |

#### 3.2.2 未提及的风险

| 风险点 | 描述 | 缓解措施 |
|--------|------|----------|
| **Opus 编解码开销** | Discord 要求 48kHz/20ms Opus 帧 | 使用 libopus FFI 绑定，避免额外进程开销 |
| **WSL 环境限制** | GPU 加速在 WSL2 下需特殊配置 | 确认 CUDA 可用性或纯 CPU 方案 |
| **Discord API 速率限制** | 高频语音事件可能触发限流 | 批量化事件处理、优雅降级 |
| **OpenClaw Gateway 单点** | 语音服务依赖 Gateway 存活 | 健康检查 + 自动重连 |

#### 3.2.3 乐观估计

| 内容 | GPT 估计 | 现实评估 |
|------|----------|----------|
| Phase 0 耗时 | 1-2 天 | 1-2 天 ✅ 合理 |
| Phase 1 耗时 | 3-7 天 | 7-14 天（含调试） |
| Phase 2 耗时 | 1-2 周 | 2-3 周 |
| Phase 3 耗时 | 未明确 | 2-4 周 |

---

## 4. 最终推荐架构

### 4.1 架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Transport Layer                                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │ DiscordVoice    │  │ VoiceMessage    │  │ WebRTC          │ (未来)       │
│  │ Adapter         │  │ Adapter         │  │ Adapter         │              │
│  │ (实时语音频道)   │  │ (语音附件/留言)  │  │ (自建实时通信)   │              │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘              │
└───────────┼────────────────────┼────────────────────┼────────────────────────┘
            │                    │                    │
            └────────────────────┼────────────────────┘
                                 │ PCM Audio / Events
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Speech Core Layer                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        SpeechPipeline                                │    │
│  │  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐             │    │
│  │  │ VAD     │→  │ Segment │→  │ STT     │→  │ Text    │             │    │
│  │  │ Detector│   │ Buffer  │   │ Engine  │   │ Output  │             │    │
│  │  └─────────┘   └─────────┘   └─────────┘   └─────────┘             │    │
│  │                                                                      │    │
│  │  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐             │    │
│  │  │ Text    │←  │ TTS     │←  │ Chunker │←  │ Text    │             │    │
│  │  │ Output  │   │ Engine  │   │ (句级)   │   │ Input   │             │    │
│  │  └─────────┘   └─────────┘   └─────────┘   └─────────┘             │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │ BargeIn         │  │ EchoCanceler    │  │ SampleRate      │              │
│  │ Controller      │  │ (可选)          │  │ Converter       │              │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘              │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │ Text / Commands
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        OpenClaw Gateway (Orchestrator)                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │ Session Manager │  │ LLM Router      │  │ Tool Executor   │              │
│  │ (按 channelId)  │  │ (多模型回退)    │  │ (技能调用)      │              │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘              │
│  ┌─────────────────┐  ┌─────────────────┐                                   │
│  │ Memory Manager  │  │ Persona Config  │                                   │
│  │ (对话历史)      │  │ (人格配置)      │                                   │
│  └─────────────────┘  └─────────────────┘                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 核心设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| **语言选择** | Transport: Python；Speech Core: Python；Gateway 集成: TypeScript | Python 语音生态成熟；Gateway 保持原生 |
| **STT 引擎** | faster-whisper（GPU）/ whisper.cpp（CPU） | 性能最优，支持流式 |
| **TTS 引擎** | Piper（本地）+ ElevenLabs（云端备选） | Piper 延迟低；ElevenLabs 音质好 |
| **VAD 方案** | Silero VAD | 轻量、准确、易集成 |
| **进程模型** | 独立进程，通过 RPC 与 Gateway 通信 | 隔离故障域，便于调试 |
| **通信协议** | WebSocket + JSON-RPC 2.0 | 双向通信，与 Gateway 协议一致 |

### 4.3 与 OpenClaw 集成方式

```
┌─────────────────────────────────────────────────────────────┐
│                    OpenClaw Gateway                          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              speech-core Plugin (TypeScript)          │   │
│  │                                                       │   │
│  │  Gateway RPC:                                         │   │
│  │    speech.stt   → 调用外部 Python 服务                │   │
│  │    speech.tts   → 调用外部 Python 服务                │   │
│  │    speech.status → 健康检查                           │   │
│  │                                                       │   │
│  │  Config:                                              │   │
│  │    sttEndpoint: "ws://localhost:9001/stt"            │   │
│  │    ttsEndpoint: "ws://localhost:9001/tts"            │   │
│  └──────────────────────────────────────────────────────┘   │
│                            ▲                                 │
│                            │ Gateway RPC                     │
│                            ▼                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         discord-voice-adapter Plugin                  │   │
│  │                                                       │   │
│  │  - 加入/离开语音频道                                   │   │
│  │  - 接收用户音频 → 调用 speech.stt                     │   │
│  │  - 收到 LLM 回复 → 调用 speech.tts → 播放            │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │ WebSocket
                            ▼
┌─────────────────────────────────────────────────────────────┐
│               Speech Core Service (Python)                   │
│                                                              │
│  Port 9001                                                   │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ STT Worker  │  │ TTS Worker  │  │ VAD Worker  │         │
│  │ (faster-    │  │ (Piper)     │  │ (Silero)    │         │
│  │  whisper)   │  │             │  │             │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 技术规格详述

### 5.1 协议设计

#### 5.1.1 Speech Core RPC 协议

**基础协议**：JSON-RPC 2.0 over WebSocket

**连接地址**：`ws://localhost:9001/speech`

##### STT 请求

```json
{
  "jsonrpc": "2.0",
  "id": "stt-001",
  "method": "speech.stt",
  "params": {
    "audio": {
      "format": "pcm_s16le",
      "sampleRate": 48000,
      "channels": 1,
      "data": "<base64 encoded audio>"
    },
    "options": {
      "language": "auto",
      "model": "base",
      "vadEnabled": true,
      "vadThreshold": 0.5
    },
    "stream": false
  }
}
```

##### STT 响应

```json
{
  "jsonrpc": "2.0",
  "id": "stt-001",
  "result": {
    "text": "你好，今天天气怎么样？",
    "language": "zh",
    "confidence": 0.95,
    "segments": [
      {
        "start": 0.0,
        "end": 1.2,
        "text": "你好，"
      },
      {
        "start": 1.2,
        "end": 2.5,
        "text": "今天天气怎么样？"
      }
    ],
    "processingTimeMs": 450
  }
}
```

##### TTS 请求

```json
{
  "jsonrpc": "2.0",
  "id": "tts-001",
  "method": "speech.tts",
  "params": {
    "text": "今天天气很好，适合出门散步。",
    "options": {
      "voice": "zh_CN-huayan-medium",
      "speed": 1.0,
      "pitch": 1.0,
      "provider": "piper"
    },
    "output": {
      "format": "opus",
      "sampleRate": 48000,
      "channels": 1
    },
    "stream": true
  }
}
```

##### TTS 流式响应

```json
{
  "jsonrpc": "2.0",
  "id": "tts-001",
  "result": {
    "type": "chunk",
    "index": 0,
    "audio": "<base64 encoded opus frame>",
    "durationMs": 20,
    "final": false
  }
}
```

#### 5.1.2 Transport ↔ Speech Core 事件协议

```json
// 用户开始说话
{
  "event": "speech.started",
  "userId": "123456789",
  "channelId": "987654321",
  "timestamp": 1707552000000
}

// 用户停止说话
{
  "event": "speech.ended",
  "userId": "123456789",
  "channelId": "987654321",
  "durationMs": 3500,
  "timestamp": 1707552003500
}

// 打断请求
{
  "event": "barge_in",
  "userId": "123456789",
  "channelId": "987654321",
  "timestamp": 1707552002000
}
```

### 5.2 接口定义

#### 5.2.1 TypeScript 接口（Gateway 插件）

```typescript
// types/speech.ts

interface SpeechCoreConfig {
  endpoint: string;           // ws://localhost:9001/speech
  reconnectIntervalMs: number;
  maxReconnectAttempts: number;
  healthCheckIntervalMs: number;
}

interface STTRequest {
  audio: AudioData;
  options: STTOptions;
  stream?: boolean;
}

interface STTOptions {
  language?: string;    // 'auto' | 'zh' | 'en' | ...
  model?: string;       // 'tiny' | 'base' | 'small' | 'medium' | 'large'
  vadEnabled?: boolean;
  vadThreshold?: number;
}

interface STTResult {
  text: string;
  language: string;
  confidence: number;
  segments: Segment[];
  processingTimeMs: number;
}

interface TTSRequest {
  text: string;
  options: TTSOptions;
  output: AudioOutputConfig;
  stream?: boolean;
}

interface TTSOptions {
  voice?: string;
  speed?: number;
  pitch?: number;
  provider?: 'piper' | 'elevenlabs' | 'openai';
}

interface AudioOutputConfig {
  format: 'pcm' | 'opus' | 'mp3';
  sampleRate: 16000 | 22050 | 24000 | 44100 | 48000;
  channels: 1 | 2;
}

// Gateway RPC 接口
interface SpeechCoreRPC {
  'speech.stt': (params: STTRequest) => Promise<STTResult>;
  'speech.tts': (params: TTSRequest) => Promise<TTSResult | AsyncIterable<TTSChunk>>;
  'speech.status': () => Promise<SpeechCoreStatus>;
  'speech.models': () => Promise<ModelList>;
}
```

#### 5.2.2 Python 接口（Speech Core Service）

```python
# speech_core/interfaces.py

from dataclasses import dataclass
from typing import Optional, List, AsyncIterator
from enum import Enum

class AudioFormat(Enum):
    PCM_S16LE = "pcm_s16le"
    OPUS = "opus"
    MP3 = "mp3"

@dataclass
class AudioData:
    format: AudioFormat
    sample_rate: int
    channels: int
    data: bytes

@dataclass
class STTOptions:
    language: str = "auto"
    model: str = "base"
    vad_enabled: bool = True
    vad_threshold: float = 0.5

@dataclass
class STTResult:
    text: str
    language: str
    confidence: float
    segments: List['Segment']
    processing_time_ms: int

@dataclass
class Segment:
    start: float
    end: float
    text: str

@dataclass
class TTSOptions:
    voice: str = "zh_CN-huayan-medium"
    speed: float = 1.0
    pitch: float = 1.0
    provider: str = "piper"

class SpeechCoreService:
    """Speech Core 服务接口"""
    
    async def transcribe(
        self, 
        audio: AudioData, 
        options: STTOptions
    ) -> STTResult:
        """同步转写"""
        ...
    
    async def transcribe_stream(
        self, 
        audio_stream: AsyncIterator[bytes],
        options: STTOptions
    ) -> AsyncIterator[STTResult]:
        """流式转写"""
        ...
    
    async def synthesize(
        self, 
        text: str, 
        options: TTSOptions
    ) -> AudioData:
        """同步合成"""
        ...
    
    async def synthesize_stream(
        self, 
        text: str, 
        options: TTSOptions
    ) -> AsyncIterator[bytes]:
        """流式合成（句子级）"""
        ...
```

### 5.3 模块划分

```
clawdbot_workspace/
└── projects/
    └── voice-gateway/
        ├── README.md
        ├── docker-compose.yml          # 本地开发环境
        │
        ├── speech-core/                # Python Speech Core Service
        │   ├── pyproject.toml
        │   ├── speech_core/
        │   │   ├── __init__.py
        │   │   ├── server.py           # WebSocket RPC 服务
        │   │   ├── interfaces.py       # 类型定义
        │   │   ├── stt/
        │   │   │   ├── __init__.py
        │   │   │   ├── engine.py       # STT 引擎抽象
        │   │   │   ├── whisper.py      # faster-whisper 实现
        │   │   │   └── whisper_cpp.py  # whisper.cpp 实现
        │   │   ├── tts/
        │   │   │   ├── __init__.py
        │   │   │   ├── engine.py       # TTS 引擎抽象
        │   │   │   ├── piper.py        # Piper 实现
        │   │   │   └── elevenlabs.py   # ElevenLabs 云端实现
        │   │   ├── vad/
        │   │   │   ├── __init__.py
        │   │   │   └── silero.py       # Silero VAD 实现
        │   │   └── pipeline/
        │   │       ├── __init__.py
        │   │       ├── segment.py      # 语音分段
        │   │       └── barge_in.py     # 打断控制
        │   └── tests/
        │       ├── test_stt.py
        │       ├── test_tts.py
        │       └── fixtures/
        │           └── audio/
        │
        ├── gateway-plugins/            # OpenClaw Gateway 插件
        │   ├── speech-core/            # Speech Core RPC 客户端
        │   │   ├── package.json
        │   │   └── src/
        │   │       ├── index.ts
        │   │       ├── client.ts       # WebSocket RPC 客户端
        │   │       └── types.ts
        │   │
        │   └── discord-voice/          # Discord 语音适配器
        │       ├── package.json
        │       └── src/
        │           ├── index.ts
        │           ├── adapter.ts      # 语音频道管理
        │           ├── receiver.ts     # 音频接收
        │           └── player.ts       # 音频播放
        │
        └── docs/
            ├── architecture.md
            ├── api-reference.md
            └── deployment.md
```

### 5.4 延迟预算分配

基于目标 P50 ≤ 1.0s 的延迟预算分配：

| 阶段 | 目标延迟 | 说明 |
|------|----------|------|
| 用户说话结束检测 (VAD) | 150ms | 静音检测窗口 + 确认 |
| 音频传输 (Discord → 服务) | 50ms | 本地网络延迟可忽略 |
| STT 转写 | 300ms | faster-whisper base 模型 |
| LLM 首 token | 200ms | 本地 LLM 或流式 API |
| TTS 首帧合成 | 200ms | Piper 流式合成 |
| 音频传输 + 播放启动 | 100ms | Opus 编码 + 缓冲 |
| **总计** | **1000ms** | P50 目标 |

**P95 预算 (≤2.0s)**：
- STT 扩展到 500ms（复杂语句）
- LLM 扩展到 600ms（复杂推理）
- 其他阶段保持不变

---

## 6. 实施计划与里程碑

### 6.1 阶段概览

```
Phase 0          Phase 1              Phase 2                Phase 3
语音留言验证     半双工对讲           插件化重构              全双工打断
───────────────────────────────────────────────────────────────────────▶
   1-2天           7-14天               2-3周                   2-4周
   
验证:            实现:                实现:                   实现:
- 本地 STT       - Discord 语音接入    - Gateway 插件封装      - 流式 TTS
- OpenClaw 集成  - 单用户对话          - RPC 接口              - Barge-in
                 - 基础 TTS 回放       - 多用户支持            - 并发优化
```

### 6.2 Phase 0：语音留言验证（1-2 天）

#### 目标
验证本地 STT + OpenClaw 多模型路由的闭环可行性

#### 交付物
- [ ] 本地 whisper 环境配置完成
- [ ] Discord 语音留言自动转写测试通过
- [ ] OpenClaw 正确处理转写文本并回复
- [ ] 延迟基准数据收集

#### 里程碑
- **M0.1**: faster-whisper 本地安装并测试（4h）
- **M0.2**: OpenClaw 音频转写配置启用（2h）
- **M0.3**: 端到端语音留言对话测试（4h）
- **M0.4**: 性能基准文档（2h）

#### 验收标准
```
输入：Discord 语音留言（10s 以内）
输出：OpenClaw 文本回复
延迟：< 3s（含上传时间）
准确率：中文/英文 > 95%
```

### 6.3 Phase 1：半双工对讲（7-14 天）

#### 目标
实现 Discord 语音频道的半双工对话（一说一听）

#### 交付物
- [ ] Discord 语音适配器（加入/离开/接收/播放）
- [ ] VAD 分段逻辑
- [ ] 基础对话流程
- [ ] TTS 回放能力

#### 里程碑
- **M1.1**: @discordjs/voice 集成，加入语音频道（2d）
- **M1.2**: 音频接收 + Opus 解码（2d）
- **M1.3**: VAD + STT 集成（2d）
- **M1.4**: TTS 合成 + Opus 编码 + 播放（3d）
- **M1.5**: 端到端联调 + 问题修复（3d）

#### 验收标准
```
场景：单用户在 Discord 语音频道
流程：用户说话 → Bot 识别 → OpenClaw 处理 → Bot 语音回复
延迟：P50 < 1.5s，P95 < 3s
支持：中英文对话
```

#### 技术要点

```python
# 半双工状态机
class ConversationState(Enum):
    IDLE = "idle"           # 等待用户说话
    LISTENING = "listening" # 正在录音
    PROCESSING = "processing" # STT + LLM 处理中
    SPEAKING = "speaking"   # TTS 播放中

# 状态转换
IDLE → (user_speech_start) → LISTENING
LISTENING → (silence_detected) → PROCESSING
PROCESSING → (llm_response_ready) → SPEAKING
SPEAKING → (playback_complete) → IDLE
```

### 6.4 Phase 2：插件化重构（2-3 周）

#### 目标
将 Speech Core 封装为 OpenClaw Gateway 插件，提供标准 RPC 接口

#### 交付物
- [ ] speech-core Python 服务独立部署
- [ ] speech-core Gateway 插件（RPC 客户端）
- [ ] discord-voice Gateway 插件
- [ ] 配置化的语音参数
- [ ] 多用户会话支持

#### 里程碑
- **M2.1**: Speech Core 服务独立化 + WebSocket RPC（3d）
- **M2.2**: Gateway 插件封装（4d）
- **M2.3**: 多用户会话隔离（3d）
- **M2.4**: 配置系统 + 文档（2d）
- **M2.5**: 集成测试 + 问题修复（3d）

#### 验收标准
```
部署：Speech Core 独立进程，Gateway 插件热加载
RPC：speech.stt / speech.tts / speech.status
会话：支持同一频道多用户（active speaker 模式）
配置：STT/TTS 引擎可配置切换
```

### 6.5 Phase 3：全双工打断（2-4 周）

#### 目标
实现自然对话体验：流式 TTS + 用户可打断

#### 交付物
- [ ] 流式 TTS（句子级分块）
- [ ] Barge-in 检测与处理
- [ ] 并发说话处理优化
- [ ] 延迟优化至目标水平

#### 里程碑
- **M3.1**: 流式 TTS 实现（5d）
- **M3.2**: Barge-in 控制器（4d）
- **M3.3**: LLM 输出 chunking（3d）
- **M3.4**: 延迟优化 + 调参（4d）
- **M3.5**: 用户体验打磨 + 文档（4d）

#### 验收标准
```
延迟：P50 < 1.0s，P95 < 2.0s
打断：用户说话时 Bot 立即停止
流式：TTS 边合成边播放
并发：正确处理多人同时说话
```

### 6.6 资源需求

| 资源 | Phase 0 | Phase 1 | Phase 2 | Phase 3 |
|------|---------|---------|---------|---------|
| 开发人力 | 0.5人 | 1人 | 1人 | 1人 |
| GPU（推荐） | 可选 | 推荐 | 推荐 | 必需 |
| 测试设备 | Discord 账号 | 同左 | 同左 | 同左 + 多账号 |
| 云服务 | 无 | ElevenLabs API（可选） | 同左 | 同左 |

---

## 7. 风险评估与缓解措施

### 7.1 技术风险

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| **Discord 语音 API 变更** | 低 | 高 | 锁定 @discordjs/voice 版本；关注官方变更日志 |
| **音频接收质量问题** | 中 | 中 | 丢包重传、抖动缓冲；参考 discospeech 实现 |
| **STT 识别准确率不足** | 中 | 中 | 提供模型选择（tiny→large）；支持云端 fallback |
| **TTS 延迟过高** | 中 | 中 | 流式合成；预合成高频回复；云端 fallback |
| **WSL GPU 加速问题** | 中 | 低 | 验证 CUDA 可用性；准备纯 CPU 方案 |
| **多用户并发性能** | 中 | 中 | 限制并发数；队列化处理 |

### 7.2 工程风险

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| **工期延误** | 中 | 中 | 保守估算（已 x1.5）；Phase 0 先验证核心风险 |
| **依赖库不稳定** | 低 | 中 | 锁定版本；容器化部署 |
| **Gateway 集成复杂** | 中 | 中 | 早期 PoC 验证插件机制 |

### 7.3 运维风险

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| **Speech Core 服务崩溃** | 低 | 高 | 健康检查 + 自动重启；降级到纯文本 |
| **资源耗尽（GPU/内存）** | 中 | 中 | 监控告警；请求队列限制 |
| **Discord 速率限制** | 低 | 低 | 批量化事件；优雅降级 |

### 7.4 风险优先级矩阵

```
           影响
     低    中    高
高  ┌────┬────┬────┐
    │    │    │ A1 │  A1: Discord API 变更
可  ├────┼────┼────┤
能  │    │B1 B2│ B3 │  B1: STT 准确率 B2: TTS 延迟 B3: 服务崩溃
性  ├────┼────┼────┤
低  │ C1 │ C2 │    │  C1: 速率限制 C2: 依赖库问题
    └────┴────┴────┘
```

---

## 8. 附录

### 8.1 技术选型对比

#### STT 引擎对比

| 引擎 | 延迟 | 准确率 | GPU 需求 | 中文支持 | 选择理由 |
|------|------|--------|----------|----------|----------|
| **faster-whisper** | 200-500ms | 优秀 | 推荐 | ✅ | **首选** - 平衡最佳 |
| whisper.cpp | 300-800ms | 优秀 | 可选 | ✅ | CPU 备选 |
| sherpa-onnx | 150-400ms | 良好 | 可选 | ✅ | 极致低延迟场景 |
| OpenAI Whisper API | 500-1500ms | 优秀 | 无 | ✅ | 云端 fallback |

#### TTS 引擎对比

| 引擎 | 延迟 | 音质 | 成本 | 中文支持 | 选择理由 |
|------|------|------|------|----------|----------|
| **Piper** | 200-500ms | 中等 | 免费 | ✅ | **本地首选** |
| Edge TTS | 300-600ms | 良好 | 免费 | ✅ | 备选（非实时可靠） |
| ElevenLabs | 300-800ms | 优秀 | $$$$ | ✅ | 高质量场景 |
| OpenAI TTS | 400-1000ms | 优秀 | $$$ | ✅ | 云端 fallback |

### 8.2 Discord 语音技术细节

#### 音频格式
- **采样率**: 48000 Hz
- **声道**: 单声道（Mono）或立体声（Stereo）
- **编码**: Opus（20ms 帧）
- **比特率**: 64-128 kbps（可配置）

#### @discordjs/voice 关键 API

```javascript
// 加入语音频道
const connection = joinVoiceChannel({
  channelId: voiceChannel.id,
  guildId: guild.id,
  adapterCreator: guild.voiceAdapterCreator,
  selfDeaf: false,  // 重要：必须为 false 才能接收
  selfMute: true
});

// 接收用户音频
connection.receiver.speaking.on('start', (userId) => {
  const audioStream = connection.receiver.subscribe(userId, {
    end: { behavior: EndBehaviorType.AfterSilence, duration: 600 }
  });
  // audioStream 是 Opus 编码的 Readable
});

// 播放音频
const player = createAudioPlayer();
const resource = createAudioResource(opusStream);
player.play(resource);
connection.subscribe(player);
```

### 8.3 参考资源

#### 官方文档
- [OpenClaw Voice Call Plugin](https://docs.openclaw.ai/plugins/voice-call)
- [OpenClaw Audio and Voice Notes](https://docs.openclaw.ai/nodes/audio)
- [@discordjs/voice Guide](https://discordjs.guide/voice/)

#### 开源项目
- [discospeech](https://github.com/ajr-dev/discospeech) - Discord 语音端到端实现
- [Pipecat](https://github.com/pipecat-ai/pipecat) - 实时语音 Agent 框架
- [faster-whisper](https://github.com/guillaumekln/faster-whisper) - 高性能 Whisper 实现
- [Piper](https://github.com/rhasspy/piper) - 本地 TTS 引擎

#### 学习资源
- [Discord Voice Gateway Protocol](https://discord.com/developers/docs/topics/voice-connections)
- [Opus Codec](https://opus-codec.org/docs/)
- [WebRTC for the Curious](https://webrtcforthecurious.com/)

### 8.4 术语表

| 术语 | 解释 |
|------|------|
| **VAD** | Voice Activity Detection，语音活动检测 |
| **Barge-in** | 用户打断机器人说话的能力 |
| **RTF** | Real-Time Factor，处理时间/音频时长，<1 表示实时 |
| **Opus** | 开源音频编码格式，适合实时语音 |
| **Jitter Buffer** | 抖动缓冲，用于平滑网络延迟波动 |
| **PLC** | Packet Loss Concealment，丢包隐藏技术 |
| **Half-duplex** | 半双工，一方说话时另一方必须听 |
| **Full-duplex** | 全双工，双方可同时说话 |

---

## 变更历史

| 版本 | 日期 | 作者 | 变更内容 |
|------|------|------|----------|
| v1.0 | 2026-02-10 | 架构师 | 初版，综合两份材料评估 |

---

*本报告由高级系统架构师根据用户原始架构评估与 GPT 建议综合分析生成。*
