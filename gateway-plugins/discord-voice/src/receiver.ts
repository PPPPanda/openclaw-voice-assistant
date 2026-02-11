/**
 * Discord 音频接收器
 *
 * 处理从 Discord 语音频道接收到的 Opus 音频流，
 * 将其解码为 PCM 并提供给 Speech Core 处理。
 */

import { Transform, TransformCallback, Readable } from 'stream';
import prism from 'prism-media';

/**
 * Opus → PCM 解码 Transform 流
 *
 * Discord 发送 48kHz Opus 编码的音频帧（20ms 每帧）。
 * 此 Transform 将其解码为 PCM s16le，可选择重采样到 16kHz。
 */
export class OpusToPCMStream extends Transform {
  private decoder: prism.opus.Decoder;
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

    this.decoder = new prism.opus.Decoder({
      rate: this.sourceSampleRate,
      channels,
      frameSize: 960, // 20ms at 48kHz
    });
  }

  _transform(
    chunk: Buffer,
    _encoding: BufferEncoding,
    callback: TransformCallback,
  ): void {
    try {
      // 解码 Opus → PCM s16le
      const pcm = this.decoder.decode(chunk);

      if (!pcm) {
        callback();
        return;
      }

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
   * 注意：这是一个基础实现，音质可能不如专业重采样库。
   * 生产环境建议使用 FFmpeg 或 libsamplerate。
   */
  private resample(input: Buffer): Buffer {
    const ratio = this.targetSampleRate / this.sourceSampleRate;
    const inputSamples = input.length / 2; // s16le = 2 bytes per sample
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

  _flush(callback: TransformCallback): void {
    callback();
  }
}

/**
 * 创建 PCM 流的便捷函数
 */
export function createPCMStream(
  opusStream: Readable,
  options?: {
    targetSampleRate?: number;
    channels?: number;
  },
): Readable {
  const decoder = new OpusToPCMStream({
    sourceSampleRate: 48000,
    targetSampleRate: options?.targetSampleRate ?? 16000,
    channels: options?.channels ?? 1,
  });

  return opusStream.pipe(decoder);
}

/**
 * 收集 PCM 流的所有数据到一个 Buffer
 */
export function collectPCMBuffer(pcmStream: Readable): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];

    pcmStream.on('data', (chunk: Buffer) => {
      chunks.push(chunk);
    });

    pcmStream.on('end', () => {
      resolve(Buffer.concat(chunks));
    });

    pcmStream.on('error', (error: Error) => {
      reject(error);
    });
  });
}
