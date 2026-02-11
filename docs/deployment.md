# 部署指南

## 开发环境

### 前置条件

- Python 3.11+
- Node.js 20+
- FFmpeg (`apt install ffmpeg` / `brew install ffmpeg`)
- CUDA Toolkit 12.x（可选，GPU 加速）

### 方式一：手动启动

#### 1. Speech Core Service

```bash
cd speech-core

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安装依赖
pip install -e ".[dev]"

# 首次运行下载模型
python -m speech_core.server
```

#### 2. Gateway 插件

```bash
# Speech Core RPC 客户端
cd gateway-plugins/speech-core
npm install
npm run build

# Discord Voice 适配器
cd ../discord-voice
npm install
npm run build
```

### 方式二：Docker Compose

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f speech-core

# 停止
docker-compose down
```

## 生产部署

### 系统要求

| 组件 | 最低配置 | 推荐配置 |
|------|----------|----------|
| CPU | 4 核 | 8 核 |
| 内存 | 8 GB | 16 GB |
| GPU | 无 | NVIDIA RTX 3060+ (6GB VRAM) |
| 磁盘 | 10 GB | 20 GB |

### GPU 配置

#### NVIDIA GPU (CUDA)

```bash
# 检查 CUDA 可用性
python -c "import torch; print(torch.cuda.is_available())"

# 设置环境变量
export STT_DEVICE=cuda
export STT_COMPUTE_TYPE=float16
```

#### CPU 模式

```bash
export STT_DEVICE=cpu
export STT_COMPUTE_TYPE=int8
```

### WSL2 GPU 加速

```bash
# 确认 NVIDIA 驱动已安装（Windows 端）
nvidia-smi

# WSL2 中检查
nvidia-smi  # 应该能看到 GPU

# 安装 CUDA Toolkit（WSL2 版本）
# https://developer.nvidia.com/cuda-downloads?target_os=Linux&target_arch=x86_64&Distribution=WSL-Ubuntu
```

### 健康检查

```bash
# 使用 wscat 测试
wscat -c ws://localhost:9001/speech -x '{"jsonrpc":"2.0","id":"1","method":"speech.status","params":{}}'
```

### 环境变量

复制 `.env.example` 为 `.env` 并配置：

```bash
cp .env.example .env
# 编辑 .env 配置各项参数
```

详见 [.env.example](../.env.example) 中的所有配置项说明。

## 监控

### 日志

```bash
# 调整日志级别
export LOG_LEVEL=DEBUG  # DEBUG / INFO / WARNING / ERROR
```

### 性能指标

Speech Core 在每个 RPC 响应中包含 `processingTimeMs` 字段，
可用于监控各引擎的处理延迟。

建议监控：
- STT 处理延迟 P50/P95
- TTS 处理延迟 P50/P95
- WebSocket 连接数
- GPU 内存使用率
