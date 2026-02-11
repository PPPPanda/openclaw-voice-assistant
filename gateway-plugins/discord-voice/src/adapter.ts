/**
 * Discord Voice Adapter
 *
 * 管理 Discord 语音频道连接：加入、离开、接收和播放音频。
 * 使用 @discordjs/voice 实现实时语音通信。
 */

import {
  joinVoiceChannel,
  VoiceConnection,
  VoiceConnectionStatus,
  entersState,
  getVoiceConnection,
  createAudioPlayer,
  AudioPlayer,
  AudioPlayerStatus,
  createAudioResource,
  StreamType,
  VoiceReceiver,
  EndBehaviorType,
} from '@discordjs/voice';
import { VoiceChannel, Guild, Snowflake } from 'discord.js';
import { EventEmitter } from 'events';
import { Readable } from 'stream';

export interface VoiceAdapterConfig {
  /** 是否自动取消静音（接收音频需要） */
  selfDeaf: boolean;
  /** Bot 是否静音（播放音频时需要关闭） */
  selfMute: boolean;
  /** 用户停止说话后的静音检测时长（毫秒） */
  silenceDurationMs: number;
}

const DEFAULT_VOICE_CONFIG: VoiceAdapterConfig = {
  selfDeaf: false,  // 必须为 false 才能接收音频
  selfMute: false,
  silenceDurationMs: 600,
};

export interface VoiceAdapterEvents {
  /** 用户开始说话 */
  userSpeakingStart: (userId: string, channelId: string) => void;
  /** 用户停止说话，返回 Opus 音频流 */
  userAudioReceived: (userId: string, channelId: string, audioStream: Readable) => void;
  /** 连接建立 */
  connected: (channelId: string) => void;
  /** 连接断开 */
  disconnected: (channelId: string, reason: string) => void;
  /** 播放完成 */
  playbackFinished: (channelId: string) => void;
  /** 错误 */
  error: (error: Error) => void;
}

/**
 * Discord 语音频道适配器
 *
 * 负责：
 * - 加入/离开语音频道
 * - 接收用户音频（Opus 编码）
 * - 播放音频到频道
 *
 * Usage:
 * ```typescript
 * const adapter = new DiscordVoiceAdapter();
 *
 * adapter.on('userAudioReceived', (userId, channelId, stream) => {
 *   // 处理用户音频
 * });
 *
 * await adapter.join(voiceChannel, guild);
 * ```
 */
export class DiscordVoiceAdapter extends EventEmitter {
  private connections: Map<string, VoiceConnection> = new Map();
  private players: Map<string, AudioPlayer> = new Map();
  private config: VoiceAdapterConfig;
  private activeSubscriptions: Map<string, Set<string>> = new Map(); // channelId -> Set<userId>

  constructor(config?: Partial<VoiceAdapterConfig>) {
    super();
    this.config = { ...DEFAULT_VOICE_CONFIG, ...config };
  }

  /**
   * 加入语音频道
   */
  async join(channel: VoiceChannel, guild: Guild): Promise<VoiceConnection> {
    const channelId = channel.id;

    // 检查是否已连接
    const existing = this.connections.get(channelId);
    if (existing) {
      return existing;
    }

    console.log(`[DiscordVoice] Joining channel: ${channel.name} (${channelId})`);

    const connection = joinVoiceChannel({
      channelId: channel.id,
      guildId: guild.id,
      adapterCreator: guild.voiceAdapterCreator,
      selfDeaf: this.config.selfDeaf,
      selfMute: this.config.selfMute,
    });

    // 等待连接就绪
    try {
      await entersState(connection, VoiceConnectionStatus.Ready, 30_000);
    } catch (error) {
      connection.destroy();
      throw new Error(`Failed to join voice channel: ${(error as Error).message}`);
    }

    // 创建音频播放器
    const player = createAudioPlayer();
    connection.subscribe(player);
    this.players.set(channelId, player);

    // 监听播放完成
    player.on(AudioPlayerStatus.Idle, () => {
      this.emit('playbackFinished', channelId);
    });

    player.on('error', (error) => {
      console.error(`[DiscordVoice] Player error in ${channelId}:`, error);
      this.emit('error', error);
    });

    // 设置音频接收
    this.setupAudioReceiver(connection, channelId);

    // 监听连接状态变化
    connection.on(VoiceConnectionStatus.Disconnected, async () => {
      try {
        // 尝试恢复连接
        await Promise.race([
          entersState(connection, VoiceConnectionStatus.Signalling, 5_000),
          entersState(connection, VoiceConnectionStatus.Connecting, 5_000),
        ]);
      } catch {
        // 无法恢复，清理连接
        this.cleanup(channelId);
        this.emit('disconnected', channelId, 'Connection lost');
      }
    });

    connection.on(VoiceConnectionStatus.Destroyed, () => {
      this.cleanup(channelId);
      this.emit('disconnected', channelId, 'Connection destroyed');
    });

    this.connections.set(channelId, connection);
    this.emit('connected', channelId);

    console.log(`[DiscordVoice] Connected to ${channel.name}`);
    return connection;
  }

  /**
   * 离开语音频道
   */
  leave(channelId: string): void {
    const connection = this.connections.get(channelId);
    if (connection) {
      connection.destroy();
      this.cleanup(channelId);
      console.log(`[DiscordVoice] Left channel ${channelId}`);
    }
  }

  /**
   * 离开所有语音频道
   */
  leaveAll(): void {
    for (const channelId of this.connections.keys()) {
      this.leave(channelId);
    }
  }

  /**
   * 播放音频到频道
   *
   * @param channelId 频道 ID
   * @param audioStream 音频流（Opus 或 PCM）
   * @param streamType 流类型
   */
  async play(
    channelId: string,
    audioStream: Readable,
    streamType: StreamType = StreamType.OggOpus,
  ): Promise<void> {
    const player = this.players.get(channelId);
    if (!player) {
      throw new Error(`Not connected to channel: ${channelId}`);
    }

    const resource = createAudioResource(audioStream, {
      inputType: streamType,
    });

    player.play(resource);

    // 等待播放完成
    return new Promise((resolve, reject) => {
      const onIdle = () => {
        cleanup();
        resolve();
      };
      const onError = (error: Error) => {
        cleanup();
        reject(error);
      };
      const cleanup = () => {
        player.removeListener(AudioPlayerStatus.Idle, onIdle);
        player.removeListener('error', onError);
      };

      player.once(AudioPlayerStatus.Idle, onIdle);
      player.once('error', onError);
    });
  }

  /**
   * 停止播放
   */
  stopPlayback(channelId: string): void {
    const player = this.players.get(channelId);
    if (player) {
      player.stop(true);
    }
  }

  /**
   * 是否已连接到指定频道
   */
  isConnected(channelId: string): boolean {
    return this.connections.has(channelId);
  }

  /**
   * 获取所有连接的频道 ID
   */
  getConnectedChannels(): string[] {
    return [...this.connections.keys()];
  }

  // ─── Audio Receiver ───────────────────────────────────────────────────

  /**
   * 设置音频接收监听
   *
   * 当用户开始说话时，订阅其音频流。
   * 音频流在用户停止说话后（silence duration）结束。
   */
  private setupAudioReceiver(connection: VoiceConnection, channelId: string): void {
    const receiver: VoiceReceiver = connection.receiver;
    const subs = new Set<string>();
    this.activeSubscriptions.set(channelId, subs);

    receiver.speaking.on('start', (userId: Snowflake) => {
      // 避免重复订阅
      if (subs.has(userId)) {
        return;
      }

      subs.add(userId);
      this.emit('userSpeakingStart', userId, channelId);

      const audioStream = receiver.subscribe(userId, {
        end: {
          behavior: EndBehaviorType.AfterSilence,
          duration: this.config.silenceDurationMs,
        },
      });

      // 音频流是 Opus 编码的 Readable
      this.emit('userAudioReceived', userId, channelId, audioStream);

      audioStream.on('end', () => {
        subs.delete(userId);
      });

      audioStream.on('error', (error) => {
        console.error(`[DiscordVoice] Audio stream error for user ${userId}:`, error);
        subs.delete(userId);
      });
    });
  }

  // ─── Cleanup ──────────────────────────────────────────────────────────

  private cleanup(channelId: string): void {
    this.connections.delete(channelId);
    this.players.delete(channelId);
    this.activeSubscriptions.delete(channelId);
  }
}
