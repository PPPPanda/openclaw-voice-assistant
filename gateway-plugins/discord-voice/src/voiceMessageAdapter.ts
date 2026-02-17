/**
 * VoiceMessage Adapter
 *
 * 监听 Discord 频道中的语音附件/语音留言消息，
 * 自动下载音频并转写为文本。
 */

import {
  Client,
  Message,
  Attachment,
  GatewayIntentBits,
} from 'discord.js';
import { pipeline } from 'stream/promises';
import { createWriteStream, createReadStream } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { randomUUID } from 'crypto';
import { existsSync, unlinkSync } from 'fs';

// ============================================================================
// 类型定义
// ============================================================================

export interface VoiceMessageAdapterConfig {
  /** Discord Bot Token */
  botToken: string;
  /** Speech Core HTTP 端点 */
  speechCoreEndpoint: string;
  /** 目标频道 ID 列表（空表示监听所有文本频道） */
  channelIds?: string[];
  /** 是否启用语音消息监听 */
  enabled?: boolean;
  /** OpenClaw Gateway 端点 (e.g. http://localhost:18790) */
  gatewayEndpoint?: string;
  /** OpenClaw Hooks 认证 Token */
  gatewayHooksToken?: string;
  /** 是否自动将转写文本发送给 OpenClaw 处理 (默认 true) */
  autoDispatch?: boolean;
}

export interface TranscriptionResult {
  messageId: string;
  channelId: string;
  userId: string;
  text: string;
  language: string;
  confidence: number;
  processingTimeMs: number;
}

interface Logger {
  info: (msg: string, ...args: unknown[]) => void;
  warn: (msg: string, ...args: unknown[]) => void;
  error: (msg: string, ...args: unknown[]) => void;
  debug: (msg: string, ...args: unknown[]) => void;
}

// ============================================================================
// Speech Core 客户端 (HTTP 版本)
// ============================================================================

class SpeechCoreClient {
  private endpoint: string;
  private logger: Logger;

  constructor(endpoint: string, logger: Logger) {
    this.endpoint = endpoint;
    this.logger = logger;
  }

  async stt(audioBase64: string): Promise<{
    text: string;
    language: string;
    confidence: number;
    processingTimeMs: number;
  }> {
    // 使用 HTTP API
    const response = await fetch(`${this.endpoint}/speech.stt`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: randomUUID(),
        method: 'speech.stt',
        params: {
          audio: {
            format: 'opus',
            sampleRate: 48000,
            channels: 1,
            data: audioBase64,
          },
          options: {
            language: 'auto',
            vadEnabled: false,
          },
        },
      }),
    });

    if (!response.ok) {
      throw new Error(`STT request failed: ${response.statusText}`);
    }

    const result = await response.json() as {
      result?: {
        text: string;
        language: string;
        confidence: number;
        processingTimeMs: number;
      };
      error?: { message: string };
    };

    if (result.error) {
      throw new Error(result.error.message);
    }

    return result.result!;
  }
}

// ============================================================================
// VoiceMessage Adapter
// ============================================================================

/**
 * 语音消息适配器
 *
 * 监听 Discord 文本频道中的语音附件消息，
 * 自动转写并回复文本。
 */
export class VoiceMessageAdapter {
  private client: Client;
  private config: VoiceMessageAdapterConfig;
  private speechCore: SpeechCoreClient;
  private logger: Logger;
  private initialized = false;

  /**
   * 转写完成回调
   * 当语音消息被转写后调用。
   */
  onTranscription: ((
    result: TranscriptionResult
  ) => Promise<void>) | null = null;

  /**
   * 错误回调
   */
  onError: ((error: Error) => void) | null = null;

  constructor(config: VoiceMessageAdapterConfig, logger: Logger) {
    this.config = config;
    this.logger = logger;
    this.speechCore = new SpeechCoreClient(config.speechCoreEndpoint, logger);

    this.client = new Client({
      intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
      ],
    });
  }

  /**
   * 初始化适配器
   */
  async initialize(): Promise<void> {
    if (this.initialized) return;
    if (!this.config.enabled) {
      this.logger.info('[VoiceMessage] Adapter disabled, skipping initialization');
      return;
    }

    this.logger.info('[VoiceMessage] Initializing VoiceMessage adapter...');

    // 登录 Discord
    await this.client.login(this.config.botToken);
    this.logger.info(`[VoiceMessage] Logged in as ${this.client.user?.tag}`);

    // 设置消息监听
    this.client.on('messageCreate', (message) => {
      this.handleMessage(message).catch((err) => {
        this.logger.error(`[VoiceMessage] Error handling message: ${err}`);
        if (this.onError) {
          this.onError(err);
        }
      });
    });

    this.initialized = true;
    this.logger.info('[VoiceMessage] VoiceMessage adapter initialized');
  }

  /**
   * 处理消息
   */
  private async handleMessage(message: Message): Promise<void> {
    // 忽略机器人消息
    if (message.author.bot) return;

    // 检查是否是目标频道
    if (this.config.channelIds && this.config.channelIds.length > 0) {
      if (!this.config.channelIds.includes(message.channelId)) {
        return;
      }
    }

    // 检查是否是语音消息附件
    const voiceAttachment = this.findVoiceAttachment(message);
    if (!voiceAttachment) return;

    this.logger.info(
      `[VoiceMessage] Found voice message from ${message.author.tag} in ${message.channelId}`
    );

    try {
      // 下载音频文件
      const audioPath = await this.downloadAudio(voiceAttachment, message.id);

      // 读取音频文件
      const audioBuffer = await this.readAudioFile(audioPath);
      const audioBase64 = audioBuffer.toString('base64');

      // 调用 STT
      const result = await this.speechCore.stt(audioBase64);

      this.logger.info(
        `[VoiceMessage] Transcription: "${result.text}" (${result.language}, conf=${result.confidence.toFixed(2)})`
      );

      // 构建转写结果
      const transcriptionResult: TranscriptionResult = {
        messageId: message.id,
        channelId: message.channelId,
        userId: message.author.id,
        text: result.text,
        language: result.language,
        confidence: result.confidence,
        processingTimeMs: result.processingTimeMs,
      };

      // 触发回调
      if (this.onTranscription) {
        await this.onTranscription(transcriptionResult);
      }

      // 自动派发到 OpenClaw Gateway
      if (this.config.autoDispatch !== false) {
        await this.dispatchToGateway(transcriptionResult, message);
      }

      // 清理临时文件
      this.cleanupTempFiles([audioPath]);
    } catch (error) {
      this.logger.error(`[VoiceMessage] Failed to process voice message: ${error}`);
      throw error;
    }
  }

  /**
   * 查找语音附件
   */
  private findVoiceAttachment(message: Message): Attachment | null {
    // 检查附件 - convert to array first
    const attachments = Array.from(message.attachments.values());
    for (const attachment of attachments) {
      // Discord 语音消息通常是 .ogg 或 .opus 格式
      const ext = attachment.name?.split('.').pop()?.toLowerCase();
      if (ext === 'ogg' || ext === 'opus' || attachment.contentType?.includes('audio')) {
        return attachment;
      }
    }
    return null;
  }

  /**
   * 下载音频文件
   */
  private async downloadAudio(attachment: Attachment, messageId: string): Promise<string> {
    const tempPath = join(tmpdir(), `voice_${messageId}_${randomUUID()}.ogg`);

    this.logger.debug(`[VoiceMessage] Downloading audio to ${tempPath}`);

    const response = await fetch(attachment.url);
    if (!response.ok) {
      throw new Error(`Failed to download audio: ${response.statusText}`);
    }

    const fileStream = createWriteStream(tempPath);
    await pipeline(response.body as any, fileStream);

    return tempPath;
  }

  /**
   * 读取音频文件
   */
  private async readAudioFile(filePath: string): Promise<Buffer> {
    return new Promise((resolve, reject) => {
      const chunks: Buffer[] = [];
      const stream = createReadStream(filePath);

      stream.on('data', (chunk: Buffer | string) => {
        chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
      });
      stream.on('end', () => resolve(Buffer.concat(chunks)));
      stream.on('error', reject);
    });
  }

  /**
   * 清理临时文件
   */
  private cleanupTempFiles(paths: string[]): void {
    for (const path of paths) {
      if (path && existsSync(path)) {
        try {
          unlinkSync(path);
        } catch (e) {
          this.logger.warn(`[VoiceMessage] Failed to cleanup temp file ${path}: ${e}`);
        }
      }
    }
  }

  // ==========================================================================
  // OpenClaw Gateway 对接 (P0-2)
  // ==========================================================================

  /**
   * 将转写文本派发到 OpenClaw Gateway
   *
   * 使用 /hooks/agent 端点：
   * - 创建一个隔离的 agent session 处理语音输入
   * - 自动将 LLM 回复投递回 Discord 频道
   */
  private async dispatchToGateway(
    transcription: TranscriptionResult,
    originalMessage: Message,
  ): Promise<void> {
    const endpoint = this.config.gatewayEndpoint;
    const token = this.config.gatewayHooksToken;

    if (!endpoint || !token) {
      this.logger.debug(
        '[VoiceMessage] Gateway dispatch skipped: gatewayEndpoint or gatewayHooksToken not configured',
      );
      return;
    }

    // 跳过空转写或低置信度结果
    if (!transcription.text.trim()) {
      this.logger.debug('[VoiceMessage] Gateway dispatch skipped: empty transcription');
      return;
    }

    if (transcription.confidence < 0.3) {
      this.logger.warn(
        `[VoiceMessage] Gateway dispatch skipped: low confidence ${transcription.confidence.toFixed(2)}`,
      );
      return;
    }

    const senderTag = originalMessage.author.tag ?? originalMessage.author.id;
    const hookPayload = {
      message: `[🎤 Voice from ${senderTag}] ${transcription.text}`,
      name: 'VoiceMessage',
      deliver: true,
      channel: 'discord',
      to: transcription.channelId,
      sessionKey: `hook:voice:${transcription.channelId}`,
    };

    this.logger.info(
      `[VoiceMessage] Dispatching to Gateway: "${transcription.text.slice(0, 60)}..."`,
    );

    try {
      const response = await fetch(`${endpoint}/hooks/agent`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(hookPayload),
      });

      if (!response.ok) {
        const body = await response.text().catch(() => '');
        throw new Error(`Gateway responded ${response.status}: ${body.slice(0, 200)}`);
      }

      this.logger.info(
        `[VoiceMessage] Gateway dispatch accepted (${response.status})`,
      );
    } catch (error) {
      this.logger.error(`[VoiceMessage] Gateway dispatch failed: ${error}`);
      // 不抛出 — dispatch 失败不应阻断转写流程
    }
  }

  /**
   * 销毁适配器
   */
  destroy(): void {
    this.client.destroy();
    this.initialized = false;
    this.logger.info('[VoiceMessage] VoiceMessage adapter destroyed');
  }

  /**
   * 获取状态
   */
  getStatus(): {
    initialized: boolean;
    botUser: string | null;
    targetChannels: string[];
  } {
    return {
      initialized: this.initialized,
      botUser: this.client.user?.tag ?? null,
      targetChannels: this.config.channelIds ?? [],
    };
  }
}

// ============================================================================
// 便捷函数
// ============================================================================

/**
 * 创建语音消息适配器
 */
export function createVoiceMessageAdapter(
  config: VoiceMessageAdapterConfig,
  logger: Logger
): VoiceMessageAdapter {
  return new VoiceMessageAdapter(config, logger);
}
