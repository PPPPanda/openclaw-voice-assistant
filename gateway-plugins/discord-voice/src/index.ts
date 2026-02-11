/**
 * Discord Voice Plugin
 *
 * OpenClaw Gateway 的 Discord 语音适配器插件入口。
 * 协调 DiscordVoiceAdapter + SpeechCorePlugin 实现语音对讲。
 *
 * 适配 OpenClaw Plugin API，支持：
 * - Gateway RPC 方法注册（voice.join, voice.leave, voice.speak, voice.status）
 * - Agent 工具注册（voice_channel_join, voice_channel_leave, voice_speak）
 * - CLI 命令注册（openclaw voice join/leave/status）
 * - 后台服务管理
 */

import { VoiceChannel, Guild, Client, GatewayIntentBits } from 'discord.js';
import { Readable } from 'stream';
import { DiscordVoiceAdapter } from './adapter';
import { createPCMStream, collectPCMBuffer } from './receiver';
import { createAudioResourceFromPCM } from './player';

export { DiscordVoiceAdapter } from './adapter';
export { OpusToPCMStream, createPCMStream, collectPCMBuffer } from './receiver';
export { PCMToOpusStream, createAudioResourceFromPCM, createAudioResourceFromOpus } from './player';

// ============================================================================
// 类型定义
// ============================================================================

export interface DiscordVoicePluginConfig {
  /** Discord Bot Token */
  botToken: string;
  /** Speech Core 服务地址 */
  speechCoreEndpoint: string;
  /** 目标语音频道 ID（可选，可通过命令加入） */
  defaultChannelId?: string;
  /** 目标 Guild ID */
  guildId: string;
  /** TTS 提供者 */
  ttsProvider?: 'piper' | 'elevenlabs' | 'openai';
  /** STT 语言 */
  sttLanguage?: string;
}

// Speech Core 插件的简化类型（避免循环依赖）
interface SpeechCorePluginLike {
  initialize(): Promise<void>;
  destroy(): void;
  stt(request: {
    audio: { format: string; sampleRate: number; channels: number; data: string };
    options: { language: string; vadEnabled?: boolean };
  }): Promise<{
    text: string;
    language: string;
    confidence: number;
    processingTimeMs: number;
  }>;
  tts(request: {
    text: string;
    options: { provider: string };
    stream: boolean;
  }): Promise<{
    audio: string;
    sampleRate: number;
  }>;
}

// OpenClaw Plugin API 类型
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
        'discord-voice'?: {
          enabled?: boolean;
          config?: Partial<DiscordVoicePluginConfig>;
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
  registerCli?: (
    builder: (ctx: { program: unknown }) => void,
    options: { commands: string[] }
  ) => void;
  // 获取其他插件的引用
  getPlugin?: (id: string) => unknown;
}

// ============================================================================
// DiscordVoicePlugin 类
// ============================================================================

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
 */
export class DiscordVoicePlugin {
  private adapter: DiscordVoiceAdapter;
  private speechCore: SpeechCorePluginLike | null = null;
  private client: Client;
  private config: DiscordVoicePluginConfig;
  private initialized = false;
  private logger: PluginAPI['logger'] | null = null;
  private activeChannels: Set<string> = new Set();

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

    this.client = new Client({
      intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildVoiceStates,
      ],
    });
  }

  /**
   * 设置 Speech Core 插件引用
   */
  setSpeechCore(speechCore: SpeechCorePluginLike): void {
    this.speechCore = speechCore;
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
      console[level === 'debug' ? 'log' : level](`[DiscordVoice] ${msg}`, ...args);
    }
  }

  /**
   * 初始化插件
   */
  async initialize(): Promise<void> {
    if (this.initialized) return;

    // 检查 Speech Core 是否已设置
    if (!this.speechCore) {
      throw new Error('Speech Core plugin not set. Call setSpeechCore() first.');
    }

    // 连接 Speech Core
    await this.speechCore.initialize();
    this.log('info', 'Speech Core connected');

    // 登录 Discord
    await this.client.login(this.config.botToken);
    this.log('info', `Discord bot logged in as ${this.client.user?.tag}`);

    // 设置音频接收回调
    this.adapter.on(
      'userAudioReceived',
      (userId: string, channelId: string, opusStream: Readable) => {
        this.handleUserAudio(userId, channelId, opusStream).catch((err) => {
          this.log('error', `Error handling user audio: ${err}`);
        });
      },
    );

    this.adapter.on('connected', (channelId: string) => {
      this.activeChannels.add(channelId);
      this.log('info', `Connected to voice channel: ${channelId}`);
    });

    this.adapter.on('disconnected', (channelId: string, reason: string) => {
      this.activeChannels.delete(channelId);
      this.log('info', `Disconnected from ${channelId}: ${reason}`);
    });

    this.initialized = true;
    this.log('info', 'Discord Voice plugin initialized');

    // 如果配置了默认频道，自动加入
    if (this.config.defaultChannelId) {
      try {
        await this.joinChannel(this.config.defaultChannelId);
      } catch (error) {
        this.log('warn', `Failed to join default channel: ${error}`);
      }
    }
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
    this.activeChannels.delete(channelId);
  }

  /**
   * 离开所有语音频道
   */
  leaveAllChannels(): void {
    this.adapter.leaveAll();
    this.activeChannels.clear();
  }

  /**
   * 获取当前状态
   */
  getStatus(): {
    initialized: boolean;
    botUser: string | null;
    activeChannels: string[];
    speechCoreConnected: boolean;
  } {
    return {
      initialized: this.initialized,
      botUser: this.client.user?.tag ?? null,
      activeChannels: Array.from(this.activeChannels),
      speechCoreConnected: this.speechCore !== null,
    };
  }

  /**
   * 通过 TTS 在语音频道中说话
   */
  async speak(channelId: string, text: string): Promise<void> {
    if (!text.trim()) return;
    if (!this.speechCore) {
      throw new Error('Speech Core not initialized');
    }

    this.log('debug', `Speaking in ${channelId}: "${text.slice(0, 50)}..."`);

    // 调用 TTS
    const ttsResult = await this.speechCore.tts({
      text,
      options: { provider: this.config.ttsProvider ?? 'piper' },
      stream: false,
    });

    // 解码 Base64 音频
    const pcmBuffer = Buffer.from(ttsResult.audio, 'base64');

    // 创建 AudioResource 并播放
    createAudioResourceFromPCM(pcmBuffer, ttsResult.sampleRate);
    // 通过 adapter 播放
    const audioStream = new Readable({
      read() {
        this.push(pcmBuffer);
        this.push(null);
      },
    });

    await this.adapter.play(channelId, audioStream);
    this.log('debug', `Playback complete in ${channelId}`);
  }

  /**
   * 处理用户音频
   */
  private async handleUserAudio(
    userId: string,
    channelId: string,
    opusStream: Readable,
  ): Promise<void> {
    if (!this.speechCore) return;

    this.log('debug', `Receiving audio from user ${userId}`);

    // Opus → PCM 16kHz
    const pcmStream = createPCMStream(opusStream, { targetSampleRate: 16000 });
    const pcmBuffer = await collectPCMBuffer(pcmStream);

    if (pcmBuffer.length === 0) {
      this.log('debug', 'Empty audio received, ignoring');
      return;
    }

    this.log(
      'debug',
      `Audio collected: ${pcmBuffer.length} bytes (~${((pcmBuffer.length / 2 / 16000) * 1000).toFixed(0)}ms)`,
    );

    try {
      const result = await this.speechCore.stt({
        audio: {
          format: 'pcm_s16le',
          sampleRate: 16000,
          channels: 1,
          data: pcmBuffer.toString('base64'),
        },
        options: {
          language: this.config.sttLanguage ?? 'auto',
          vadEnabled: false, // VAD 已在 Discord 端处理
        },
      });

      this.log(
        'info',
        `STT result: "${result.text}" (lang=${result.language}, conf=${result.confidence.toFixed(2)}, time=${result.processingTimeMs}ms)`,
      );

      if (result.text.trim() && this.onTranscription) {
        await this.onTranscription(result.text, userId, channelId);
      }
    } catch (error) {
      this.log('error', `STT error: ${error}`);
    }
  }

  /**
   * 销毁插件
   */
  destroy(): void {
    this.adapter.leaveAll();
    if (this.speechCore) {
      this.speechCore.destroy();
    }
    this.client.destroy();
    this.initialized = false;
    this.activeChannels.clear();
    this.log('info', 'Discord Voice plugin destroyed');
  }
}

// ============================================================================
// 全局插件实例
// ============================================================================

let globalPlugin: DiscordVoicePlugin | null = null;

/**
 * 获取全局 Discord Voice 插件实例
 */
export function getDiscordVoicePlugin(): DiscordVoicePlugin | null {
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
  const pluginConfig = api.config.plugins?.entries?.['discord-voice']?.config;
  
  if (!pluginConfig?.botToken || !pluginConfig?.guildId) {
    api.logger.warn('Discord Voice plugin requires botToken and guildId in config. Plugin will not start.');
    return;
  }

  // 创建插件实例
  globalPlugin = new DiscordVoicePlugin({
    botToken: pluginConfig.botToken,
    guildId: pluginConfig.guildId,
    speechCoreEndpoint: pluginConfig.speechCoreEndpoint ?? 'ws://localhost:9001/speech',
    defaultChannelId: pluginConfig.defaultChannelId,
    ttsProvider: pluginConfig.ttsProvider,
    sttLanguage: pluginConfig.sttLanguage,
  });
  globalPlugin.setLogger(api.logger);

  api.logger.info('Discord Voice plugin registering...');

  // -------------------------------------------------------------------------
  // 注册 Gateway RPC 方法
  // -------------------------------------------------------------------------

  api.registerGatewayMethod('voice.join', async ({ params, respond }) => {
    try {
      if (!globalPlugin) {
        respond(false, { error: 'Discord Voice plugin not initialized' });
        return;
      }
      const { channelId } = params as { channelId: string };
      await globalPlugin.joinChannel(channelId);
      respond(true, { success: true, channelId });
    } catch (error) {
      respond(false, { error: (error as Error).message });
    }
  });

  api.registerGatewayMethod('voice.leave', async ({ params, respond }) => {
    try {
      if (!globalPlugin) {
        respond(false, { error: 'Discord Voice plugin not initialized' });
        return;
      }
      const { channelId } = params as { channelId?: string };
      if (channelId) {
        globalPlugin.leaveChannel(channelId);
      } else {
        globalPlugin.leaveAllChannels();
      }
      respond(true, { success: true });
    } catch (error) {
      respond(false, { error: (error as Error).message });
    }
  });

  api.registerGatewayMethod('voice.speak', async ({ params, respond }) => {
    try {
      if (!globalPlugin) {
        respond(false, { error: 'Discord Voice plugin not initialized' });
        return;
      }
      const { channelId, text } = params as { channelId: string; text: string };
      await globalPlugin.speak(channelId, text);
      respond(true, { success: true });
    } catch (error) {
      respond(false, { error: (error as Error).message });
    }
  });

  api.registerGatewayMethod('voice.status', async ({ respond }) => {
    try {
      if (!globalPlugin) {
        respond(false, { error: 'Discord Voice plugin not initialized' });
        return;
      }
      const status = globalPlugin.getStatus();
      respond(true, status);
    } catch (error) {
      respond(false, { error: (error as Error).message });
    }
  });

  // -------------------------------------------------------------------------
  // 注册 Agent 工具
  // -------------------------------------------------------------------------

  api.registerTool({
    name: 'voice_channel_join',
    description: 'Join a Discord voice channel to enable voice conversations',
    parameters: {
      type: 'object',
      properties: {
        channel_id: {
          type: 'string',
          description: 'Discord voice channel ID to join',
        },
      },
      required: ['channel_id'],
    },
    handler: async (params) => {
      if (!globalPlugin) {
        throw new Error('Discord Voice plugin not initialized');
      }
      await globalPlugin.joinChannel(params.channel_id as string);
      return { success: true, channelId: params.channel_id };
    },
  });

  api.registerTool({
    name: 'voice_channel_leave',
    description: 'Leave a Discord voice channel',
    parameters: {
      type: 'object',
      properties: {
        channel_id: {
          type: 'string',
          description: 'Discord voice channel ID to leave (optional, leaves all if not specified)',
        },
      },
    },
    handler: async (params) => {
      if (!globalPlugin) {
        throw new Error('Discord Voice plugin not initialized');
      }
      if (params.channel_id) {
        globalPlugin.leaveChannel(params.channel_id as string);
      } else {
        globalPlugin.leaveAllChannels();
      }
      return { success: true };
    },
  });

  api.registerTool({
    name: 'voice_speak',
    description: 'Speak text in a Discord voice channel using TTS',
    parameters: {
      type: 'object',
      properties: {
        channel_id: {
          type: 'string',
          description: 'Discord voice channel ID',
        },
        text: {
          type: 'string',
          description: 'Text to speak',
        },
      },
      required: ['channel_id', 'text'],
    },
    handler: async (params) => {
      if (!globalPlugin) {
        throw new Error('Discord Voice plugin not initialized');
      }
      await globalPlugin.speak(params.channel_id as string, params.text as string);
      return { success: true };
    },
  });

  api.registerTool({
    name: 'voice_status',
    description: 'Get Discord voice plugin status',
    parameters: {
      type: 'object',
      properties: {},
    },
    handler: async () => {
      if (!globalPlugin) {
        throw new Error('Discord Voice plugin not initialized');
      }
      return globalPlugin.getStatus();
    },
  });

  // -------------------------------------------------------------------------
  // 注册后台服务
  // -------------------------------------------------------------------------

  api.registerService({
    id: 'discord-voice-service',
    start: async () => {
      if (!globalPlugin) return;

      // 动态创建 Speech Core 客户端
      // 使用简化的 WebSocket 客户端直接连接 Speech Core 服务
      const speechCoreEndpoint = pluginConfig.speechCoreEndpoint ?? 'ws://localhost:9001/speech';
      
      // 创建一个简化的 Speech Core 客户端
      const speechCore = createSpeechCoreClient(speechCoreEndpoint, api.logger);
      globalPlugin.setSpeechCore(speechCore);

      // 设置转写回调（这里需要与 OpenClaw 的消息处理集成）
      globalPlugin.onTranscription = async (text, userId, channelId) => {
        api.logger.info(`[Voice] User ${userId} in ${channelId}: "${text}"`);
        // TODO: 将文本发送给 OpenClaw 的消息处理系统
        // 这部分需要与 OpenClaw Gateway 的消息路由集成
      };

      await globalPlugin.initialize();
      api.logger.info('Discord Voice service started');
    },
    stop: () => {
      if (globalPlugin) {
        globalPlugin.destroy();
        api.logger.info('Discord Voice service stopped');
      }
    },
  });

  // -------------------------------------------------------------------------
  // 注册 CLI 命令（可选）
  // -------------------------------------------------------------------------

  if (api.registerCli) {
    api.registerCli(
      ({ program }) => {
        const p = program as {
          command: (name: string) => {
            description: (desc: string) => {
              argument: (arg: string, desc: string) => {
                action: (fn: (arg: string) => void) => void;
              };
              action: (fn: () => void) => void;
            };
          };
        };

        p.command('voice')
          .description('Discord voice channel commands')
          .action(() => {
            console.log('Usage: openclaw voice <join|leave|status>');
          });

        p.command('voice join')
          .description('Join a Discord voice channel')
          .argument('<channelId>', 'Voice channel ID')
          .action(async (channelId: string) => {
            if (!globalPlugin) {
              console.error('Discord Voice plugin not initialized');
              return;
            }
            await globalPlugin.joinChannel(channelId);
            console.log(`Joined voice channel: ${channelId}`);
          });

        p.command('voice leave')
          .description('Leave current voice channel(s)')
          .action(() => {
            if (!globalPlugin) {
              console.error('Discord Voice plugin not initialized');
              return;
            }
            globalPlugin.leaveAllChannels();
            console.log('Left all voice channels');
          });

        p.command('voice status')
          .description('Show Discord voice plugin status')
          .action(() => {
            if (!globalPlugin) {
              console.error('Discord Voice plugin not initialized');
              return;
            }
            const status = globalPlugin.getStatus();
            console.log('Discord Voice Status:');
            console.log(`  Initialized: ${status.initialized}`);
            console.log(`  Bot User: ${status.botUser ?? 'N/A'}`);
            console.log(`  Active Channels: ${status.activeChannels.join(', ') || 'None'}`);
            console.log(`  Speech Core: ${status.speechCoreConnected ? 'Connected' : 'Not Connected'}`);
          });
      },
      { commands: ['voice'] }
    );
  }

  api.logger.info('Discord Voice plugin registered successfully');
}

// ============================================================================
// 简化的 Speech Core 客户端（避免循环依赖）
// ============================================================================

import WebSocket from 'ws';
import { v4 as uuidv4 } from 'uuid';

interface JsonRpcRequest {
  jsonrpc: '2.0';
  id: string;
  method: string;
  params: unknown;
}

interface JsonRpcResponse {
  jsonrpc: '2.0';
  id: string;
  result?: unknown;
  error?: { code: number; message: string };
}

function createSpeechCoreClient(
  endpoint: string,
  logger: PluginAPI['logger']
): SpeechCorePluginLike {
  let ws: WebSocket | null = null;
  let isConnected = false;
  const pendingRequests = new Map<string, {
    resolve: (value: unknown) => void;
    reject: (reason: unknown) => void;
  }>();

  const connect = (): Promise<void> => {
    return new Promise((resolve, reject) => {
      ws = new WebSocket(endpoint);

      ws.on('open', () => {
        isConnected = true;
        logger.info(`Connected to Speech Core at ${endpoint}`);
        resolve();
      });

      ws.on('message', (data) => {
        try {
          const response = JSON.parse(data.toString()) as JsonRpcResponse;
          const pending = pendingRequests.get(response.id);
          if (pending) {
            pendingRequests.delete(response.id);
            if (response.error) {
              pending.reject(new Error(response.error.message));
            } else {
              pending.resolve(response.result);
            }
          }
        } catch (e) {
          logger.error(`Failed to parse Speech Core response: ${e}`);
        }
      });

      ws.on('close', () => {
        isConnected = false;
        logger.warn('Disconnected from Speech Core');
      });

      ws.on('error', (err) => {
        logger.error(`Speech Core WebSocket error: ${err.message}`);
        reject(err);
      });
    });
  };

  const call = <T>(method: string, params: unknown): Promise<T> => {
    return new Promise((resolve, reject) => {
      if (!ws || !isConnected) {
        reject(new Error('Not connected to Speech Core'));
        return;
      }

      const id = uuidv4();
      const request: JsonRpcRequest = {
        jsonrpc: '2.0',
        id,
        method,
        params,
      };

      pendingRequests.set(id, {
        resolve: resolve as (value: unknown) => void,
        reject,
      });

      ws.send(JSON.stringify(request));
    });
  };

  return {
    initialize: connect,
    destroy: () => {
      if (ws) {
        ws.close();
        ws = null;
      }
      isConnected = false;
      pendingRequests.clear();
    },
    stt: (request) => call('speech.stt', request),
    tts: (request) => call('speech.tts', request),
  };
}

// 导出插件元数据
export const id = 'discord-voice';
export const name = 'Discord Voice';
export const version = '0.1.0';
