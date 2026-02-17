/**
 * Voice Pipeline (P1-1)
 *
 * 端到端实时语音管线：
 *   Discord Opus → PCM(16kHz) → STT → LLM → TTS → PCM → Opus(48kHz) → Discord
 *
 * 半双工模式：用户说完 → 处理 → 回复。
 * 支持多用户并发（每个用户独立会话）。
 */

import { EventEmitter } from 'events';
import { Readable } from 'stream';
import { createPCMStream, collectPCMBuffer } from './receiver';
import { createAudioResourceFromPCM } from './player';
import { LLMClient, LLMConfig, LLMResponse } from './llm';
import type { SpeechCoreClient } from '../../speech-core/src/client';
import type { STTResult, TTSResult } from '../../speech-core/src/types';

// ============================================================================
// 类型定义
// ============================================================================

export interface VoicePipelineConfig {
  /** LLM 配置 */
  llm: LLMConfig;
  /** STT 语言 */
  sttLanguage?: string;
  /** TTS 提供者 */
  ttsProvider?: 'piper' | 'elevenlabs' | 'openai';
  /** TTS 语音 */
  ttsVoice?: string;
  /** 最小音频时长（毫秒），低于此值忽略 */
  minAudioDurationMs?: number;
  /** STT 最低置信度，低于此值忽略 */
  minConfidence?: number;
  /** 是否启用管线延迟计时 */
  enableLatencyLogging?: boolean;
}

export interface PipelineMetrics {
  /** STT 延迟（毫秒） */
  sttLatencyMs: number;
  /** LLM 延迟（毫秒） */
  llmLatencyMs: number;
  /** TTS 延迟（毫秒） */
  ttsLatencyMs: number;
  /** 总延迟（毫秒） */
  totalLatencyMs: number;
  /** STT 结果 */
  sttText: string;
  /** LLM 回复 */
  llmText: string;
  /** 用户 ID */
  userId: string;
  /** 频道 ID */
  channelId: string;
}

export interface PipelineEvents {
  /** 管线处理开始 */
  processingStart: (userId: string, channelId: string) => void;
  /** STT 完成 */
  sttComplete: (userId: string, text: string, latencyMs: number) => void;
  /** LLM 完成 */
  llmComplete: (userId: string, text: string, latencyMs: number) => void;
  /** TTS 完成 */
  ttsComplete: (userId: string, audioBytes: number, latencyMs: number) => void;
  /** 管线处理完成（含完整指标） */
  processingComplete: (metrics: PipelineMetrics) => void;
  /** 管线错误 */
  pipelineError: (userId: string, channelId: string, error: Error, stage: string) => void;
  /** 音频已跳过（太短或置信度低） */
  audioSkipped: (userId: string, reason: string) => void;
}

interface Logger {
  info: (msg: string, ...args: unknown[]) => void;
  warn: (msg: string, ...args: unknown[]) => void;
  error: (msg: string, ...args: unknown[]) => void;
  debug: (msg: string, ...args: unknown[]) => void;
}

// ============================================================================
// Voice Pipeline
// ============================================================================

/**
 * 语音管线
 *
 * 串联 STT → LLM → TTS，处理单个用户的语音输入并生成音频回复。
 * 外部负责音频的接收和播放（通过 DiscordVoiceAdapter）。
 *
 * Usage:
 * ```typescript
 * const pipeline = new VoicePipeline(config, speechCore, logger);
 *
 * // 当接收到用户音频时
 * adapter.on('userAudioReceived', async (userId, channelId, opusStream) => {
 *   const result = await pipeline.process(userId, channelId, opusStream);
 *   if (result) {
 *     await adapter.play(channelId, result.audioStream);
 *   }
 * });
 * ```
 */
export class VoicePipeline extends EventEmitter {
  private config: VoicePipelineConfig;
  private speechCore: SpeechCoreClient;
  private llm: LLMClient;
  private logger: Logger;

  /** 正在处理中的用户（防止并发处理同一用户） */
  private processing: Set<string> = new Set();

  constructor(
    config: VoicePipelineConfig,
    speechCore: SpeechCoreClient,
    logger: Logger,
  ) {
    super();
    this.config = {
      sttLanguage: 'auto',
      ttsProvider: 'piper',
      minAudioDurationMs: 300,
      minConfidence: 0.3,
      enableLatencyLogging: true,
      ...config,
    };
    this.speechCore = speechCore;
    this.llm = new LLMClient(config.llm);
    this.logger = logger;
  }

  /**
   * 处理用户语音输入，返回 TTS 音频
   *
   * @param userId Discord 用户 ID
   * @param channelId 语音频道 ID
   * @param opusStream Discord 的 Opus 音频流
   * @returns 音频 PCM Buffer + 采样率，或 null（跳过）
   */
  async process(
    userId: string,
    channelId: string,
    opusStream: Readable,
  ): Promise<{ pcmBuffer: Buffer; sampleRate: number } | null> {
    // 防止同一用户并发处理
    const processingKey = `${channelId}:${userId}`;
    if (this.processing.has(processingKey)) {
      this.logger.debug(`[Pipeline] Skipping: user ${userId} already being processed`);
      return null;
    }

    this.processing.add(processingKey);
    const pipelineStart = Date.now();

    try {
      this.emit('processingStart', userId, channelId);

      // ── Stage 1: Opus → PCM ──────────────────────────────────────────
      const pcmStream = createPCMStream(opusStream, { targetSampleRate: 16000 });
      const pcmBuffer = await collectPCMBuffer(pcmStream);

      // 检查音频时长
      const durationMs = (pcmBuffer.length / 2 / 16000) * 1000;
      if (durationMs < this.config.minAudioDurationMs!) {
        this.emit('audioSkipped', userId, `too short: ${durationMs.toFixed(0)}ms`);
        this.logger.debug(`[Pipeline] Audio too short: ${durationMs.toFixed(0)}ms`);
        return null;
      }

      // ── Stage 2: STT ─────────────────────────────────────────────────
      const sttStart = Date.now();
      let sttResult: STTResult;

      try {
        sttResult = await this.speechCore.stt({
          audio: {
            format: 'pcm_s16le',
            sampleRate: 16000,
            channels: 1,
            data: pcmBuffer.toString('base64'),
          },
          options: {
            language: this.config.sttLanguage,
            vadEnabled: false, // VAD 由 Discord 端处理
          },
        });
      } catch (error) {
        this.emit('pipelineError', userId, channelId, error as Error, 'stt');
        throw error;
      }

      const sttLatencyMs = Date.now() - sttStart;
      this.emit('sttComplete', userId, sttResult.text, sttLatencyMs);

      // 检查转写结果
      if (!sttResult.text.trim()) {
        this.emit('audioSkipped', userId, 'empty transcription');
        return null;
      }

      if (sttResult.confidence < this.config.minConfidence!) {
        this.emit(
          'audioSkipped',
          userId,
          `low confidence: ${sttResult.confidence.toFixed(2)}`,
        );
        return null;
      }

      this.logger.info(
        `[Pipeline] STT: "${sttResult.text}" (conf=${sttResult.confidence.toFixed(2)}, ${sttLatencyMs}ms)`,
      );

      // ── Stage 3: LLM ─────────────────────────────────────────────────
      const llmStart = Date.now();
      let llmResponse: LLMResponse;

      try {
        // 会话 key = channelId:userId，每个用户在每个频道有独立上下文
        const sessionId = `${channelId}:${userId}`;
        llmResponse = await this.llm.chat(sttResult.text, sessionId);
      } catch (error) {
        this.emit('pipelineError', userId, channelId, error as Error, 'llm');
        throw error;
      }

      const llmLatencyMs = Date.now() - llmStart;
      this.emit('llmComplete', userId, llmResponse.text, llmLatencyMs);

      if (!llmResponse.text.trim()) {
        this.logger.warn('[Pipeline] LLM returned empty response');
        return null;
      }

      this.logger.info(
        `[Pipeline] LLM: "${llmResponse.text.slice(0, 80)}${llmResponse.text.length > 80 ? '...' : ''}" (${llmLatencyMs}ms)`,
      );

      // ── Stage 4: TTS ─────────────────────────────────────────────────
      const ttsStart = Date.now();
      let ttsResult: TTSResult;

      try {
        const ttsResponse = await this.speechCore.tts({
          text: llmResponse.text,
          options: {
            provider: this.config.ttsProvider,
            voice: this.config.ttsVoice,
          },
          stream: false,
        });

        // TTS 可能返回 TTSResult 或 TTSStreamResult
        ttsResult = ttsResponse as TTSResult;
      } catch (error) {
        this.emit('pipelineError', userId, channelId, error as Error, 'tts');
        throw error;
      }

      const ttsLatencyMs = Date.now() - ttsStart;
      const ttsAudioBuffer = Buffer.from(ttsResult.audio, 'base64');
      this.emit('ttsComplete', userId, ttsAudioBuffer.length, ttsLatencyMs);

      // ── 指标汇总 ──────────────────────────────────────────────────────
      const totalLatencyMs = Date.now() - pipelineStart;
      const metrics: PipelineMetrics = {
        sttLatencyMs,
        llmLatencyMs,
        ttsLatencyMs,
        totalLatencyMs,
        sttText: sttResult.text,
        llmText: llmResponse.text,
        userId,
        channelId,
      };

      this.emit('processingComplete', metrics);

      if (this.config.enableLatencyLogging) {
        this.logger.info(
          `[Pipeline] ✅ Total: ${totalLatencyMs}ms (STT: ${sttLatencyMs}ms | LLM: ${llmLatencyMs}ms | TTS: ${ttsLatencyMs}ms)`,
        );
      }

      return {
        pcmBuffer: ttsAudioBuffer,
        sampleRate: ttsResult.sampleRate,
      };
    } catch (error) {
      this.logger.error(`[Pipeline] Error processing user ${userId}: ${error}`);
      return null;
    } finally {
      this.processing.delete(processingKey);
    }
  }

  /**
   * 清除用户的 LLM 对话历史
   */
  clearUserHistory(channelId: string, userId: string): void {
    this.llm.clearHistory(`${channelId}:${userId}`);
  }

  /**
   * 清除所有对话历史
   */
  clearAllHistory(): void {
    this.llm.clearAllHistory();
  }

  /**
   * 检查某用户是否正在被处理
   */
  isProcessing(channelId: string, userId: string): boolean {
    return this.processing.has(`${channelId}:${userId}`);
  }
}
