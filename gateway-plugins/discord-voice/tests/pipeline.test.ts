/**
 * VoicePipeline 单元测试
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { Readable } from 'stream';
import { VoicePipeline, VoicePipelineConfig, PipelineMetrics } from '../src/pipeline';

// ── Mocks ──────────────────────────────────────────────────────────────────

// Mock receiver module
vi.mock('../src/receiver', () => ({
  createPCMStream: vi.fn((_stream, _opts) => {
    // 返回一个会产出 PCM 数据的流
    const s = new Readable({ read() {} });
    // 立刻发出数据然后结束
    process.nextTick(() => {
      s.push(Buffer.alloc(32000, 0x55)); // 1 秒 16kHz PCM
      s.push(null);
    });
    return s;
  }),
  collectPCMBuffer: vi.fn(async (stream: Readable) => {
    return new Promise<Buffer>((resolve) => {
      const chunks: Buffer[] = [];
      stream.on('data', (chunk: Buffer) => chunks.push(chunk));
      stream.on('end', () => resolve(Buffer.concat(chunks)));
    });
  }),
}));

// Mock SpeechCoreClient
function createMockSpeechCore() {
  return {
    connect: vi.fn(),
    disconnect: vi.fn(),
    isConnected: true,
    stt: vi.fn().mockResolvedValue({
      text: '你好',
      language: 'zh',
      confidence: 0.95,
      segments: [],
      processingTimeMs: 200,
    }),
    tts: vi.fn().mockResolvedValue({
      audio: Buffer.from('fake-pcm-audio').toString('base64'),
      format: 'pcm_s16le',
      sampleRate: 22050,
      channels: 1,
      durationMs: 500,
      processingTimeMs: 100,
    }),
    status: vi.fn(),
    models: vi.fn(),
    on: vi.fn(),
    emit: vi.fn(),
  };
}

// Mock fetch for LLM
const mockFetch = vi.fn().mockResolvedValue({
  ok: true,
  json: async () => ({
    choices: [{ message: { role: 'assistant', content: '你好！有什么可以帮你的？' } }],
    model: 'test-model',
    usage: { prompt_tokens: 20, completion_tokens: 10, total_tokens: 30 },
  }),
});
global.fetch = mockFetch as unknown as typeof fetch;

const mockLogger = {
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
};

const defaultConfig: VoicePipelineConfig = {
  llm: {
    apiEndpoint: 'https://api.example.com/v1',
    apiKey: 'test-key',
    model: 'test-model',
  },
  sttLanguage: 'auto',
  ttsProvider: 'piper',
  minAudioDurationMs: 300,
  minConfidence: 0.3,
  enableLatencyLogging: true,
};

describe('VoicePipeline', () => {
  let pipeline: VoicePipeline;
  let mockSpeechCore: ReturnType<typeof createMockSpeechCore>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockSpeechCore = createMockSpeechCore();
    pipeline = new VoicePipeline(defaultConfig, mockSpeechCore as any, mockLogger);
  });

  function createMockOpusStream(): Readable {
    const s = new Readable({ read() {} });
    process.nextTick(() => {
      s.push(Buffer.alloc(960, 0));
      s.push(null);
    });
    return s;
  }

  it('should process audio through full pipeline', async () => {
    const result = await pipeline.process('user-1', 'channel-1', createMockOpusStream());

    expect(result).not.toBeNull();
    expect(result!.pcmBuffer).toBeInstanceOf(Buffer);
    expect(result!.sampleRate).toBe(22050);

    // Verify all stages were called
    expect(mockSpeechCore.stt).toHaveBeenCalledOnce();
    expect(mockFetch).toHaveBeenCalledOnce();
    expect(mockSpeechCore.tts).toHaveBeenCalledOnce();
  });

  it('should emit processingComplete event with metrics', async () => {
    const metricsPromise = new Promise<PipelineMetrics>((resolve) => {
      pipeline.on('processingComplete', resolve);
    });

    await pipeline.process('user-1', 'channel-1', createMockOpusStream());

    const metrics = await metricsPromise;
    expect(metrics.sttText).toBe('你好');
    expect(metrics.llmText).toBe('你好！有什么可以帮你的？');
    expect(metrics.userId).toBe('user-1');
    expect(metrics.channelId).toBe('channel-1');
    expect(metrics.totalLatencyMs).toBeGreaterThanOrEqual(0);
    expect(metrics.sttLatencyMs).toBeGreaterThanOrEqual(0);
    expect(metrics.llmLatencyMs).toBeGreaterThanOrEqual(0);
    expect(metrics.ttsLatencyMs).toBeGreaterThanOrEqual(0);
  });

  it('should skip audio with empty transcription', async () => {
    mockSpeechCore.stt.mockResolvedValueOnce({
      text: '',
      language: 'en',
      confidence: 0.9,
      segments: [],
      processingTimeMs: 100,
    });

    const result = await pipeline.process('user-1', 'channel-1', createMockOpusStream());
    expect(result).toBeNull();
    expect(mockFetch).not.toHaveBeenCalled(); // LLM should not be called
  });

  it('should skip audio with low confidence', async () => {
    mockSpeechCore.stt.mockResolvedValueOnce({
      text: 'hmm',
      language: 'en',
      confidence: 0.1, // below 0.3 threshold
      segments: [],
      processingTimeMs: 100,
    });

    const result = await pipeline.process('user-1', 'channel-1', createMockOpusStream());
    expect(result).toBeNull();
  });

  it('should prevent concurrent processing of same user', async () => {
    // Make STT slow
    mockSpeechCore.stt.mockImplementation(() =>
      new Promise((resolve) =>
        setTimeout(
          () =>
            resolve({
              text: 'test',
              language: 'en',
              confidence: 0.9,
              segments: [],
              processingTimeMs: 100,
            }),
          100,
        ),
      ),
    );

    const p1 = pipeline.process('user-1', 'channel-1', createMockOpusStream());
    const p2 = pipeline.process('user-1', 'channel-1', createMockOpusStream());

    const [result1, result2] = await Promise.all([p1, p2]);

    // Second request should be skipped
    expect(result2).toBeNull();
    // STT should only be called once (first request)
    expect(mockSpeechCore.stt).toHaveBeenCalledOnce();
  });

  it('should allow concurrent processing of different users', async () => {
    const p1 = pipeline.process('user-1', 'channel-1', createMockOpusStream());
    const p2 = pipeline.process('user-2', 'channel-1', createMockOpusStream());

    const [result1, result2] = await Promise.all([p1, p2]);

    expect(result1).not.toBeNull();
    expect(result2).not.toBeNull();
    expect(mockSpeechCore.stt).toHaveBeenCalledTimes(2);
  });

  it('should handle STT errors gracefully', async () => {
    mockSpeechCore.stt.mockRejectedValueOnce(new Error('STT service down'));

    const errorHandler = vi.fn();
    pipeline.on('pipelineError', errorHandler);

    const result = await pipeline.process('user-1', 'channel-1', createMockOpusStream());

    expect(result).toBeNull();
    expect(errorHandler).toHaveBeenCalledWith(
      'user-1',
      'channel-1',
      expect.any(Error),
      'stt',
    );
  });

  it('should handle LLM errors gracefully', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: async () => 'Internal Server Error',
    });

    const errorHandler = vi.fn();
    pipeline.on('pipelineError', errorHandler);

    const result = await pipeline.process('user-1', 'channel-1', createMockOpusStream());

    expect(result).toBeNull();
    expect(errorHandler).toHaveBeenCalledWith(
      'user-1',
      'channel-1',
      expect.any(Error),
      'llm',
    );
  });

  it('should handle TTS errors gracefully', async () => {
    mockSpeechCore.tts.mockRejectedValueOnce(new Error('TTS engine failed'));

    const errorHandler = vi.fn();
    pipeline.on('pipelineError', errorHandler);

    const result = await pipeline.process('user-1', 'channel-1', createMockOpusStream());

    expect(result).toBeNull();
    expect(errorHandler).toHaveBeenCalledWith(
      'user-1',
      'channel-1',
      expect.any(Error),
      'tts',
    );
  });

  it('should clear user history', () => {
    // clearUserHistory should not throw
    expect(() => pipeline.clearUserHistory('channel-1', 'user-1')).not.toThrow();
  });

  it('should report processing status', async () => {
    expect(pipeline.isProcessing('channel-1', 'user-1')).toBe(false);

    // Make processing slow to check isProcessing
    mockSpeechCore.stt.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({
        text: 'test', language: 'en', confidence: 0.9, segments: [], processingTimeMs: 100,
      }), 200)),
    );

    const p = pipeline.process('user-1', 'channel-1', createMockOpusStream());

    // Wait a tick for processing to start
    await new Promise((r) => setTimeout(r, 10));
    expect(pipeline.isProcessing('channel-1', 'user-1')).toBe(true);

    await p;
    expect(pipeline.isProcessing('channel-1', 'user-1')).toBe(false);
  });
});
