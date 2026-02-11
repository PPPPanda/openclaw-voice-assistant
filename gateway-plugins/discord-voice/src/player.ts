/**
 * Discord 音频播放器
 *
 * 将 TTS 音频输出编码为 Opus 并通过 Discord 语音连接播放。
 */

import { createAudioResource, StreamType, AudioResource } from '@discordjs/voice';
import { Readable, Transform, TransformCallback } from 'stream';
import prism from 'prism-media';

/**
 * PCM → Opus 编码 Transform 流
 *
 * 将 PCM s16le 音频编码为 48kHz Opus，
 * 适合通过 Discord 语音连接播放。
 */
export class PCMToOpusStream extends Transform {
  private encoder: prism.opus.Encoder;
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

    // 20ms at 48kHz = 960 samples
    this.frameSize = (this.targetSampleRate * frameDurationMs) / 1000;

    this.encoder = new prism.opus.Encoder({
      rate: this.targetSampleRate,
      channels,
      frameSize: this.frameSize,
    });

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

      // 将数据添加到缓冲区
      this.buffer = Buffer.concat([this.buffer, pcm]);

      // 处理完整的帧
      const bytesPerFrame = this.frameSize * 2; // s16le = 2 bytes per sample
      while (this.buffer.length >= bytesPerFrame) {
        const frame = this.buffer.slice(0, bytesPerFrame);
        this.buffer = this.buffer.slice(bytesPerFrame);

        const encoded = this.encoder.encode(frame);
        if (encoded) {
          this.push(encoded);
        }
      }

      callback();
    } catch (error) {
      callback(error as Error);
    }
  }

  _flush(callback: TransformCallback): void {
    // 处理剩余数据（如果有的话，用静音填充）
    if (this.buffer.length > 0) {
      const bytesPerFrame = this.frameSize * 2;
      const padding = Buffer.alloc(bytesPerFrame - this.buffer.length, 0);
      const frame = Buffer.concat([this.buffer, padding]);

      const encoded = this.encoder.encode(frame);
      if (encoded) {
        this.push(encoded);
      }
    }
    callback();
  }

  /**
   * 简单的线性插值重采样
   */
  private resample(input: Buffer): Buffer {
    const ratio = this.targetSampleRate / this.sourceSampleRate;
    const inputSamples = input.length / 2;
    const outputSamples = Math.floor(inputSamples * ratio);
    const output = Buffer.alloc(outputSamples * 2);

    for (let i = 0; i < outputSamples; i++) {
      const srcIndex = i / ratio;
      const srcIndexFloor = Math.floor(srcIndex);
      const srcIndexCeil = Math.min(srcIndexFloor + 1, inputSamples - 1);
      const t = srcIndex - srcIndexFloor;

      const sample1 = input.readInt16LE(srcIndexFloor * 2);
      const sample2 = input.readInt16LE(srcIndexCeil * 2);
      const interpolated = Math.round(sample1 * (1 - t) + sample2 * t);

      output.writeInt16LE(
        Math.max(-32768, Math.min(32767, interpolated)),
        i * 2,
      );
    }

    return output;
  }
}

/**
 * 从 PCM Buffer 创建 AudioResource
 *
 * @param pcmBuffer PCM s16le 音频数据
 * @param sampleRate 音频采样率
 * @returns Discord AudioResource
 */
export function createAudioResourceFromPCM(
  pcmBuffer: Buffer,
  sampleRate: number = 22050,
): AudioResource {
  const pcmStream = new Readable({
    read() {
      this.push(pcmBuffer);
      this.push(null);
    },
  });

  const opusStream = pcmStream.pipe(
    new PCMToOpusStream({
      sourceSampleRate: sampleRate,
      targetSampleRate: 48000,
      channels: 1,
    }),
  );

  return createAudioResource(opusStream, {
    inputType: StreamType.Opus,
  });
}

/**
 * 从 Opus 流创建 AudioResource
 *
 * @param opusStream Opus 编码的音频流
 * @returns Discord AudioResource
 */
export function createAudioResourceFromOpus(opusStream: Readable): AudioResource {
  return createAudioResource(opusStream, {
    inputType: StreamType.Opus,
  });
}
