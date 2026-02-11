# API 参考

## Speech Core RPC API

**协议**: JSON-RPC 2.0 over WebSocket  
**地址**: `ws://localhost:9001/speech`

---

## speech.stt - 语音转文字

### 请求

```json
{
  "jsonrpc": "2.0",
  "id": "stt-001",
  "method": "speech.stt",
  "params": {
    "audio": {
      "format": "pcm_s16le",
      "sampleRate": 48000,
      "channels": 1,
      "data": "<base64 encoded audio>"
    },
    "options": {
      "language": "auto",
      "model": "base",
      "vadEnabled": true,
      "vadThreshold": 0.5
    },
    "stream": false
  }
}
```

### 参数说明

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| audio.format | string | ✅ | - | 音频格式: `pcm_s16le`, `opus`, `mp3` |
| audio.sampleRate | number | ✅ | - | 采样率 (Hz) |
| audio.channels | number | ✅ | - | 声道数 |
| audio.data | string | ✅ | - | Base64 编码音频数据 |
| options.language | string | ❌ | `"auto"` | 语言代码或 `"auto"` 自动检测 |
| options.model | string | ❌ | `"base"` | 模型大小: tiny/base/small/medium/large-v3 |
| options.vadEnabled | boolean | ❌ | `true` | 启用 VAD 过滤 |
| options.vadThreshold | number | ❌ | `0.5` | VAD 阈值 (0-1) |

### 响应

```json
{
  "jsonrpc": "2.0",
  "id": "stt-001",
  "result": {
    "text": "你好，今天天气怎么样？",
    "language": "zh",
    "confidence": 0.95,
    "segments": [
      { "start": 0.0, "end": 1.2, "text": "你好，" },
      { "start": 1.2, "end": 2.5, "text": "今天天气怎么样？" }
    ],
    "processingTimeMs": 450
  }
}
```

---

## speech.tts - 文字转语音

### 请求

```json
{
  "jsonrpc": "2.0",
  "id": "tts-001",
  "method": "speech.tts",
  "params": {
    "text": "今天天气很好，适合出门散步。",
    "options": {
      "voice": "zh_CN-huayan-medium",
      "speed": 1.0,
      "pitch": 1.0,
      "provider": "piper"
    },
    "stream": false
  }
}
```

### 参数说明

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| text | string | ✅ | - | 要合成的文本 |
| options.voice | string | ❌ | `"zh_CN-huayan-medium"` | 语音名称 |
| options.speed | number | ❌ | `1.0` | 语速 (0.5-2.0) |
| options.pitch | number | ❌ | `1.0` | 音调 (0.5-2.0) |
| options.provider | string | ❌ | `"piper"` | TTS 引擎: piper/elevenlabs |
| stream | boolean | ❌ | `false` | 是否流式返回 |

### 响应（非流式）

```json
{
  "jsonrpc": "2.0",
  "id": "tts-001",
  "result": {
    "audio": "<base64 encoded audio>",
    "format": "pcm_s16le",
    "sampleRate": 22050,
    "channels": 1,
    "durationMs": 3200,
    "processingTimeMs": 350
  }
}
```

### 响应（流式）

```json
{
  "jsonrpc": "2.0",
  "id": "tts-001",
  "result": {
    "chunks": [
      {
        "type": "chunk",
        "index": 0,
        "audio": "<base64 encoded audio>",
        "durationMs": 1500,
        "final": false
      },
      {
        "type": "chunk",
        "index": 1,
        "audio": "<base64 encoded audio>",
        "durationMs": 1700,
        "final": true
      }
    ]
  }
}
```

---

## speech.status - 服务状态

### 请求

```json
{
  "jsonrpc": "2.0",
  "id": "status-001",
  "method": "speech.status",
  "params": {}
}
```

### 响应

```json
{
  "jsonrpc": "2.0",
  "id": "status-001",
  "result": {
    "status": "healthy",
    "stt_engine": "faster-whisper",
    "tts_engine": "piper",
    "vad_loaded": true,
    "gpu_available": true,
    "uptime_seconds": 3600.5
  }
}
```

---

## speech.models - 可用模型

### 请求

```json
{
  "jsonrpc": "2.0",
  "id": "models-001",
  "method": "speech.models",
  "params": {}
}
```

### 响应

```json
{
  "jsonrpc": "2.0",
  "id": "models-001",
  "result": {
    "stt": {
      "engine": "faster-whisper",
      "model": "base",
      "available": ["tiny", "base", "small", "medium", "large-v3"]
    },
    "tts": {
      "engine": "piper",
      "voice": "zh_CN-huayan-medium"
    },
    "vad": {
      "engine": "silero",
      "loaded": true
    }
  }
}
```

---

## 事件协议

### speech.started - 用户开始说话

```json
{
  "event": "speech.started",
  "userId": "123456789",
  "channelId": "987654321",
  "timestamp": 1707552000000
}
```

### speech.ended - 用户停止说话

```json
{
  "event": "speech.ended",
  "userId": "123456789",
  "channelId": "987654321",
  "durationMs": 3500,
  "timestamp": 1707552003500
}
```

### barge_in - 打断请求

```json
{
  "event": "barge_in",
  "userId": "123456789",
  "channelId": "987654321",
  "timestamp": 1707552002000
}
```

---

## 错误码

| 代码 | 含义 |
|------|------|
| -32700 | 解析错误（无效 JSON） |
| -32600 | 无效请求 |
| -32601 | 方法不存在 |
| -32602 | 无效参数 |
| -32603 | 内部错误 |
