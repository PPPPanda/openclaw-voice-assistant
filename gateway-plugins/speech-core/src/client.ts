/**
 * Speech Core WebSocket RPC 客户端
 *
 * 通过 WebSocket + JSON-RPC 2.0 与 Python Speech Core Service 通信。
 * 支持自动重连、健康检查、请求超时。
 */

import WebSocket from 'ws';
import { v4 as uuidv4 } from 'uuid';
import { EventEmitter } from 'events';
import {
  SpeechCoreConfig,
  DEFAULT_CONFIG,
  JsonRpcRequest,
  JsonRpcResponse,
  STTRequest,
  STTResult,
  TTSRequest,
  TTSResult,
  TTSStreamResult,
  SpeechCoreStatus,
  ModelList,
} from './types';

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
};

export class SpeechCoreClient extends EventEmitter {
  private config: SpeechCoreConfig;
  private ws: WebSocket | null = null;
  private pendingRequests: Map<string, PendingRequest> = new Map();
  private reconnectAttempts = 0;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private healthCheckTimer: NodeJS.Timeout | null = null;
  private isConnecting = false;
  private _isConnected = false;

  constructor(config?: Partial<SpeechCoreConfig>) {
    super();
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  // ─── Connection Management ──────────────────────────────────────────────

  /**
   * 连接到 Speech Core 服务
   */
  async connect(): Promise<void> {
    if (this._isConnected || this.isConnecting) {
      return;
    }

    this.isConnecting = true;

    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(this.config.endpoint);

        this.ws.on('open', () => {
          this.isConnecting = false;
          this._isConnected = true;
          this.reconnectAttempts = 0;
          this.emit('connected');
          this.startHealthCheck();
          resolve();
        });

        this.ws.on('message', (data: WebSocket.Data) => {
          this.handleMessage(data.toString());
        });

        this.ws.on('close', (code: number, reason: Buffer) => {
          this._isConnected = false;
          this.isConnecting = false;
          this.emit('disconnected', code, reason.toString());
          this.stopHealthCheck();
          this.rejectAllPending(new Error(`Connection closed: ${code}`));
          this.scheduleReconnect();
        });

        this.ws.on('error', (error: Error) => {
          this.isConnecting = false;
          this.emit('error', error);
          if (!this._isConnected) {
            reject(error);
          }
        });
      } catch (error) {
        this.isConnecting = false;
        reject(error);
      }
    });
  }

  /**
   * 断开连接
   */
  disconnect(): void {
    this.stopHealthCheck();

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }

    this._isConnected = false;
    this.rejectAllPending(new Error('Client disconnected'));
  }

  /**
   * 是否已连接
   */
  get isConnected(): boolean {
    return this._isConnected;
  }

  // ─── RPC Methods ────────────────────────────────────────────────────────

  /**
   * 语音转文字
   */
  async stt(params: STTRequest): Promise<STTResult> {
    return this.call<STTResult>('speech.stt', params);
  }

  /**
   * 文字转语音
   */
  async tts(params: TTSRequest): Promise<TTSResult | TTSStreamResult> {
    return this.call<TTSResult | TTSStreamResult>('speech.tts', params);
  }

  /**
   * 获取服务状态
   */
  async status(): Promise<SpeechCoreStatus> {
    return this.call<SpeechCoreStatus>('speech.status', {});
  }

  /**
   * 获取可用模型列表
   */
  async models(): Promise<ModelList> {
    return this.call<ModelList>('speech.models', {});
  }

  // ─── Generic RPC Call ───────────────────────────────────────────────────

  /**
   * 发送 JSON-RPC 2.0 请求
   */
  private async call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    if (!this._isConnected || !this.ws) {
      throw new Error('Not connected to Speech Core service');
    }

    const id = uuidv4();
    const request: JsonRpcRequest = {
      jsonrpc: '2.0',
      id,
      method,
      params,
    };

    return new Promise<T>((resolve, reject) => {
      // 设置超时
      const timer = setTimeout(() => {
        this.pendingRequests.delete(id);
        reject(new Error(`Request timeout: ${method} (${this.config.requestTimeoutMs}ms)`));
      }, this.config.requestTimeoutMs);

      this.pendingRequests.set(id, {
        resolve: resolve as (value: unknown) => void,
        reject,
        timer,
      });

      // 发送请求
      this.ws!.send(JSON.stringify(request), (error) => {
        if (error) {
          clearTimeout(timer);
          this.pendingRequests.delete(id);
          reject(error);
        }
      });
    });
  }

  // ─── Message Handling ───────────────────────────────────────────────────

  private handleMessage(data: string): void {
    let response: JsonRpcResponse;
    try {
      response = JSON.parse(data);
    } catch {
      this.emit('error', new Error(`Invalid JSON response: ${data.slice(0, 100)}`));
      return;
    }

    if (response.id == null) {
      // 通知/事件（无 id）
      this.emit('notification', response);
      return;
    }

    const pending = this.pendingRequests.get(String(response.id));
    if (!pending) {
      return;
    }

    this.pendingRequests.delete(String(response.id));
    clearTimeout(pending.timer);

    if (response.error) {
      pending.reject(
        new Error(`RPC Error [${response.error.code}]: ${response.error.message}`)
      );
    } else {
      pending.resolve(response.result);
    }
  }

  // ─── Reconnection ──────────────────────────────────────────────────────

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.config.maxReconnectAttempts) {
      this.emit('reconnect_failed');
      return;
    }

    this.reconnectAttempts++;
    const delay = this.config.reconnectIntervalMs * Math.min(this.reconnectAttempts, 5);

    this.reconnectTimer = setTimeout(async () => {
      this.emit('reconnecting', this.reconnectAttempts);
      try {
        await this.connect();
      } catch {
        // connect() 失败会触发 close 事件，进而再次调度重连
      }
    }, delay);
  }

  // ─── Health Check ───────────────────────────────────────────────────────

  private startHealthCheck(): void {
    this.stopHealthCheck();
    this.healthCheckTimer = setInterval(async () => {
      try {
        const result = await this.status();
        this.emit('health', result);
      } catch (error) {
        this.emit('health_error', error);
      }
    }, this.config.healthCheckIntervalMs);
  }

  private stopHealthCheck(): void {
    if (this.healthCheckTimer) {
      clearInterval(this.healthCheckTimer);
      this.healthCheckTimer = null;
    }
  }

  // ─── Helpers ────────────────────────────────────────────────────────────

  private rejectAllPending(error: Error): void {
    for (const [id, pending] of this.pendingRequests) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pendingRequests.clear();
  }
}
