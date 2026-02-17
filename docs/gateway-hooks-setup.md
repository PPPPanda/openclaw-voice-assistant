# OpenClaw Gateway Hooks 配置（P0-2 前置条件）

语音消息适配器通过 OpenClaw 的 Webhook API 将 STT 转写文本发送给 AI 处理。

## 1. 启用 Hooks

在 `~/.openclaw/openclaw.json` 中添加 `hooks` 配置：

```json
{
  "hooks": {
    "enabled": true,
    "token": "<生成一个随机 token>",
    "path": "/hooks",
    "allowRequestSessionKey": true,
    "allowedSessionKeyPrefixes": ["hook:voice:"]
  }
}
```

生成 token：
```bash
openssl rand -hex 24
```

## 2. 重启 Gateway

```bash
# 方式 1：通过 OpenClaw CLI
openclaw gateway restart

# 方式 2：kill 进程让 daemon 重拉
kill $(pgrep -f openclaw-gateway)
```

## 3. 验证

```bash
# 测试 hooks 端点可用
curl -s -X POST http://localhost:18790/hooks/wake \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{"text":"Voice hooks test","mode":"now"}'
# 预期：200 OK
```

## 4. 配置环境变量

在 `.env` 中设置：

```
OPENCLAW_GATEWAY_URL=http://localhost:18790
OPENCLAW_HOOKS_TOKEN=<和上面的 token 一致>
```

## 5. 运行验证脚本

```bash
OPENCLAW_GATEWAY_URL=http://localhost:18790 \
OPENCLAW_HOOKS_TOKEN=<token> \
DISCORD_CHANNEL_ID=<频道ID> \
npx tsx scripts/test_gateway_dispatch.ts "你好，测试语音消息"
```

## 架构说明

```
Discord 语音消息
    ↓ (VoiceMessageAdapter 下载 + 解码)
Speech Core STT 转写
    ↓ (POST /hooks/agent)
OpenClaw Gateway
    ↓ (隔离 session, AI 处理)
LLM 回复
    ↓ (自动投递到 Discord)
用户看到文本回复
```

**优势：**
- VoiceMessageAdapter 不需要管理 OpenClaw session
- 复用现有 Discord 插件的消息投递能力
- 每条语音消息独立 session key，互不干扰
- deliver=true 让 Gateway 自动回复到 Discord 频道
