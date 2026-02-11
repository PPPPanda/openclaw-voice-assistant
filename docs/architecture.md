# 架构文档

## 概述

OpenClaw Voice Gateway 采用三层解耦架构，实现可扩展的实时语音对话能力。

## 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                   Transport Layer (平台适配器)                │
│  DiscordVoiceAdapter  │  VoiceMessageAdapter  │  WebRTC*    │
│  加入房间/收发音频帧/用户事件/权限管理                        │
└────────────────────────────┬────────────────────────────────┘
                             │ PCM / Events
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   Speech Core Layer (语音中台)                │
│  VAD → SegmentBuffer → STT → Text Output                    │
│  Text Input → Chunker → TTS → PCM Output                    │
│  BargeIn Controller / SampleRate Converter                   │
└────────────────────────────┬────────────────────────────────┘
                             │ Text / Commands
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              OpenClaw Gateway (Orchestrator)                  │
│  Session Manager │ LLM Router │ Tool Executor │ Memory      │
└─────────────────────────────────────────────────────────────┘
```

## 各层职责

### Transport Layer

- **DiscordVoiceAdapter**: Discord 语音频道连接管理、Opus 音频收发
- **VoiceMessageAdapter**: Discord 语音附件/留言处理（Phase 0）
- **WebRTCAdapter**: 自建实时通信（未来扩展）

### Speech Core Layer

- **VAD (Silero)**: 语音活动检测，区分说话/静音
- **SegmentBuffer**: 将连续音频流切割为离散语音段
- **STT (faster-whisper / whisper.cpp)**: 语音转文字
- **TTS (Piper / ElevenLabs)**: 文字转语音
- **BargeIn Controller**: 打断控制（Phase 3）
- **SpeechPipeline**: 协调各组件的主流水线

### OpenClaw Gateway

- **Session Manager**: 按 channelId 管理对话会话
- **LLM Router**: 多模型路由与回退
- **Tool Executor**: 技能/工具调用

## 通信协议

Transport ↔ Speech Core: **WebSocket + JSON-RPC 2.0**

详见 [api-reference.md](api-reference.md)

## 半双工状态机

```
IDLE → (user_speech_start) → LISTENING
LISTENING → (silence_detected) → PROCESSING
PROCESSING → (llm_response_ready) → SPEAKING
SPEAKING → (playback_complete) → IDLE
```

## 延迟预算 (P50 ≤ 1.0s)

| 阶段 | 目标延迟 |
|------|----------|
| VAD 检测 | 150ms |
| 音频传输 | 50ms |
| STT 转写 | 300ms |
| LLM 首 token | 200ms |
| TTS 首帧 | 200ms |
| 播放启动 | 100ms |
| **总计** | **1000ms** |

## 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| STT | faster-whisper (GPU) / whisper.cpp (CPU) | 性能最优 |
| TTS | Piper (本地) + ElevenLabs (云端) | 延迟低 / 音质好 |
| VAD | Silero VAD | 轻量、准确 |
| 通信 | WebSocket + JSON-RPC 2.0 | 双向通信、标准协议 |
