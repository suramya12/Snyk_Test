# Image Compression Project

A Python image compression toolkit supporting three complementary strategies:

- **Standard compression** (AVIF / WebP / JPEG) with SSIM quality guarantees
- **Neural compression** (NCI3 format) using CompressAI learned codecs with overlapped tiling, adaptive quality, and optional ONNX inference
- **Super-resolution compression** using Real-ESRGAN AI upscaling

## Features

| Feature | Description |
|---|---|
| Smart format selection | Auto-selects AVIF > WebP > JPEG for best ratio |
| Neural codec (NCI3) | State-of-the-art learned compression via CompressAI |
| Overlapped tiling | Eliminates tile seam artifacts with linear gradient blending |
| Adaptive quality | Per-tile bitrate based on content complexity |
| ONNX export | Lightweight deployment without full PyTorch stack |
| Quality analysis | MSE, PSNR, SSIM metrics + tile seam detection |
| Batch processing | Compress entire directories in one command |
| NCI2 backward compat | Decoder auto-detects and handles legacy NCI2 files |

## Benchmark Results

Comparison of NCI3 neural compression vs lossless formats on RAW camera images:

### Summary

| Format | Avg Compression | Avg Size | Avg Time | Quality (SSIM) |
|--------|-----------------|----------|----------|----------------|
| **NCI3 (Neural)** | **47.7:1** | **3.69 MB** | **8.0s** | 99.28% |
| JPEG-XL (lossless) | 1.22:1 | 54.9 MB | 279s | 100% |
| AVIF (lossless) | 1.03:1 | 64.7 MB | 31s | 100% |
| PNG (optimized) | 1.02:1 | 64.5 MB | 24s | 100% |

**Key findings:**
- **NCI3 is 17x smaller** than lossless formats while maintaining 99.28% visual quality
- **35x faster** than JPEG-XL lossless compression
- Achieves **6:1 to 155:1 compression** depending on image content

### Per-Image Results (Sample)

| Image | Resolution | NCI3 | JXL | AVIF | PNG |
|-------|------------|------|-----|------|-----|
| DSC01658.ARW | 5496×3672 | **1.0 MB** | 19.9 MB | 25.4 MB | 26.2 MB |
| DSC06430.ARW | 9566×6374 | **5.1 MB** | 83.6 MB | 98.5 MB | 96.0 MB |
| DSC06447.ARW | 9566×6374 | **0.4 MB** | 46.4 MB | 50.8 MB | 58.4 MB |

### Run Your Own Benchmark

```bash
python benchmark.py /path/to/images -o ./benchmark_output --quality 6
```

## Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

ONNX support is optional. Uncomment the last two lines in `requirements.txt` if needed:

```
onnx>=1.14.0
onnxruntime>=1.15.0
```

## Quick Start

### Standard Compression (Python API)

```python
from src.compressor import ImageCompressor

compressor = ImageCompressor(min_ssim=0.95)

# Compress to target size
compressor.compress_to_size("input.jpg", "output.webp", target_size_mb=3)

# Compress with specific ratio
compressor.compress_with_ratio("input.png", "output.avif", ratio=10)
```

### Neural Compression (Python API)

```python
from src.neural_compressor import NeuralCompressor

compressor = NeuralCompressor(
    quality=6,                  # 1-8
    model_name="mbt2018_mean",  # or "cheng2020_anchor"
    overlap=64,                 # 0 = no overlap
    quality_mode="adaptive",    # or "fixed"
)

# Compress
compressor.compress("input.png", "output.nci3")

# Decompress (auto-detects NCI2/NCI3)
compressor.decompress("output.nci3", "decoded.png")
```

## CLI Usage

### Standard compression

```bash
# Compress to target size
python compress.py input.jpg -o output.webp --target-size 3MB

# Compress with ratio
python compress.py input.png --ratio 10 --format avif

# Batch compress a folder
python compress.py ./images/ -o ./compressed/ --target-size 1MB
```

### Neural compression

```bash
# Compress with defaults (quality=6, overlap=64, fixed quality)
python compress.py input.png -o output.nci3 --mode neural

# Adaptive quality + custom settings
python compress.py input.png -o output.nci3 --mode neural \
    --quality 6 --quality-mode adaptive --overlap 64 \
    --model mbt2018_mean --tile-size 1024

# No overlap (NCI3 format, but without blending)
python compress.py input.png -o output.nci3 --mode neural --overlap 0
```

### Decoding

```bash
# Via compress.py
python compress.py compressed.nci3 --decode -o output.png

# Via standalone decoder
python decode_script.py compressed.nci3 output.png

# With ONNX inference
python decode_script.py compressed.nci3 output.png --onnx-model ./onnx_models/
```

### Quality comparison

```bash
python compress.py input.png -o output.nci3 --mode neural --compare
```

## NCI3 File Format

The NCI3 binary format stores neural-compressed images with tile-level metadata.

**Header (32 bytes):**

```
Magic(4:"NCI3") + Width(4) + Height(4) + Quality(1) + ModelID(1) +
TileSize(4) + Overlap(2) + TilesX(4) + TilesY(4) + Flags(1) + Reserved(3)
```

- `Flags`: bit 0 = adaptive per-tile quality, bit 1 = ONNX model used

**Per-Tile Block:**

```
OrigW(2) + OrigH(2) + LatentH(2) + LatentW(2) + TileQuality(1) +
StrLen1(4) + StrLen2(4) + String1(var) + String2(var)
```

Legacy NCI2 files are auto-detected and decoded transparently.

## ONNX Export

Export CompressAI models for deployment without PyTorch:

```python
from src.onnx_export import export_model_to_onnx

export_model_to_onnx(
    model_name="mbt2018_mean",
    quality=6,
    output_dir="onnx_models/"
)
```

This creates `g_a.onnx`, `h_a.onnx`, `h_s.onnx`, `g_s.onnx`, and entropy metadata JSON.

## Project Structure

```
Compression Project/
├── compress.py              # CLI entry point (standard + neural + decode)
├── decode_script.py         # Standalone NCI2/NCI3 decoder
├── requirements.txt         # Python dependencies
├── README.md
├── .gitignore
├── src/
│   ├── __init__.py          # Package exports (v2.0.0)
│   ├── compressor.py        # Standard AVIF/WebP/JPEG compression
│   ├── neural_compressor.py # Neural compression (NCI2/NCI3)
│   ├── onnx_export.py       # ONNX export & inference engine
│   ├── sr_compressor.py     # Super-resolution compression
│   ├── quality.py           # Quality metrics (MSE, PSNR, SSIM, seam)
│   └── utils.py             # File size helpers, format detection
├── tests/
│   ├── __init__.py
│   └── test_compressor.py   # Unit tests
└── examples/
    └── sample_usage.py      # Usage examples
```

## How It Works

### Standard Compression

Binary searches for the optimal quality setting that meets the SSIM threshold at the target file size. Tries AVIF first (best ratio), then WebP, then JPEG as fallback.

### Neural Compression (NCI3)

1. **Tiling**: Splits image into overlapping tiles (default 1024px, 64px overlap)
2. **Adaptive quality** (optional): Analyzes tile complexity via 16x16 block variance, adjusts quality per-tile
3. **Encoding**: Each tile runs through CompressAI's analysis transform + entropy coding
4. **Decoding**: Entropy decode + synthesis transform per tile
5. **Blending**: Float32 canvas with linear gradient weights eliminates seam artifacts

### Super-Resolution Compression

Downscales the image 4x, stores as lossless PNG, then reconstructs with Real-ESRGAN.

## Running Tests

```bash
python -m unittest discover -s tests -v
```

## License

MIT
