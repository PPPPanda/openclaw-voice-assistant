#!/usr/bin/env npx tsx
/**
 * P0-2 验证脚本：测试 VoiceMessageAdapter → OpenClaw Gateway 对接
 *
 * 不依赖 Speech Core 和 Discord，直接模拟转写结果并发送到 Gateway。
 *
 * 用法：
 *   OPENCLAW_GATEWAY_URL=http://localhost:18790 \
 *   OPENCLAW_HOOKS_TOKEN=<your-token> \
 *   DISCORD_CHANNEL_ID=<target-channel> \
 *   npx tsx scripts/test_gateway_dispatch.ts [message]
 *
 * 环境变量：
 *   OPENCLAW_GATEWAY_URL  - Gateway 地址 (默认 http://localhost:18790)
 *   OPENCLAW_HOOKS_TOKEN  - Hooks 认证 Token (必填)
 *   DISCORD_CHANNEL_ID    - 目标 Discord 频道 ID (必填)
 */

const GATEWAY_URL = process.env.OPENCLAW_GATEWAY_URL ?? 'http://localhost:18790';
const HOOKS_TOKEN = process.env.OPENCLAW_HOOKS_TOKEN;
const CHANNEL_ID = process.env.DISCORD_CHANNEL_ID;

if (!HOOKS_TOKEN) {
  console.error('❌ OPENCLAW_HOOKS_TOKEN is required');
  process.exit(1);
}

if (!CHANNEL_ID) {
  console.error('❌ DISCORD_CHANNEL_ID is required');
  process.exit(1);
}

const message = process.argv.slice(2).join(' ') || '你好，这是一条语音转写测试消息。';

async function main() {
  console.log('🎤 P0-2 Gateway Dispatch Test');
  console.log(`   Gateway: ${GATEWAY_URL}`);
  console.log(`   Channel: ${CHANNEL_ID}`);
  console.log(`   Message: "${message}"`);
  console.log('');

  // Step 1: Health check
  console.log('1️⃣  Checking Gateway health...');
  try {
    const healthResp = await fetch(`${GATEWAY_URL}/`, { method: 'GET' });
    console.log(`   Gateway responded: ${healthResp.status} ${healthResp.statusText}`);
  } catch (err) {
    console.error(`   ❌ Gateway unreachable: ${err}`);
    process.exit(1);
  }

  // Step 2: Dispatch via /hooks/agent
  console.log('2️⃣  Dispatching to /hooks/agent...');

  const payload = {
    message: `[🎤 Voice Test] ${message}`,
    name: 'VoiceMessage',
    deliver: true,
    channel: 'discord',
    to: CHANNEL_ID,
    sessionKey: `hook:voice:test:${Date.now()}`,
  };

  console.log(`   Payload: ${JSON.stringify(payload, null, 2)}`);

  try {
    const response = await fetch(`${GATEWAY_URL}/hooks/agent`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${HOOKS_TOKEN}`,
      },
      body: JSON.stringify(payload),
    });

    const body = await response.text();

    if (response.ok) {
      console.log(`   ✅ Accepted: ${response.status}`);
      if (body) console.log(`   Response: ${body.slice(0, 200)}`);
      console.log('');
      console.log('🎉 Dispatch successful! Check your Discord channel for the LLM response.');
    } else {
      console.error(`   ❌ Failed: ${response.status} ${response.statusText}`);
      console.error(`   Body: ${body.slice(0, 500)}`);

      if (response.status === 401) {
        console.error('');
        console.error('💡 Auth failed. Make sure:');
        console.error('   1. hooks.enabled = true in openclaw.json');
        console.error('   2. OPENCLAW_HOOKS_TOKEN matches hooks.token');
      }

      if (response.status === 404) {
        console.error('');
        console.error('💡 Endpoint not found. Make sure hooks are enabled:');
        console.error('   Add to openclaw.json: "hooks": { "enabled": true, "token": "..." }');
      }
    }
  } catch (err) {
    console.error(`   ❌ Request failed: ${err}`);
  }
}

main().catch(console.error);
