# P1-1 架构调研报告

> 日期：2026-02-17
> 调研方式：Web 搜索 + GitHub 项目分析 + 行业文章 + 子代理深度调研

---

## 一、行业三大架构模式

### 1. 级联管道 (Cascaded Pipeline) — 最常见
```
语音 → STT → LLM → TTS → 语音
```
- **每步等上一步完成**，延迟叠加
- Twilio 基准（2025.11）：STT 350ms + LLM 375ms + TTS 100ms + 网络/编解码 ≈ **1.1s 端到端**
- **优点**：简单、模块化、可独立替换组件
- **缺点**：延迟高、丢失语音情感信息
- **所有 GitHub 开源 Discord 项目都用这个架构**

### 2. 半级联/Speech-to-Speech (Half-Cascade)
```
语音 → Audio Encoder → Text LLM → TTS → 语音
```
- 原生音频输入，文本层推理，语音输出
- 代表：OpenAI Realtime API (gpt-realtime)、Gemini Live 2.5 Flash
- **延迟 200-300ms**
- **缺点**：成本高（~10x 级联）、依赖特定 API、TTS 音质不如专业 TTS

### 3. 原生音频模型 (End-to-End)
```
语音 → 统一模型 → 语音
```
- 单一模型直接处理音频到音频
- 代表：Gemini 2.5 Flash Native Audio、Moshi (Kyutai Labs)
- **延迟最低**，保留情感
- **缺点**：难控制、不透明、灵活性差

---

## 二、GitHub 开源项目分析

### 项目 1：Discord-VC-LLM (Eidenz) ⭐33
- **语言**：JavaScript (Node.js)
- **架构**：级联管道，单文件 `bot.js`
- **STT**：OpenAI Whisper API（远程）
- **LLM**：OpenAI 兼容 API
- **TTS**：OpenAI 兼容 API → MP3 → FFmpeg 播放
- **流程**：`!join` → 订阅用户 Opus 流 → AfterSilence 结束 → WAV 文件 → Whisper API → LLM → TTS → 播放
- **特点**：支持触发词模式 vs 自由模式、支持打断（say "stop"）
- **已归档**（2025-02-01）

### 项目 2：Discord-AI-With-STT (pladisdev) ⭐26
- **语言**：Python (discord.py)
- **架构**：级联管道 + 多种 Sink 模式
- **STT**：Whisper 本地 / Deepgram 流式 / Whisper Stream
- **LLM**：OpenAI API
- **TTS**：未明确
- **核心创新**：**3 种音频接收模式**
  - 标准 Whisper：缓冲全部 → 批量转写（高延迟）
  - Deepgram Sink：**流式 STT**（显著降低延迟）
  - Whisper Stream：增量处理（不会因长语音变慢）
- **多用户**：每用户独立转写

### 项目 3：Discord-Realtime-STT-Bot (Leehyunbin) ⭐新
- **语言**：Python (discord.py)
- **架构**：**多进程隔离** — 这是最工程化的方案
- **STT**：Faster-Whisper (CTranslate2, 4x 加速)
- **VAD**：Silero VAD
- **核心设计**：
  ```
  Main Process（Discord Bot）        STT Process（隔离）
  ├── AudioSink                      ├── UserStateManager
  ├── Resampler (48kHz→16kHz)        ├── Silero VAD (32ms frames)
  ├── IPC Audio Queue ──────────────→├── Faster-Whisper
  │                    ←──────────── ├── IPC Result Queue
  └── ResultHandler                  └──
  ```
- **关键技术**：
  - torchaudio Kaiser 窗口抗混叠重采样
  - 320ms 环形缓冲区（不丢首音节）
  - Per-User 状态机
  - 优雅关闭（信号处理）
- **无 LLM/TTS 集成**（纯 STT）

### 项目 4：discord-voice-ai (itzzkirito)
- **语言**：TypeScript (discord.js)
- **架构**：级联管道
- **STT**：Whisper API
- **LLM**：GPT-4
- **TTS**：ElevenLabs API
- **特点**：SQLite 持久化、Prisma ORM

### 项目 5：Discord-Voice-Channel-Bot (Gemeri)
- **语言**：Python
- **STT**：OpenAI Whisper API
- **TTS**：Microsoft 免费 TTS
- **特点**：低成本方案（微软 TTS 免费）

### 项目 6：Saya Voice Assistant (KickerMix)
- **语言**：Python
- **架构**：全本地
- **STT**：Faster-Whisper
- **LLM**：LM Studio (本地)
- **TTS**：XTTS v2（语音克隆）
- **特点**：关键词激活、完全本地运行

---

## 三、AssemblyAI 教程参考架构（discord.js）

最完整的端到端教程（AssemblyAI 官方博客）：

```
discord.js + @discordjs/voice
    ↓
connection.receiver.subscribe(userId, { end: AfterSilence })
    ↓ Opus → PCM (ffmpeg-static + @discordjs/opus)
写入 PCM 文件
    ↓
AssemblyAI STT (远程 API)
    ↓ 文本
OpenAI ChatGPT API
    ↓ 回复文本
ElevenLabs TTS API → MP3 文件
    ↓
createAudioResource(mp3) → AudioPlayer → 播放到语音频道
```

依赖：`discord.js libsodium-wrappers ffmpeg-static @discordjs/opus @discordjs/voice`

---

## 四、延迟基准数据

| 来源 | STT | LLM (TTFT) | TTS (TTFB) | 端到端 |
|------|-----|------------|-----------|--------|
| Twilio (2025.11) | 350ms | 375ms | 100ms | **~1.1s** |
| Introl (2025) | 200ms | 500ms | 150ms | **~1.0s** |
| 流式优化后 | 150ms | 200ms | 80ms | **~500ms** |
| OpenAI Realtime API | — | — | — | **200-300ms** |

---

## 五、关键延迟优化技术

### 5.1 流式 STT（最大收益）
- **标准模式**：等用户说完 → 全量转写 → 1-5s 延迟
- **流式模式**：用户说话同时转写 → 300ms 延迟
- 选项：Deepgram (流式)、AssemblyAI Universal-Streaming、WhisperLive

### 5.2 LLM 流式输出 + Chunker
- LLM 输出第一个 token 开始 → 按句子切分 → 每句立即送 TTS
- 不等 LLM 全部输出完
- **我们已有 `chunker.py` 实现**

### 5.3 TTS 流式合成
- ElevenLabs 支持流式（WebSocket）
- Piper 本地延迟已经很低

### 5.4 进程隔离（Discord-Realtime-STT-Bot 的经验）
- STT 推理（GPU 密集）放独立进程
- Bot 主进程永不阻塞
- IPC 队列通信

---

## 六、P1-1 推荐架构

### 核心原则
1. **级联管道**（成熟、可控、模块化）
2. **直接调 LLM API**（P1-1 验证阶段，不走 Gateway webhook）
3. **本地 STT + TTS**（faster-whisper + Piper，降低网络延迟）
4. **流式处理后续优化**（P1-1 先用批量模式跑通，P3 再上流式）

### 推荐架构图
```
Discord 语音频道
    ↓ @discordjs/voice receiver
    ↓ Opus 音频流 (48kHz)

┌─────── TypeScript (discord-voice 插件) ───────┐
│                                                │
│  OpusToPCMStream (48kHz → 16kHz)              │
│      ↓ PCM Base64                              │
│  WebSocket → Speech Core                       │
│      ↓                                         │
└────────────────────────────────────────────────┘

┌─────── Python (Speech Core 服务) ─────────────┐
│                                                │
│  Silero VAD → 语音分段                         │
│      ↓                                         │
│  Faster-Whisper STT → 文本                     │
│      ↓                                         │
│  HTTP → LLM API (Anthropic/OpenAI)            │
│      ↓ 回复文本                                │
│  Piper TTS → PCM 音频                          │
│      ↓ Base64                                  │
│  WebSocket → 返回给 TS 插件                    │
│                                                │
└────────────────────────────────────────────────┘

┌─────── TypeScript (discord-voice 插件) ───────┐
│                                                │
│  PCMToOpusStream (22kHz → 48kHz)              │
│      ↓                                         │
│  AudioPlayer → 播放到语音频道                   │
│                                                │
└────────────────────────────────────────────────┘
```

### 为什么 LLM 放在 Speech Core 里而不走 Gateway？

| 方案 | 延迟 | 复杂度 | 适合阶段 |
|------|------|--------|----------|
| A. Speech Core 直调 LLM API | **最低** | 低 | **P1-1 ✅** |
| B. /hooks/agent (Gateway webhook) | 高（异步202） | 低 | P0-2 语音留言 |
| C. Gateway 插件内部 dispatch | 中等 | 高 | Phase 2 目标 |

- P0-2 的 `/hooks/agent` 是异步的（返回 202），拿不到同步回复文本
- P1-1 需要同步拿到 LLM 文本才能 TTS → 只能 A 或 C
- A 最简单，P1-1 先验证链路通不通

### 后续演进路径
```
P1-1: Speech Core 直调 LLM API（验证链路）
  ↓
P2-2: 接入 Gateway Plugin API（获得 session 管理、memory、tools）
  ↓
P3: 流式 STT + LLM streaming + TTS streaming（延迟优化）
```

---

## 七、与我们现有代码的差距分析

| 组件 | 现有状态 | P1-1 需要 |
|------|----------|-----------|
| DiscordVoiceAdapter | ✅ 已完成 | 已有 |
| OpusToPCMStream | ✅ 已完成 | 已有 |
| Silero VAD | ✅ 已完成 | 已有 |
| Faster-Whisper STT | ✅ 已完成 | 已有 |
| Piper TTS | ✅ 已完成（已修复） | 已有 |
| PCMToOpusStream | ✅ 已完成 | 已有 |
| **LLM API 调用** | ❌ 缺失 | **需要新增** |
| **端到端编排** | ❌ 缺失 | **需要新增** |
| Speech Core WebSocket | ✅ 已完成 | 需要扩展 RPC 方法 |

**结论：代码基础已有 80%，主要缺 LLM 对接和端到端编排。**
