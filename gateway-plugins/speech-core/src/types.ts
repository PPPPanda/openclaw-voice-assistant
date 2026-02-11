/**
 * Speech Core 类型定义
 *
 * 与 Python Speech Core Service 的 JSON-RPC 2.0 协议对应的 TypeScript 类型。
 */

// ─── Configuration ──────────────────────────────────────────────────────────

export interface SpeechCoreConfig {
  /** WebSocket 端点地址 */
  endpoint: string;
  /** 重连间隔（毫秒） */
  reconnectIntervalMs: number;
  /** 最大重连次数 */
  maxReconnectAttempts: number;
  /** 健康检查间隔（毫秒） */
  healthCheckIntervalMs: number;
  /** 请求超时（毫秒） */
  requestTimeoutMs: number;
}

export const DEFAULT_CONFIG: SpeechCoreConfig = {
  endpoint: 'ws://localhost:9001/speech',
  reconnectIntervalMs: 3000,
  maxReconnectAttempts: 10,
  healthCheckIntervalMs: 30000,
  requestTimeoutMs: 30000,
};

// ─── Audio Types ────────────────────────────────────────────────────────────

export type AudioFormatType = 'pcm_s16le' | 'opus' | 'mp3';

export interface AudioData {
  format: AudioFormatType;
  sampleRate: number;
  channels: number;
  /** Base64 encoded audio data */
  data: string;
}

export interface AudioOutputConfig {
  format: AudioFormatType;
  sampleRate: 16000 | 22050 | 24000 | 44100 | 48000;
  channels: 1 | 2;
}

// ─── STT Types ──────────────────────────────────────────────────────────────

export interface STTRequest {
  audio: AudioData;
  options: STTOptions;
  stream?: boolean;
}

export interface STTOptions {
  language?: string;
  model?: string;
  vadEnabled?: boolean;
  vadThreshold?: number;
}

export interface STTResult {
  text: string;
  language: string;
  confidence: number;
  segments: Segment[];
  processingTimeMs: number;
}

export interface Segment {
  start: number;
  end: number;
  text: string;
}

// ─── TTS Types ──────────────────────────────────────────────────────────────

export interface TTSRequest {
  text: string;
  options: TTSOptions;
  output?: AudioOutputConfig;
  stream?: boolean;
}

export interface TTSOptions {
  voice?: string;
  speed?: number;
  pitch?: number;
  provider?: 'piper' | 'elevenlabs' | 'openai';
}

export interface TTSResult {
  audio: string;  // Base64 encoded
  format: AudioFormatType;
  sampleRate: number;
  channels: number;
  durationMs: number;
  processingTimeMs: number;
}

export interface TTSChunk {
  type: 'chunk';
  index: number;
  audio: string;  // Base64 encoded
  durationMs: number;
  final: boolean;
}

export interface TTSStreamResult {
  chunks: TTSChunk[];
}

// ─── Status Types ───────────────────────────────────────────────────────────

export interface SpeechCoreStatus {
  status: 'healthy' | 'degraded' | 'unhealthy';
  stt_engine: string;
  tts_engine: string;
  vad_loaded: boolean;
  gpu_available: boolean;
  uptime_seconds: number;
}

export interface ModelList {
  stt: {
    engine: string;
    model: string;
    available: string[];
  };
  tts: {
    engine: string;
    voice: string;
  };
  vad: {
    engine: string;
    loaded: boolean;
  };
}

// ─── JSON-RPC Types ─────────────────────────────────────────────────────────

export interface JsonRpcRequest {
  jsonrpc: '2.0';
  id: string | number;
  method: string;
  params?: Record<string, unknown>;
}

export interface JsonRpcResponse<T = unknown> {
  jsonrpc: '2.0';
  id: string | number | null;
  result?: T;
  error?: JsonRpcError;
}

export interface JsonRpcError {
  code: number;
  message: string;
  data?: unknown;
}

// ─── Event Types ────────────────────────────────────────────────────────────

export interface SpeechEvent {
  event: string;
  userId: string;
  channelId: string;
  timestamp: number;
  data?: Record<string, unknown>;
}

// ─── Gateway RPC Interface ──────────────────────────────────────────────────

export interface SpeechCoreRPC {
  'speech.stt': (params: STTRequest) => Promise<STTResult>;
  'speech.tts': (params: TTSRequest) => Promise<TTSResult | TTSStreamResult>;
  'speech.status': () => Promise<SpeechCoreStatus>;
  'speech.models': () => Promise<ModelList>;
}
