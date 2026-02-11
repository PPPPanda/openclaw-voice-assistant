/**
 * Discord 音频接收器
 *
 * 处理从 Discord 语音频道接收到的 Opus 音频流，
 * 将其解码为 PCM 并提供给 Speech Core 处理。
 */

import { OpusEncoder } from '@discordjs/opus';
import { Transform, TransformCallback, Readable } from 'stream';

/**
 * Opus → PCM 解码 Transform 流
 *
 * Discord 发送 48kHz Opus 编码的音频帧（20ms 每帧）。
 * 此 Transform 将其解码为 PCM s16le，可选择重采样到 16kHz。
 */
export class OpusToPCMStream extends Transform {
  private encoder: OpusEncoder;
  private targetSampleRate: number;
  private sourceSampleRate: number;

  constructor(options?: {
    sourceSampleRate?: number;
    targetSampleRate?: number;
    channels?: number;
  }) {
    super();
    this.sourceSampleRate = options?.sourceSampleRate ?? 48000;
    this.targetSampleRate = options?.targetSampleRate ?? 16000;
    const channels = options?.channels ?? 1;

    this.encoder = new OpusEncoder(this.sourceSampleRate, channels);
  }

  _transform(
    chunk: Buffer,
    _encoding: BufferEncoding,
    callback: TransformCallback,
  ): void {
    try {
      // 解码 Opus → PCM s16le
      const pcm = this.encoder.decode(chunk);

      // 如果需要重采样
      if (this.sourceSampleRate !== this.targetSampleRate) {
        const resampled = this.resample(pcm);
        this.push(resampled);
      } else {
        this.push(pcm);
      }

      callback();
    } catch (error) {
      callback(error as Error);
    }
  }

  /**
   * 简单的线性插值重采样
   *
   * 从 48kHz 下采样到 16kHz（比率 3:1）
   */
  private resample(pcmBuffer: Buffer): Buffer {
    const ratio = this.sourceSampleRate / this.targetSampleRate;
    const inputSamples = pcmBuffer.length / 2; // s16le = 2 bytes per sample
    const outputSamples = Math.floor(inputSamples / ratio);
    const output = Buffer.alloc(outputSamples * 2);

    for (let i = 0; i < outputSamples; i++) {
      const srcIndex = i * ratio;
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
 * 创建一个将 Opus 流转换为 PCM 16kHz 的管道
 */
export function createPCMStream(
  opusStream: Readable,
  options?: {
    targetSampleRate?: number;
  },
): Readable {
  const decoder = new OpusToPCMStream({
    sourceSampleRate: 48000,
    targetSampleRate: options?.targetSampleRate ?? 16000,
    channels: 1,
  });

  return opusStream.pipe(decoder);
}

/**
 * 将 PCM 流收集为 Buffer
 */
export async function collectPCMBuffer(stream: Readable): Promise<Buffer> {
  const chunks: Buffer[] = [];

  return new Promise((resolve, reject) => {
    stream.on('data', (chunk: Buffer) => {
      chunks.push(chunk);
    });

    stream.on('end', () => {
      resolve(Buffer.concat(chunks));
    });

    stream.on('error', reject);
  });
}
