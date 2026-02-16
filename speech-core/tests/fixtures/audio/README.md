# Test Audio Fixtures

This directory contains test audio files for STT accuracy evaluation.

## Directory Structure

```
audio/
├── sample_001.wav
├── sample_001.json
├── sample_002.wav
├── sample_002.json
└── ...
```

## File Format Requirements

### Audio Files (.wav)

- **Format**: PCM (WAV)
- **Sample Rate**: 16,000 Hz (16kHz)
- **Channels**: Mono (1 channel)
- **Bit Depth**: 16-bit signed integer (PCM S16LE)

### Metadata Files (.json)

Each audio file must have a corresponding JSON file with the same base name.

**Example** (`sample_001.json`):

```json
{
  "reference_text": "hello world",
  "language": "en"
}
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `reference_text` | string | The expected transcription text |
| `language` | string | Language code: `en` (English) or `zh` (Chinese) |

## Creating Test Samples

### Recording Audio

Use any audio recording tool (audacity, ffmpeg, etc.) to create test audio files:

```bash
# Record from microphone
ffmpeg -f alsa -i default -ar 16000 -ac 1 -t 5 output.wav

# Convert existing audio
ffmpeg -i input.mp3 -ar 16000 -ac 1 output.wav
```

### Generating Synthetic Audio

For testing purposes, you can generate synthetic speech audio:

```python
import numpy as np
import wave

# Generate sine wave (simple test tone)
sample_rate = 16000
duration = 2.0
t = np.linspace(0, duration, int(sample_rate * duration))

# Simple "hello" sound (440Hz tone)
audio = np.sin(2 * np.pi * 440 * t) * 0.5

# Convert to 16-bit PCM
audio_int16 = (audio * 32767).astype(np.int16)

# Save as WAV
with wave.open('sample_test.wav', 'wb') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    wf.writeframes(audio_int16.tobytes())
```

## Running Evaluation

```bash
# Run accuracy evaluation
python scripts/evaluate_accuracy.py

# Use custom fixtures directory
python scripts/evaluate_accuracy.py --fixtures-dir /path/to/fixtures

# Save results to JSON
python scripts/evaluate_accuracy.py --output results.json
```

## Evaluation Metrics

- **WER (Word Error Rate)**: Measures transcription accuracy at word level
  - Lower is better (0% = perfect)
  - Formula: `WER = (Substitutions + Deletions + Insertions) / Total Words`
  
- **CER (Character Error Rate)**: Measures transcription accuracy at character level
  - Lower is better (0% = perfect)
  - Formula: `CER = (Substitutions + Deletions + Insertions) / Total Characters`

## Example Samples

### English Sample

```json
{
  "reference_text": "hello world this is a test",
  "language": "en"
}
```

### Chinese Sample

```json
{
  "reference_text": "你好世界这是一个测试",
  "language": "zh"
}
```
