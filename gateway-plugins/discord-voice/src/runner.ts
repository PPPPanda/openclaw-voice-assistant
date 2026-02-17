/**
 * Voice Pipeline Runner (P1-1)
 *
 * 独立运行器：启动 Discord bot → 加入语音频道 → 运行完整管线。
 * 用于端到端测试和独立部署。
 *
 * Usage:
 *   npx tsx src/runner.ts
 *
 * 环境变量：
 *   DISCORD_BOT_TOKEN    - Discord Bot Token
 *   DISCORD_GUILD_ID     - 目标 Guild ID
 *   DISCORD_CHANNEL_ID   - 目标语音频道 ID
 *   SPEECH_CORE_ENDPOINT - Speech Core WebSocket 端点 (默认 ws://localhost:9001/speech)
 *   LLM_API_ENDPOINT     - LLM API 端点 (默认 https://api.openai.com/v1)
 *   LLM_API_KEY          - LLM API Key
 *   LLM_MODEL            - 模型名称 (默认 gpt-4o-mini)
 *   TTS_PROVIDER         - TTS 提供者 (默认 piper)
 *   STT_LANGUAGE         - STT 语言 (默认 auto)
 */

import { Client, GatewayIntentBits, VoiceChannel } from 'discord.js';
import { StreamType } from '@discordjs/voice';
import { Readable } from 'stream';
import { DiscordVoiceAdapter } from './adapter';
import { VoicePipeline, VoicePipelineConfig } from './pipeline';
import { PCMToOpusStream, createAudioResourceFromPCM } from './player';
import { SpeechCoreClient } from '../../speech-core/src/client';

// ============================================================================
// 配置
// ============================================================================

function loadConfig() {
  const botToken = process.env.DISCORD_BOT_TOKEN;
  const guildId = process.env.DISCORD_GUILD_ID;
  const channelId = process.env.DISCORD_CHANNEL_ID;

  if (!botToken || !guildId || !channelId) {
    console.error('Missing required environment variables:');
    console.error('  DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, DISCORD_CHANNEL_ID');
    process.exit(1);
  }

  const llmApiKey = process.env.LLM_API_KEY;
  if (!llmApiKey) {
    console.error('Missing LLM_API_KEY environment variable');
    process.exit(1);
  }

  return {
    botToken,
    guildId,
    channelId,
    speechCoreEndpoint: process.env.SPEECH_CORE_ENDPOINT ?? 'ws://localhost:9001/speech',
    llm: {
      apiEndpoint: process.env.LLM_API_ENDPOINT ?? 'https://api.openai.com/v1',
      apiKey: llmApiKey,
      model: process.env.LLM_MODEL ?? 'gpt-4o-mini',
      maxTokens: 256,
      temperature: 0.7,
    },
    ttsProvider: (process.env.TTS_PROVIDER ?? 'piper') as 'piper' | 'elevenlabs' | 'openai',
    sttLanguage: process.env.STT_LANGUAGE ?? 'auto',
  };
}

// ============================================================================
// Logger
// ============================================================================

const logger = {
  info: (msg: string, ...args: unknown[]) => console.log(`[INFO]  ${msg}`, ...args),
  warn: (msg: string, ...args: unknown[]) => console.warn(`[WARN]  ${msg}`, ...args),
  error: (msg: string, ...args: unknown[]) => console.error(`[ERROR] ${msg}`, ...args),
  debug: (msg: string, ...args: unknown[]) => {
    if (process.env.DEBUG) console.log(`[DEBUG] ${msg}`, ...args);
  },
};

// ============================================================================
// Main
// ============================================================================

async function main() {
  const config = loadConfig();

  logger.info('=== Voice Pipeline Runner (P1-1) ===');
  logger.info(`Guild: ${config.guildId}`);
  logger.info(`Channel: ${config.channelId}`);
  logger.info(`LLM: ${config.llm.model} @ ${config.llm.apiEndpoint}`);
  logger.info(`TTS: ${config.ttsProvider}`);
  logger.info(`STT Language: ${config.sttLanguage}`);

  // ── 1. 连接 Speech Core ────────────────────────────────────────────────
  logger.info('Connecting to Speech Core...');
  const speechCore = new SpeechCoreClient({
    endpoint: config.speechCoreEndpoint,
  });

  speechCore.on('connected', () => logger.info('Speech Core connected'));
  speechCore.on('disconnected', (code: number) =>
    logger.warn(`Speech Core disconnected: ${code}`),
  );
  speechCore.on('error', (err: Error) =>
    logger.error(`Speech Core error: ${err.message}`),
  );

  await speechCore.connect();

  // 验证 Speech Core 状态
  const status = await speechCore.status();
  logger.info(
    `Speech Core: ${status.status} | STT: ${status.stt_engine} | TTS: ${status.tts_engine} | GPU: ${status.gpu_available}`,
  );

  // ── 2. 创建管线 ──────────────────────────────────────────────────────
  const pipelineConfig: VoicePipelineConfig = {
    llm: config.llm,
    sttLanguage: config.sttLanguage,
    ttsProvider: config.ttsProvider,
    minAudioDurationMs: 300,
    minConfidence: 0.3,
    enableLatencyLogging: true,
  };

  const pipeline = new VoicePipeline(pipelineConfig, speechCore, logger);

  // 管线事件监听
  pipeline.on('processingStart', (userId: string) => {
    logger.info(`🎙️ Processing audio from user ${userId}...`);
  });

  pipeline.on('audioSkipped', (userId: string, reason: string) => {
    logger.debug(`⏭️ Audio skipped for ${userId}: ${reason}`);
  });

  pipeline.on('pipelineError', (userId: string, _channelId: string, error: Error, stage: string) => {
    logger.error(`❌ Pipeline error for ${userId} at ${stage}: ${error.message}`);
  });

  // ── 3. 登录 Discord ──────────────────────────────────────────────────
  logger.info('Logging in to Discord...');
  const client = new Client({
    intents: [
      GatewayIntentBits.Guilds,
      GatewayIntentBits.GuildVoiceStates,
    ],
  });

  await client.login(config.botToken);
  logger.info(`Discord bot logged in as ${client.user?.tag}`);

  // ── 4. 加入语音频道 ──────────────────────────────────────────────────
  const adapter = new DiscordVoiceAdapter({
    selfDeaf: false,
    selfMute: false,
    silenceDurationMs: 800, // 800ms 静默检测
  });

  const guild = await client.guilds.fetch(config.guildId);
  const channel = (await guild.channels.fetch(config.channelId)) as VoiceChannel;
  if (!channel || !channel.isVoiceBased()) {
    logger.error(`Channel ${config.channelId} is not a voice channel`);
    process.exit(1);
  }

  adapter.on('connected', (channelId: string) => {
    logger.info(`🔊 Connected to voice channel: ${channelId}`);
    logger.info('✅ Ready! Speak in the voice channel to test the pipeline.');
  });

  adapter.on('disconnected', (channelId: string, reason: string) => {
    logger.warn(`🔇 Disconnected from ${channelId}: ${reason}`);
  });

  // ── 5. 核心管线：接收音频 → 处理 → 播放 ────────────────────────────
  adapter.on(
    'userAudioReceived',
    async (userId: string, channelId: string, opusStream: Readable) => {
      try {
        const result = await pipeline.process(userId, channelId, opusStream);

        if (result) {
          // 创建 PCM → Opus 编码流
          const pcmReadable = new Readable({
            read() {
              this.push(result.pcmBuffer);
              this.push(null);
            },
          });

          const opusEncoder = new PCMToOpusStream({
            sourceSampleRate: result.sampleRate,
            targetSampleRate: 48000,
            channels: 1,
          });

          const opusOutput = pcmReadable.pipe(opusEncoder);

          // 播放到频道
          logger.info('🔈 Playing TTS response...');
          await adapter.play(channelId, opusOutput, StreamType.Opus);
          logger.info('🔈 Playback complete');
        }
      } catch (error) {
        logger.error(`Failed to process/play audio: ${error}`);
      }
    },
  );

  // 加入频道
  await adapter.join(channel, guild);

  // ── 6. 优雅退出 ────────────────────────────────────────────────────
  const shutdown = async () => {
    logger.info('\nShutting down...');
    adapter.leaveAll();
    speechCore.disconnect();
    client.destroy();
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  // 保持进程运行
  logger.info('Voice pipeline running. Press Ctrl+C to stop.');
}

main().catch((error) => {
  logger.error(`Fatal error: ${error}`);
  process.exit(1);
});
