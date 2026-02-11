/**
 * Speech Core Gateway Plugin
 *
 * OpenClaw Gateway 插件入口。
 * 提供 speech.stt / speech.tts / speech.status / speech.models RPC 接口。
 *
 * 适配 OpenClaw Plugin API，支持：
 * - Gateway RPC 方法注册
 * - Agent 工具注册
 * - 后台服务管理
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

// ============================================================================
// OpenClaw Plugin API 类型（简化版，实际从 openclaw 包导入）
// ============================================================================

interface PluginAPI {
  logger: {
    info: (msg: string, ...args: unknown[]) => void;
    warn: (msg: string, ...args: unknown[]) => void;
    error: (msg: string, ...args: unknown[]) => void;
    debug: (msg: string, ...args: unknown[]) => void;
  };
  config: {
    plugins?: {
      entries?: {
        'speech-core'?: {
          enabled?: boolean;
          config?: Partial<SpeechCoreConfig>;
        };
      };
    };
  };
  registerGatewayMethod: (
    name: string,
    handler: (ctx: {
      params: unknown;
      respond: (success: boolean, result: unknown) => void;
    }) => void | Promise<void>
  ) => void;
  registerTool: (tool: {
    name: string;
    description: string;
    parameters: {
      type: string;
      properties: Record<string, unknown>;
      required?: string[];
    };
    handler: (params: Record<string, unknown>) => Promise<unknown>;
  }) => void;
  registerService: (service: {
    id: string;
    start: () => void | Promise<void>;
    stop: () => void | Promise<void>;
  }) => void;
}

// ============================================================================
// SpeechCorePlugin 类（保持原有功能）
// ============================================================================

/**
 * Speech Core 插件
 *
 * 为 OpenClaw Gateway 提供语音处理能力。
 */
export class SpeechCorePlugin {
  private client: SpeechCoreClient;
  private config: SpeechCoreConfig;
  private initialized = false;
  private logger: PluginAPI['logger'] | null = null;

  constructor(config?: Partial<SpeechCoreConfig>) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.client = new SpeechCoreClient(this.config);
  }

  /**
   * 设置 logger（由 OpenClaw Plugin API 提供）
   */
  setLogger(logger: PluginAPI['logger']): void {
    this.logger = logger;
  }

  private log(level: 'info' | 'warn' | 'error' | 'debug', msg: string, ...args: unknown[]): void {
    if (this.logger) {
      this.logger[level](msg, ...args);
    } else {
      console[level === 'debug' ? 'log' : level](`[SpeechCore] ${msg}`, ...args);
    }
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
      this.log('info', 'Connected to Speech Core service');
    });

    this.client.on('disconnected', (code: number, reason: string) => {
      this.log('warn', `Disconnected from Speech Core: ${code} ${reason}`);
    });

    this.client.on('reconnecting', (attempt: number) => {
      this.log('info', `Reconnecting to Speech Core (attempt ${attempt})...`);
    });

    this.client.on('reconnect_failed', () => {
      this.log('error', 'Max reconnection attempts reached for Speech Core');
    });

    this.client.on('error', (error: Error) => {
      this.log('error', `Speech Core error: ${error.message}`);
    });

    this.client.on('health', (status: SpeechCoreStatus) => {
      if (status.status !== 'healthy') {
        this.log('warn', `Speech Core health: ${status.status}`);
      }
    });

    // 连接
    await this.client.connect();
    this.initialized = true;

    // 验证连接
    const status = await this.client.status();
    this.log(
      'info',
      `Speech Core ready: STT=${status.stt_engine}, TTS=${status.tts_engine}, GPU=${status.gpu_available}`
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

// ============================================================================
// 全局插件实例（供 Gateway RPC 使用）
// ============================================================================

let globalPlugin: SpeechCorePlugin | null = null;

/**
 * 获取全局 Speech Core 插件实例
 */
export function getSpeechCorePlugin(): SpeechCorePlugin | null {
  return globalPlugin;
}

// ============================================================================
// OpenClaw Plugin 注册入口
// ============================================================================

/**
 * OpenClaw Plugin 注册函数
 *
 * 当 OpenClaw Gateway 加载此插件时调用。
 */
export default function register(api: PluginAPI): void {
  // 获取插件配置
  const pluginConfig = api.config.plugins?.entries?.['speech-core']?.config ?? {};
  
  // 创建插件实例
  globalPlugin = new SpeechCorePlugin(pluginConfig);
  globalPlugin.setLogger(api.logger);

  api.logger.info('Speech Core plugin registering...');

  // -------------------------------------------------------------------------
  // 注册 Gateway RPC 方法
  // -------------------------------------------------------------------------

  api.registerGatewayMethod('speech.stt', async ({ params, respond }) => {
    try {
      if (!globalPlugin) {
        respond(false, { error: 'Speech Core plugin not initialized' });
        return;
      }
      const result = await globalPlugin.stt(params as STTRequest);
      respond(true, result);
    } catch (error) {
      respond(false, { error: (error as Error).message });
    }
  });

  api.registerGatewayMethod('speech.tts', async ({ params, respond }) => {
    try {
      if (!globalPlugin) {
        respond(false, { error: 'Speech Core plugin not initialized' });
        return;
      }
      const result = await globalPlugin.tts(params as TTSRequest);
      respond(true, result);
    } catch (error) {
      respond(false, { error: (error as Error).message });
    }
  });

  api.registerGatewayMethod('speech.status', async ({ respond }) => {
    try {
      if (!globalPlugin) {
        respond(false, { error: 'Speech Core plugin not initialized' });
        return;
      }
      const result = await globalPlugin.status();
      respond(true, result);
    } catch (error) {
      respond(false, { error: (error as Error).message });
    }
  });

  api.registerGatewayMethod('speech.models', async ({ respond }) => {
    try {
      if (!globalPlugin) {
        respond(false, { error: 'Speech Core plugin not initialized' });
        return;
      }
      const result = await globalPlugin.models();
      respond(true, result);
    } catch (error) {
      respond(false, { error: (error as Error).message });
    }
  });

  // -------------------------------------------------------------------------
  // 注册 Agent 工具
  // -------------------------------------------------------------------------

  api.registerTool({
    name: 'speech_to_text',
    description: 'Convert audio to text using Speech Core STT service. Supports PCM, WAV, and Opus formats.',
    parameters: {
      type: 'object',
      properties: {
        audio_base64: {
          type: 'string',
          description: 'Base64 encoded audio data',
        },
        format: {
          type: 'string',
          enum: ['pcm_s16le', 'wav', 'opus'],
          description: 'Audio format (default: pcm_s16le)',
        },
        sample_rate: {
          type: 'number',
          description: 'Audio sample rate in Hz (default: 16000)',
        },
        language: {
          type: 'string',
          description: 'Language code (auto, zh, en, etc.) (default: auto)',
        },
      },
      required: ['audio_base64'],
    },
    handler: async (params) => {
      if (!globalPlugin) {
        throw new Error('Speech Core plugin not initialized');
      }
      const formatStr = (params.format as string) || 'pcm_s16le';
      const format = (['pcm_s16le', 'opus', 'mp3'].includes(formatStr) 
        ? formatStr 
        : 'pcm_s16le') as 'pcm_s16le' | 'opus' | 'mp3';
      
      const request: STTRequest = {
        audio: {
          format,
          sampleRate: (params.sample_rate as number) || 16000,
          channels: 1,
          data: params.audio_base64 as string,
        },
        options: {
          language: (params.language as string) || 'auto',
        },
      };
      return globalPlugin.stt(request);
    },
  });

  api.registerTool({
    name: 'text_to_speech',
    description: 'Convert text to speech using Speech Core TTS service. Returns base64 encoded audio.',
    parameters: {
      type: 'object',
      properties: {
        text: {
          type: 'string',
          description: 'Text to convert to speech',
        },
        voice: {
          type: 'string',
          description: 'Voice ID (default: zh_CN-huayan-medium for Piper)',
        },
        provider: {
          type: 'string',
          enum: ['piper', 'elevenlabs', 'openai'],
          description: 'TTS provider (default: piper)',
        },
        speed: {
          type: 'number',
          description: 'Speech speed multiplier (default: 1.0)',
        },
      },
      required: ['text'],
    },
    handler: async (params) => {
      if (!globalPlugin) {
        throw new Error('Speech Core plugin not initialized');
      }
      const providerStr = (params.provider as string) || 'piper';
      const provider = (['piper', 'elevenlabs', 'openai'].includes(providerStr)
        ? providerStr
        : 'piper') as 'piper' | 'elevenlabs' | 'openai';
      
      const request: TTSRequest = {
        text: params.text as string,
        options: {
          voice: params.voice as string,
          provider,
          speed: (params.speed as number) || 1.0,
        },
        stream: false,
      };
      return globalPlugin.tts(request);
    },
  });

  // -------------------------------------------------------------------------
  // 注册后台服务
  // -------------------------------------------------------------------------

  api.registerService({
    id: 'speech-core-service',
    start: async () => {
      if (globalPlugin) {
        await globalPlugin.initialize();
        api.logger.info('Speech Core service started');
      }
    },
    stop: () => {
      if (globalPlugin) {
        globalPlugin.destroy();
        api.logger.info('Speech Core service stopped');
      }
    },
  });

  api.logger.info('Speech Core plugin registered successfully');
}

// 导出插件元数据（供 OpenClaw 识别）
export const id = 'speech-core';
export const name = 'Speech Core';
export const version = '0.1.0';
