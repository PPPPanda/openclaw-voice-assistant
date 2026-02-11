/**
 * Discord Voice Plugin
 *
 * OpenClaw Gateway 的 Discord 语音适配器插件入口。
 * 协调 DiscordVoiceAdapter + SpeechCorePlugin 实现语音对讲。
 */

import { VoiceChannel, Guild, Client, GatewayIntentBits } from 'discord.js';
import { Readable } from 'stream';
import { DiscordVoiceAdapter } from './adapter';
import { createPCMStream, collectPCMBuffer } from './receiver';
import { createAudioResourceFromPCM } from './player';
import { SpeechCorePlugin, STTRequest, TTSRequest, TTSResult } from '@openclaw/speech-core-plugin';

export { DiscordVoiceAdapter } from './adapter';
export { OpusToPCMStream, createPCMStream, collectPCMBuffer } from './receiver';
export { PCMToOpusStream, createAudioResourceFromPCM, createAudioResourceFromOpus } from './player';

export interface DiscordVoicePluginConfig {
  /** Discord Bot Token */
  botToken: string;
  /** Speech Core 服务地址 */
  speechCoreEndpoint: string;
  /** 目标语音频道 ID（可选，可通过命令加入） */
  defaultChannelId?: string;
  /** 目标 Guild ID */
  guildId: string;
}

/**
 * Discord Voice Plugin
 *
 * 完整的 Discord 语音对讲插件，集成：
 * - Discord 语音频道管理
 * - 音频接收 → Opus 解码 → PCM
 * - PCM → Speech Core STT
 * - LLM 回复 → Speech Core TTS → Opus 编码 → Discord 播放
 *
 * 当前为半双工模式（Phase 1）。
 *
 * Usage:
 * ```typescript
 * const plugin = new DiscordVoicePlugin({
 *   botToken: process.env.DISCORD_BOT_TOKEN!,
 *   speechCoreEndpoint: 'ws://localhost:9001/speech',
 *   guildId: '...',
 * });
 *
 * plugin.onTranscription = async (text, userId, channelId) => {
 *   // 将文本发送给 LLM
 *   const reply = await llm.chat(text);
 *   // 通过语音回复
 *   await plugin.speak(channelId, reply);
 * };
 *
 * await plugin.initialize();
 * await plugin.joinChannel(channelId);
 * ```
 */
export class DiscordVoicePlugin {
  private adapter: DiscordVoiceAdapter;
  private speechCore: SpeechCorePlugin;
  private client: Client;
  private config: DiscordVoicePluginConfig;
  private initialized = false;

  /**
   * 转写完成回调
   * 当用户说话被转写后调用，外部负责将文本发送给 LLM。
   */
  onTranscription:
    | ((text: string, userId: string, channelId: string) => Promise<void>)
    | null = null;

  constructor(config: DiscordVoicePluginConfig) {
    this.config = config;
    this.adapter = new DiscordVoiceAdapter();
    this.speechCore = new SpeechCorePlugin({
      endpoint: config.speechCoreEndpoint,
    });

    this.client = new Client({
      intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildVoiceStates,
      ],
    });
  }

  /**
   * 初始化插件
   */
  async initialize(): Promise<void> {
    if (this.initialized) return;

    // 连接 Speech Core
    await this.speechCore.initialize();
    console.log('[DiscordVoice] Speech Core connected');

    // 登录 Discord
    await this.client.login(this.config.botToken);
    console.log(`[DiscordVoice] Discord bot logged in as ${this.client.user?.tag}`);

    // 设置音频接收回调
    this.adapter.on(
      'userAudioReceived',
      (userId: string, channelId: string, opusStream: Readable) => {
        this.handleUserAudio(userId, channelId, opusStream).catch((err) => {
          console.error('[DiscordVoice] Error handling user audio:', err);
        });
      },
    );

    this.adapter.on('connected', (channelId: string) => {
      console.log(`[DiscordVoice] Connected to voice channel: ${channelId}`);
    });

    this.adapter.on('disconnected', (channelId: string, reason: string) => {
      console.log(`[DiscordVoice] Disconnected from ${channelId}: ${reason}`);
    });

    this.initialized = true;
    console.log('[DiscordVoice] Plugin initialized');
  }

  /**
   * 加入语音频道
   */
  async joinChannel(channelId: string): Promise<void> {
    const guild = await this.client.guilds.fetch(this.config.guildId);
    const channel = (await guild.channels.fetch(channelId)) as VoiceChannel;
    if (!channel || !channel.isVoiceBased()) {
      throw new Error(`Channel ${channelId} is not a voice channel`);
    }

    await this.adapter.join(channel, guild);
  }

  /**
   * 离开语音频道
   */
  leaveChannel(channelId: string): void {
    this.adapter.leave(channelId);
  }

  /**
   * 通过 TTS 在语音频道中说话
   */
  async speak(channelId: string, text: string): Promise<void> {
    if (!text.trim()) return;

    console.log(`[DiscordVoice] Speaking in ${channelId}: "${text.slice(0, 50)}..."`);

    // 调用 TTS
    const ttsRequest: TTSRequest = {
      text,
      options: { provider: 'piper' },
      stream: false,
    };

    const ttsResult = (await this.speechCore.tts(ttsRequest)) as TTSResult;

    // 解码 Base64 音频
    const pcmBuffer = Buffer.from(ttsResult.audio, 'base64');

    // 创建 AudioResource 并播放
    const resource = createAudioResourceFromPCM(pcmBuffer, ttsResult.sampleRate);
    // 通过 adapter 播放
    const audioStream = new Readable({
      read() {
        this.push(pcmBuffer);
        this.push(null);
      },
    });

    await this.adapter.play(channelId, audioStream);
    console.log(`[DiscordVoice] Playback complete in ${channelId}`);
  }

  /**
   * 处理用户音频
   */
  private async handleUserAudio(
    userId: string,
    channelId: string,
    opusStream: Readable,
  ): Promise<void> {
    console.log(`[DiscordVoice] Receiving audio from user ${userId}`);

    // Opus → PCM 16kHz
    const pcmStream = createPCMStream(opusStream, { targetSampleRate: 16000 });
    const pcmBuffer = await collectPCMBuffer(pcmStream);

    if (pcmBuffer.length === 0) {
      console.log('[DiscordVoice] Empty audio received, ignoring');
      return;
    }

    console.log(
      `[DiscordVoice] Audio collected: ${pcmBuffer.length} bytes ` +
      `(~${((pcmBuffer.length / 2 / 16000) * 1000).toFixed(0)}ms)`,
    );

    // 发送到 Speech Core 进行 STT
    const sttRequest: STTRequest = {
      audio: {
        format: 'pcm_s16le',
        sampleRate: 16000,
        channels: 1,
        data: pcmBuffer.toString('base64'),
      },
      options: {
        language: 'auto',
        vadEnabled: false, // VAD 已在 Discord 端处理
      },
    };

    try {
      const result = await this.speechCore.stt(sttRequest);
      console.log(
        `[DiscordVoice] STT result: "${result.text}" ` +
        `(lang=${result.language}, conf=${result.confidence.toFixed(2)}, ` +
        `time=${result.processingTimeMs}ms)`,
      );

      if (result.text.trim() && this.onTranscription) {
        await this.onTranscription(result.text, userId, channelId);
      }
    } catch (error) {
      console.error('[DiscordVoice] STT error:', error);
    }
  }

  /**
   * 销毁插件
   */
  destroy(): void {
    this.adapter.leaveAll();
    this.speechCore.destroy();
    this.client.destroy();
    this.initialized = false;
    console.log('[DiscordVoice] Plugin destroyed');
  }
}
