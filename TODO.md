# OpenClaw Voice Gateway — TODO & 开发路线图

> **最后更新**: 2026-02-17  
> **目的**: 跟踪未完成功能，方便多人协作与后续开发  
> **约定**: 每完成一项请将 `[ ]` 改为 `[x]` 并注明完成日期

---

## 当前进度概览

| 阶段 | 状态 | 完成度 |
|------|------|--------|
| Phase 0 — 语音留言验证 | **脚本+适配器已完成，待集成测试** | ~60% |
| Phase 1 — 半双工对讲 | **代码就绪，待集成测试** | ~70% |
| Phase 2 — 插件化重构 | **会话管理器已完成** | ~90% |
| Phase 3 — 全双工打断 | **BargeIn + Chunker 已完成** | ~40% |

---

## Phase 0 — 语音留言验证（优先级：🔴 最高）

> **目标**: 绕开 Discord 实时语音的复杂度，先验证 STT + OpenClaw 集成链路  
> **预计**: 1-2 天

- [x] **P0-1** (✅ 2026-02-17): 创建 VoiceMessage Adapter
  - 监听 Discord 频道中的语音附件/语音留言消息
  - 自动下载音频文件并转换为 PCM
  - 调用 `speech.stt` 获取转写文本
  - 文件: `gateway-plugins/discord-voice/src/voiceMessageAdapter.ts`

- [x] **P0-2** (✅ 2026-02-17): OpenClaw Gateway 对接
  - 使用 `/hooks/agent` Webhook API 发送转写文本
  - 自动投递 LLM 回复到 Discord 频道（`deliver: true, channel: "discord"`）
  - 配置文档：`docs/gateway-hooks-setup.md`
  - 验证脚本：`scripts/test_gateway_dispatch.ts`
  - 前置条件：在 `openclaw.json` 中启用 `hooks.enabled: true`

- [x] **P0-3** (✅ 2026-02-17): 本地 STT 环境验证脚本
  - 编写独立的 Python 脚本验证 faster-whisper 安装和推理
  - 测量不同模型(tiny/base/small)在目标机器上的延迟
  - 文件: `speech-core/scripts/benchmark_stt.py`

- [x] **P0-4** (✅ 2026-02-17): 延迟基准测试工具
  - 创建端到端延迟测试脚本（STT + LLM + TTS 全链路）
  - 记录 P50/P95 数据作为后续优化基线
  - 文件: `speech-core/scripts/benchmark_e2e.py`

- [x] **P0-5** (✅ 2026-02-17): 中英文 STT 准确率测试
  - 准备中文和英文测试音频文件到 `speech-core/tests/fixtures/audio/`
  - 编写准确率评估脚本（与参考文本对比 WER/CER）
  - 文件: `speech-core/scripts/evaluate_accuracy.py`

---

## Phase 1 — 半双工对讲（优先级：🟠 高）

> **目标**: 实现 Discord 语音频道的单用户半双工对话  
> **预计**: 7-14 天  
> **注意**: 代码骨架已完成，重点在集成调试

- [ ] **P1-1**: 端到端集成测试
  - 用真实 Discord Bot Token 测试完整流程
  - 验证: 加入频道 → 接收音频 → STT → LLM → TTS → 播放
  - 记录并修复实际运行中发现的问题

- [ ] **P1-2**: Opus 编解码验证
  - 验证 `OpusToPCMStream`（48kHz→16kHz）音质是否可接受
  - 验证 `PCMToOpusStream`（22050→48kHz）播放是否正常
  - 如不理想，考虑使用 FFmpeg 替代线性插值重采样

- [ ] **P1-3**: VAD 参数调优
  - 在真实 Discord 语音环境中测试 Silero VAD
  - 调整 `threshold`、`min_silence_ms`、`min_speech_ms` 参数
  - 解决可能的误触发问题（背景噪声、键盘声等）

- [ ] **P1-4**: TTS 输出音频格式兼容
  - 确认 Piper TTS 输出采样率（22050Hz）→ Discord（48kHz Opus）转换正确
  - 测试中文和英文语音合成效果
  - 如 Piper 中文音质不足，评估替代方案

- [ ] **P1-5**: 错误处理与优雅降级
  - STT 失败时的回退逻辑（重试 / 提示用户）
  - TTS 失败时的回退逻辑（发文本消息代替语音）
  - Speech Core 服务不可用时的降级处理
  - WebSocket 断连恢复

- [ ] **P1-6**: Discord Bot 命令支持
  - 实现 `/join` 命令让 Bot 加入语音频道
  - 实现 `/leave` 命令让 Bot 离开
  - 实现 `/voice-status` 命令查看语音服务状态

---

## Phase 2 — 插件化重构（优先级：🟡 中）

> **目标**: 正式对接 OpenClaw Gateway 插件体系，支持多用户  
> **预计**: 2-3 周

- [x] **P2-1** (✅ 2026-02-17): 多用户会话管理
  - 实现 `SessionManager` 类，按 `voiceChannelId + userId` 隔离会话
  - 每个用户独立的对话历史和状态机
  - Active Speaker 策略：同一时刻只处理一个活跃用户
  - 文件: `speech-core/speech_core/session/manager.py`

- [ ] **P2-2**: OpenClaw Gateway 插件接口适配
  - 研究 OpenClaw Gateway 的插件注册机制
  - 将 `SpeechCorePlugin` 适配为标准 Gateway 插件格式
  - 实现 Gateway RPC 注册: `speech.stt` / `speech.tts` / `speech.status`

- [ ] **P2-3**: 配置热加载
  - 支持运行时切换 STT 模型（tiny↔base↔small）
  - 支持运行时切换 TTS 引擎（Piper↔ElevenLabs）
  - 通过 RPC 接口: `speech.config.update`

- [ ] **P2-4**: 语音参数可配置化
  - 每个 Guild/频道可独立配置语音参数（语言、模型、语音角色等）
  - 配置持久化（数据库或文件）
  - 管理命令: `/voice-config set <key> <value>`

- [ ] **P2-5**: Gateway 插件集成测试
  - 模拟 Gateway 环境的集成测试
  - 验证插件热加载/卸载
  - 验证 RPC 调用链路完整性

---

## Phase 3 — 全双工打断（优先级：🟢 中低）

> **目标**: 实现自然的全双工对话体验  
> **预计**: 2-4 周

- [ ] **P3-1**: 真正的流式 STT
  - 替换当前"缓冲全部再转写"为增量流式转写
  - 研究 faster-whisper 的流式/分段转写方案
  - 或集成 sherpa-onnx 的实时流式模型
  - 目标: 用户说话过程中即可开始处理

- [x] **P3-2** (✅ 2026-02-17): LLM 输出流式 Chunker
  - 将 LLM 的 streaming token 输出按句子粒度切分
  - 每凑齐一个完整句子立即送 TTS 合成
  - 减少首帧延迟（不等 LLM 全部输出完）
  - 文件: `speech-core/speech_core/pipeline/chunker.py`

- [ ] **P3-3**: 流式 TTS 优化
  - 将当前句子级流式改为更细粒度（子句/分句）
  - Piper: 研究是否支持增量合成
  - ElevenLabs: 已支持 streaming，需要对接

- [ ] **P3-4**: Barge-in 端到端验证
  - 在真实环境测试 BargeInController 的三种策略
  - 验证打断后 TTS 立即停止播放
  - 验证打断后 VAD/分段器正确重置
  - 调优 `confirm_duration_ms` 和 `cooldown_ms`

- [ ] **P3-5**: 并发说话处理
  - 多人同时说话时的仲裁策略（Active Speaker）
  - 音频混流/分流处理
  - 对其他非活跃用户的排队/忽略逻辑

- [ ] **P3-6**: 延迟优化冲刺
  - 目标: P50 ≤ 1.0s, P95 ≤ 2.0s
  - 各阶段延迟 profiling 并定位瓶颈
  - STT: 模型量化、GPU batch、vad_filter 优化
  - TTS: 预合成高频回复、缓存机制
  - 网络: PCM 传输优化、减少 JSON 序列化开销

---

## 基础设施 & 工程质量（优先级：持续）

### 测试

- [x] **T-1** (✅ 2026-02-17): 补充 VAD 单元测试
  - 用 MockSileroVAD 测试状态转换、边界条件、最大时长切断
  - 文件: `speech-core/tests/test_vad.py`

- [x] **T-2** (✅ 2026-02-17): 补充 SegmentBuffer 测试
  - 测试前导缓冲、分段流程、属性、重置、边界情况
  - 文件: `speech-core/tests/test_segment.py`

- [x] **T-3** (✅ 2026-02-17): 补充 SpeechPipeline 集成测试
  - Mock STT/TTS 引擎，测试状态机、回调、speak、打断
  - 文件: `speech-core/tests/test_speech_pipeline.py`

- [x] **T-4** (✅ 2026-02-17): WebSocket RPC 服务器测试
  - JSON-RPC 2.0 协议、方法路由、错误处理（25 tests）
  - 文件: `speech-core/tests/test_rpc.py`

- [ ] **T-5**: TypeScript 插件测试
  - 为 `SpeechCoreClient` 编写单元测试（Mock WebSocket）
  - 为 `DiscordVoiceAdapter` 编写单元测试（Mock Discord.js）
  - 为 `OpusToPCMStream` / `PCMToOpusStream` 编写编解码测试

- [ ] **T-6**: 启用 CI 中的集成测试
  - 将 `@pytest.mark.skipif(True)` 改为条件判断（如模型文件存在时才运行）
  - 在 CI 环境中缓存模型文件

### DevOps

- [x] **D-1** (✅ 2026-02-17): CI/CD 流水线
  - GitHub Actions: Python lint(ruff) + typecheck(mypy) + test(pytest) + TS lint + build
  - Matrix: Python 3.11/3.12
  - 文件: `.github/workflows/ci.yml`

- [x] **D-2** (✅ 2026-02-17): Dockerfile 完善
  - 多阶段构建、非 root 用户、健康检查
  - GPU 版本：`speech-core/Dockerfile.gpu`（CUDA 12.2）

- [ ] **D-3**: 监控与可观测性
  - 添加 Prometheus 指标导出（延迟、请求数、错误率）
  - 结构化日志增强（request_id、user_id 追踪）
  - Grafana 仪表盘模板

- [ ] **D-4**: 生产部署文档
  - WSL2 GPU 加速配置详细步骤
  - 系统资源监控建议（GPU 内存、CPU 使用率）
  - 模型文件预下载脚本

---

## 已知技术债务

| 编号 | 位置 | 描述 | 严重度 |
|------|------|------|--------|
| TD-1 | `stt/whisper.py` | `transcribe_stream()` 是假流式（缓冲全部再转写），有 TODO 注释 | 中 |
| TD-2 | `stt/engine.py` | 基类 `transcribe_stream()` 默认实现中有冗余的 AudioData 构造（构造了两次） | 低 |
| TD-3 | `discord-voice/receiver.ts` | 线性插值重采样（48k→16k）音质一般，生产环境应换 FFmpeg 或 libsamplerate | 中 |
| TD-4 | `discord-voice/player.ts` | 线性插值上采样（22k→48k）同上 | 中 |
| TD-5 | `tts/elevenlabs.py` | 流式模式 `TTSChunk.duration_ms` 硬编码为 0 | 低 |
| TD-6 | `server.py` | `_method_handlers` 作为类变量使用自引用方法，类型标注为 `dict[str, Any]` 不够类型安全 | 低 |
| TD-7 | 全局 | 无独立的采样率转换模块，重采样代码分散在 STT(Python) 和 Receiver/Player(TS) 中 | 低 |
| TD-8 | 全局 | 无回声消除（Echo Cancellation）支持 | 中 |
| TD-9 | 全局 | 无抖动缓冲（Jitter Buffer）/ 丢包隐藏（PLC）处理 | 低 |

---

## 开发指南

### 认领任务

1. 在本文档中找到想做的任务
2. 在任务前标注你的名字，如 `- [ ] **P1-1** (👤 @张三): ...`
3. 完成后改为 `- [x] **P1-1** (👤 @张三, ✅ 2026-02-15): ...`

### 开发顺序建议

```
推荐顺序（关键路径）:

P0-3 (STT验证) → P0-1 (语音留言) → P0-2 (OpenClaw对接)
       ↓
P1-1 (端到端集成) → P1-2 (编解码) → P1-3 (VAD调优)
       ↓
P1-5 (错误处理) → P1-6 (Bot命令) → P2-1 (多用户)
       ↓
P3-1 (流式STT) → P3-2 (Chunker) → P3-6 (延迟优化)

可并行的任务（不阻塞主路径）:
- T-* 所有测试任务
- D-* 所有 DevOps 任务
- P2-3 配置热加载
- P2-4 语音参数配置
```

### 快速开始开发

```bash
# 1. Speech Core (Python)
cd speech-core
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
pytest  # 运行现有测试

# 2. Gateway Plugins (TypeScript)
cd gateway-plugins/speech-core
npm install && npm run build

cd ../discord-voice
npm install && npm run build
```
