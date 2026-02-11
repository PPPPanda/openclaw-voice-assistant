/**
 * Discord 音频播放器
 *
 * 将 TTS 音频输出编码为 Opus 并通过 Discord 语音连接播放。
 */

import { createAudioResource, StreamType, AudioResource } from '@discordjs/voice';
import { OpusEncoder } from '@discordjs/opus';
import { Readable, Transform, TransformCallback } from 'stream';

/**
 * PCM → Opus 编码 Transform 流
 *
 * 将 PCM s16le 音频编码为 48kHz Opus，
 * 适合通过 Discord 语音连接播放。
 */
export class PCMToOpusStream extends Transform {
  private encoder: OpusEncoder;
  private frameSize: number;
  private buffer: Buffer;
  private sourceSampleRate: number;
  private targetSampleRate: number;

  constructor(options?: {
    sourceSampleRate?: number;
    targetSampleRate?: number;
    channels?: number;
    frameDurationMs?: number;
  }) {
    super();
    this.sourceSampleRate = options?.sourceSampleRate ?? 22050;
    this.targetSampleRate = options?.targetSampleRate ?? 48000;
    const channels = options?.channels ?? 1;
    const frameDurationMs = options?.frameDurationMs ?? 20;

    this.encoder = new OpusEncoder(this.targetSampleRate, channels);
    // 20ms at 48kHz = 960 samples
    this.frameSize = (this.targetSampleRate * frameDurationMs) / 1000;
    this.buffer = Buffer.alloc(0);
  }

  _transform(
    chunk: Buffer,
    _encoding: BufferEncoding,
    callback: TransformCallback,
  ): void {
    try {
      // 如果需要重采样（例如 Piper 输出 22050Hz → Discord 48000Hz）
      let pcm: Buffer;
      if (this.sourceSampleRate !== this.targetSampleRate) {
        pcm = this.resample(chunk);
      } else {
        pcm = chunk;
      }

      // 追加到缓冲区
      this.buffer = Buffer.concat([this.buffer, pcm]);

      // 每帧所需字节数（s16le = 2 bytes per sample）
      const frameSizeBytes = this.frameSize * 2;

      // 处理完整的帧
      while (this.buffer.length >= frameSizeBytes) {
        const frame = this.buffer.subarray(0, frameSizeBytes);
        this.buffer = this.buffer.subarray(frameSizeBytes);

        const encoded = this.encoder.encode(frame);
        this.push(encoded);
      }

      callback();
    } catch (error) {
      callback(error as Error);
    }
  }

  _flush(callback: TransformCallback): void {
    try {
      // 处理剩余数据（用零填充到帧大小）
      if (this.buffer.length > 0) {
        const frameSizeBytes = this.frameSize * 2;
        const padded = Buffer.alloc(frameSizeBytes);
        this.buffer.copy(padded);
        const encoded = this.encoder.encode(padded);
        this.push(encoded);
      }
      callback();
    } catch (error) {
      callback(error as Error);
    }
  }

  /**
   * 线性插值上采样
   */
  private resample(pcmBuffer: Buffer): Buffer {
    const ratio = this.targetSampleRate / this.sourceSampleRate;
    const inputSamples = pcmBuffer.length / 2;
    const outputSamples = Math.floor(inputSamples * ratio);
    const output = Buffer.alloc(outputSamples * 2);

    for (let i = 0; i < outputSamples; i++) {
      const srcIndex = i / ratio;
      const srcIndexFloor = Math.floor(srcIndex);
      const srcIndexCeil = Math.min(srcIndexFloor + 1, inputSamples - 1);
      const frac = srcIndex - srcIndexFloor;

      const sample1 = pcmBuffer.readInt16LE(srcIndexFloor * 2);
      const sample2 = pcmBuffer.readInt16LE(srcIndexCeil * 2);
      const interpolated = Math.round(sample1 * (1 - frac) + sample2 * frac);

      output.writeInt16LE(
        Math.max(-32768, Math.min(32767, interpolated)),
        i * 2,
      );
    }

    return output;
  }
}

/**
 * 从 PCM Buffer 创建 Discord 可播放的 AudioResource
 *
 * @param pcmData PCM s16le 音频数据
 * @param sampleRate 源采样率（如 22050 来自 Piper）
 */
export function createAudioResourceFromPCM(
  pcmData: Buffer,
  sampleRate: number = 22050,
): AudioResource {
  const pcmStream = new Readable({
    read() {
      this.push(pcmData);
      this.push(null);
    },
  });

  const encoder = new PCMToOpusStream({ sourceSampleRate: sampleRate });
  const opusStream = pcmStream.pipe(encoder);

  return createAudioResource(opusStream, {
    inputType: StreamType.Opus,
  });
}

/**
 * 从 Opus 数据创建 Discord AudioResource
 */
export function createAudioResourceFromOpus(opusData: Buffer): AudioResource {
  const stream = new Readable({
    read() {
      this.push(opusData);
      this.push(null);
    },
  });

  return createAudioResource(stream, {
    inputType: StreamType.Opus,
  });
}
