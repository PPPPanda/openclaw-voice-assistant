/**
 * LLM Client
 *
 * OpenAI-compatible API 客户端，用于 P1-1 端到端语音管线。
 * 支持任何 OpenAI 兼容端点（OpenAI、Anthropic via proxy、本地 LLM 等）。
 */

// ============================================================================
// 类型定义
// ============================================================================

export interface LLMConfig {
  /** API 端点 (e.g. https://api.openai.com/v1) */
  apiEndpoint: string;
  /** API Key */
  apiKey: string;
  /** 模型名称 (e.g. gpt-4o-mini, claude-3-haiku) */
  model: string;
  /** 系统提示词 */
  systemPrompt?: string;
  /** 最大回复 token 数 */
  maxTokens?: number;
  /** 温度 */
  temperature?: number;
  /** 请求超时（毫秒） */
  timeoutMs?: number;
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface LLMResponse {
  text: string;
  model: string;
  usage: {
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
  };
  latencyMs: number;
}

const DEFAULT_SYSTEM_PROMPT = `You are a voice assistant in a Discord voice channel. Keep responses concise and conversational — they will be spoken aloud via TTS. Avoid markdown, code blocks, or long lists. Respond naturally as if in a voice conversation.`;

// ============================================================================
// LLM Client
// ============================================================================

export class LLMClient {
  private config: LLMConfig;
  private conversationHistory: Map<string, ChatMessage[]> = new Map();

  constructor(config: LLMConfig) {
    this.config = {
      maxTokens: 256,
      temperature: 0.7,
      timeoutMs: 15000,
      systemPrompt: DEFAULT_SYSTEM_PROMPT,
      ...config,
    };
  }

  /**
   * 发送消息并获取回复
   *
   * @param text 用户输入文本
   * @param sessionId 会话 ID（用于维护上下文）
   * @returns LLM 回复
   */
  async chat(text: string, sessionId: string): Promise<LLMResponse> {
    const startTime = Date.now();

    // 获取或创建会话历史
    let history = this.conversationHistory.get(sessionId);
    if (!history) {
      history = [];
      if (this.config.systemPrompt) {
        history.push({ role: 'system', content: this.config.systemPrompt });
      }
      this.conversationHistory.set(sessionId, history);
    }

    // 添加用户消息
    history.push({ role: 'user', content: text });

    // 限制历史长度（保留 system + 最近 20 条）
    const maxHistory = 21; // system + 20 turns
    if (history.length > maxHistory) {
      const system = history[0].role === 'system' ? [history[0]] : [];
      const recent = history.slice(-(maxHistory - system.length));
      history = [...system, ...recent];
      this.conversationHistory.set(sessionId, history);
    }

    // 调用 API
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.config.timeoutMs);

    try {
      const response = await fetch(`${this.config.apiEndpoint}/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.config.apiKey}`,
        },
        body: JSON.stringify({
          model: this.config.model,
          messages: history,
          max_tokens: this.config.maxTokens,
          temperature: this.config.temperature,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const body = await response.text().catch(() => '');
        throw new Error(`LLM API error ${response.status}: ${body.slice(0, 300)}`);
      }

      const data = await response.json() as {
        choices: Array<{
          message: { role: string; content: string };
          finish_reason: string;
        }>;
        model: string;
        usage?: {
          prompt_tokens: number;
          completion_tokens: number;
          total_tokens: number;
        };
      };

      const assistantMessage = data.choices[0]?.message?.content ?? '';
      const latencyMs = Date.now() - startTime;

      // 添加 assistant 回复到历史
      history.push({ role: 'assistant', content: assistantMessage });

      return {
        text: assistantMessage,
        model: data.model,
        usage: {
          promptTokens: data.usage?.prompt_tokens ?? 0,
          completionTokens: data.usage?.completion_tokens ?? 0,
          totalTokens: data.usage?.total_tokens ?? 0,
        },
        latencyMs,
      };
    } finally {
      clearTimeout(timeout);
    }
  }

  /**
   * 清除会话历史
   */
  clearHistory(sessionId: string): void {
    this.conversationHistory.delete(sessionId);
  }

  /**
   * 清除所有会话
   */
  clearAllHistory(): void {
    this.conversationHistory.clear();
  }

  /**
   * 获取会话历史长度
   */
  getHistoryLength(sessionId: string): number {
    return this.conversationHistory.get(sessionId)?.length ?? 0;
  }
}
