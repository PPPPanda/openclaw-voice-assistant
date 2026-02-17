/**
 * LLM Client 单元测试
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { LLMClient, LLMConfig } from '../src/llm';

// Mock fetch
const mockFetch = vi.fn();
global.fetch = mockFetch as unknown as typeof fetch;

const defaultConfig: LLMConfig = {
  apiEndpoint: 'https://api.example.com/v1',
  apiKey: 'test-key',
  model: 'test-model',
  maxTokens: 256,
  temperature: 0.7,
  timeoutMs: 5000,
};

describe('LLMClient', () => {
  let client: LLMClient;

  beforeEach(() => {
    client = new LLMClient(defaultConfig);
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('should send chat request with correct format', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        choices: [{ message: { role: 'assistant', content: 'Hello!' } }],
        model: 'test-model',
        usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
      }),
    });

    const result = await client.chat('Hi', 'session-1');

    expect(result.text).toBe('Hello!');
    expect(result.model).toBe('test-model');
    expect(result.usage.totalTokens).toBe(15);
    expect(result.latencyMs).toBeGreaterThanOrEqual(0);

    // Verify fetch was called correctly
    expect(mockFetch).toHaveBeenCalledOnce();
    const [url, options] = mockFetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/v1/chat/completions');
    expect(options.method).toBe('POST');
    expect(options.headers['Authorization']).toBe('Bearer test-key');

    const body = JSON.parse(options.body);
    expect(body.model).toBe('test-model');
    expect(body.messages).toHaveLength(2); // system + user
    expect(body.messages[0].role).toBe('system');
    expect(body.messages[1]).toEqual({ role: 'user', content: 'Hi' });
  });

  it('should maintain conversation history per session', async () => {
    // First message
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        choices: [{ message: { role: 'assistant', content: 'Hello!' } }],
        model: 'test-model',
      }),
    });
    await client.chat('Hi', 'session-1');

    // Second message
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        choices: [{ message: { role: 'assistant', content: 'Sure!' } }],
        model: 'test-model',
      }),
    });
    await client.chat('Tell me a joke', 'session-1');

    const body = JSON.parse(mockFetch.mock.calls[1][1].body);
    expect(body.messages).toHaveLength(4); // system + user1 + assistant1 + user2
    expect(body.messages[1]).toEqual({ role: 'user', content: 'Hi' });
    expect(body.messages[2]).toEqual({ role: 'assistant', content: 'Hello!' });
    expect(body.messages[3]).toEqual({ role: 'user', content: 'Tell me a joke' });
  });

  it('should isolate sessions', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        choices: [{ message: { role: 'assistant', content: 'OK' } }],
        model: 'test-model',
      }),
    });

    await client.chat('Message A', 'session-a');
    await client.chat('Message B', 'session-b');

    // Session B should only have system + its own message
    const bodyB = JSON.parse(mockFetch.mock.calls[1][1].body);
    expect(bodyB.messages).toHaveLength(2); // system + user
    expect(bodyB.messages[1].content).toBe('Message B');
  });

  it('should throw on API error', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 429,
      text: async () => 'Rate limited',
    });

    await expect(client.chat('Hi', 'session-1')).rejects.toThrow('LLM API error 429');
  });

  it('should clear history', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        choices: [{ message: { role: 'assistant', content: 'OK' } }],
        model: 'test-model',
      }),
    });

    await client.chat('Hi', 'session-1');
    expect(client.getHistoryLength('session-1')).toBe(3); // system + user + assistant

    client.clearHistory('session-1');
    expect(client.getHistoryLength('session-1')).toBe(0);
  });

  it('should trim history when too long', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        choices: [{ message: { role: 'assistant', content: 'OK' } }],
        model: 'test-model',
      }),
    });

    // Send 25 messages to exceed the 21-message limit
    for (let i = 0; i < 25; i++) {
      await client.chat(`Message ${i}`, 'session-1');
    }

    // History should be trimmed (system + recent messages, ≤ 22)
    // After 25 chats: each adds user+assistant (2), plus system = 51 total
    // Trimming keeps system + 20 most recent = 21, then adds user+assistant = 23
    // The trim happens BEFORE sending, so final stored length may be 21+2=23 or similar
    expect(client.getHistoryLength('session-1')).toBeLessThanOrEqual(23);
  });
});
