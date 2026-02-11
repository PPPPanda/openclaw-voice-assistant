/**
 * Speech Core Gateway Plugin
 *
 * OpenClaw Gateway 插件入口。
 * 提供 speech.stt / speech.tts / speech.status / speech.models RPC 接口。
 */

import { SpeechCoreClient } from './client';
import {
  SpeechCoreConfig,
  DEFAULT_CONFIG,
  STTRequest,
  STTResult,
  TTSRequest,
  TTSResult,
  TTSStreamResult,
  SpeechCoreStatus,
  ModelList,
} from './types';

export { SpeechCoreClient } from './client';
export * from './types';

/**
 * Speech Core 插件
 *
 * 为 OpenClaw Gateway 提供语音处理能力。
 *
 * Usage:
 * ```typescript
 * const plugin = new SpeechCorePlugin({
 *   endpoint: 'ws://localhost:9001/speech'
 * });
 * await plugin.initialize();
 *
 * // STT
 * const result = await plugin.stt({ audio, options });
 *
 * // TTS
 * const audio = await plugin.tts({ text: '你好', options: {} });
 * ```
 */
export class SpeechCorePlugin {
  private client: SpeechCoreClient;
  private config: SpeechCoreConfig;
  private initialized = false;

  constructor(config?: Partial<SpeechCoreConfig>) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.client = new SpeechCoreClient(this.config);
  }

  /**
   * 初始化插件（连接到 Speech Core 服务）
   */
  async initialize(): Promise<void> {
    if (this.initialized) {
      return;
    }

    // 设置事件监听
    this.client.on('connected', () => {
      console.log('[SpeechCore] Connected to service');
    });

    this.client.on('disconnected', (code: number, reason: string) => {
      console.warn(`[SpeechCore] Disconnected: ${code} ${reason}`);
    });

    this.client.on('reconnecting', (attempt: number) => {
      console.log(`[SpeechCore] Reconnecting (attempt ${attempt})...`);
    });

    this.client.on('reconnect_failed', () => {
      console.error('[SpeechCore] Max reconnection attempts reached');
    });

    this.client.on('error', (error: Error) => {
      console.error('[SpeechCore] Error:', error.message);
    });

    this.client.on('health', (status: SpeechCoreStatus) => {
      if (status.status !== 'healthy') {
        console.warn(`[SpeechCore] Health: ${status.status}`);
      }
    });

    // 连接
    await this.client.connect();
    this.initialized = true;

    // 验证连接
    const status = await this.client.status();
    console.log(
      `[SpeechCore] Service ready: STT=${status.stt_engine}, ` +
      `TTS=${status.tts_engine}, GPU=${status.gpu_available}`
    );
  }

  /**
   * 语音转文字
   */
  async stt(params: STTRequest): Promise<STTResult> {
    this.ensureInitialized();
    return this.client.stt(params);
  }

  /**
   * 文字转语音
   */
  async tts(params: TTSRequest): Promise<TTSResult | TTSStreamResult> {
    this.ensureInitialized();
    return this.client.tts(params);
  }

  /**
   * 获取服务状态
   */
  async status(): Promise<SpeechCoreStatus> {
    this.ensureInitialized();
    return this.client.status();
  }

  /**
   * 获取可用模型
   */
  async models(): Promise<ModelList> {
    this.ensureInitialized();
    return this.client.models();
  }

  /**
   * 是否已连接
   */
  get isConnected(): boolean {
    return this.client.isConnected;
  }

  /**
   * 销毁插件
   */
  destroy(): void {
    this.client.disconnect();
    this.initialized = false;
  }

  private ensureInitialized(): void {
    if (!this.initialized) {
      throw new Error('SpeechCorePlugin not initialized. Call initialize() first.');
    }
  }
}
