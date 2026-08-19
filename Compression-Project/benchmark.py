#!/usr/bin/env python3
"""
Comprehensive Compression Benchmark

Compares NCI3 neural compression vs JPEG-XL, AVIF, and PNG
across a set of test images.
"""

import os
import sys
import json
import time
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
import numpy as np
from PIL import Image

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from src.neural_compressor import NeuralCompressor
from src.quality import QualityAnalyzer


@dataclass
class CompressionResult:
    """Result of compressing a single image with one format."""
    format_name: str
    original_size: int
    compressed_size: int
    compression_ratio: float
    compression_time: float
    decompression_time: float = 0.0
    ssim: float = 0.0
    psnr: float = 0.0
    success: bool = True
    error: str = ""


@dataclass
class ImageBenchmark:
    """Benchmark results for a single image."""
    image_name: str
    original_path: str
    original_size: int
    width: int
    height: int
    results: Dict[str, CompressionResult] = field(default_factory=dict)


class CompressionBenchmark:
    """Benchmark suite for comparing compression formats."""
    
    FORMATS = ["nci3", "jxl_lossless", "avif_lossless", "png_optimized"]
    
    def __init__(
        self,
        input_dir: str,
        output_dir: str,
        verbose: bool = True,
        quality: int = 6,
        max_images: Optional[int] = None
    ):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.verbose = verbose
        self.quality = quality
        self.max_images = max_images
        self.analyzer = QualityAnalyzer()
        self.results: List[ImageBenchmark] = []
        
        # Create output directories
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for fmt in self.FORMATS:
            (self.output_dir / fmt).mkdir(exist_ok=True)
        (self.output_dir / "png_baseline").mkdir(exist_ok=True)
    
    def _log(self, msg: str):
        if self.verbose:
            print(msg)
    
    def _get_image_files(self) -> List[Path]:
        """Get list of image files to benchmark."""
        extensions = {'.arw', '.nef', '.rw2', '.cr2', '.dng', '.tif', '.tiff', '.jpg', '.jpeg', '.png'}
        files = []
        for f in self.input_dir.iterdir():
            if f.suffix.lower() in extensions:
                files.append(f)
        files.sort(key=lambda x: x.name)
        if self.max_images:
            files = files[:self.max_images]
        return files
    
    def _convert_to_png(self, raw_path: Path, output_path: Path) -> bool:
        """Convert RAW/image to PNG baseline."""
        try:
            # Try rawpy for RAW files
            if raw_path.suffix.lower() in {'.arw', '.nef', '.rw2', '.cr2', '.dng'}:
                try:
                    import rawpy
                    with rawpy.imread(str(raw_path)) as raw:
                        rgb = raw.postprocess()
                    Image.fromarray(rgb).save(output_path)
                    return True
                except ImportError:
                    # Fallback: try dcraw via subprocess
                    pass
            
            # For other formats, use PIL
            img = Image.open(raw_path).convert('RGB')
            img.save(output_path)
            return True
        except Exception as e:
            self._log(f"  Error converting {raw_path.name}: {e}")
            return False
    
    def _compress_nci3(self, png_path: Path, output_path: Path) -> CompressionResult:
        """Compress with NCI3 neural codec."""
        try:
            # Use mbt2018_mean for stability (ELIC may not have pretrained weights)
            compressor = NeuralCompressor(
                quality=self.quality,
                model_name="mbt2018_mean",
                overlap=64,
                verbose=False
            )
            
            start = time.time()
            result = compressor.compress(png_path, output_path)
            compress_time = time.time() - start
            
            if not result.success:
                return CompressionResult(
                    format_name="nci3",
                    original_size=os.path.getsize(png_path),
                    compressed_size=0,
                    compression_ratio=0,
                    compression_time=compress_time,
                    success=False,
                    error=result.message
                )
            
            # Decompress and measure quality
            decoded_path = output_path.with_suffix('.decoded.png')
            start = time.time()
            dec_result = compressor.decompress(output_path, decoded_path)
            decompress_time = time.time() - start
            
            # Calculate SSIM
            ssim = 0.0
            psnr = 0.0
            if dec_result.success and decoded_path.exists():
                try:
                    metrics = self.analyzer.compare_images(png_path, decoded_path)
                    ssim = metrics['ssim']
                    psnr = metrics['psnr']
                except:
                    pass
                decoded_path.unlink(missing_ok=True)
            
            return CompressionResult(
                format_name="nci3",
                original_size=os.path.getsize(png_path),
                compressed_size=result.compressed_size,
                compression_ratio=result.compression_ratio,
                compression_time=compress_time,
                decompression_time=decompress_time,
                ssim=ssim,
                psnr=psnr,
                success=True
            )
        except Exception as e:
            return CompressionResult(
                format_name="nci3",
                original_size=os.path.getsize(png_path) if png_path.exists() else 0,
                compressed_size=0,
                compression_ratio=0,
                compression_time=0,
                success=False,
                error=str(e)
            )
    
    def _compress_jxl_lossless(self, png_path: Path, output_path: Path) -> CompressionResult:
        """Compress with JPEG XL lossless."""
        try:
            original_size = os.path.getsize(png_path)
            
            start = time.time()
            subprocess.run(
                ["cjxl", str(png_path), str(output_path), "-d", "0", "-e", "7"],
                check=True,
                capture_output=True
            )
            compress_time = time.time() - start
            
            compressed_size = os.path.getsize(output_path)
            
            # Decompress and measure
            decoded_path = output_path.with_suffix('.decoded.png')
            start = time.time()
            subprocess.run(
                ["djxl", str(output_path), str(decoded_path)],
                check=True,
                capture_output=True
            )
            decompress_time = time.time() - start
            
            # SSIM (should be 1.0 for lossless)
            ssim = 1.0
            psnr = float('inf')
            decoded_path.unlink(missing_ok=True)
            
            return CompressionResult(
                format_name="jxl_lossless",
                original_size=original_size,
                compressed_size=compressed_size,
                compression_ratio=original_size / compressed_size if compressed_size > 0 else 0,
                compression_time=compress_time,
                decompression_time=decompress_time,
                ssim=ssim,
                psnr=psnr,
                success=True
            )
        except Exception as e:
            return CompressionResult(
                format_name="jxl_lossless",
                original_size=os.path.getsize(png_path) if png_path.exists() else 0,
                compressed_size=0,
                compression_ratio=0,
                compression_time=0,
                success=False,
                error=str(e)
            )
    
    def _compress_avif_lossless(self, png_path: Path, output_path: Path) -> CompressionResult:
        """Compress with AVIF lossless."""
        try:
            original_size = os.path.getsize(png_path)
            
            start = time.time()
            subprocess.run(
                ["avifenc", str(png_path), str(output_path), "-l", "-s", "6"],
                check=True,
                capture_output=True
            )
            compress_time = time.time() - start
            
            compressed_size = os.path.getsize(output_path)
            
            # Decompress
            decoded_path = output_path.with_suffix('.decoded.png')
            start = time.time()
            subprocess.run(
                ["avifdec", str(output_path), str(decoded_path)],
                check=True,
                capture_output=True
            )
            decompress_time = time.time() - start
            
            ssim = 1.0
            psnr = float('inf')
            decoded_path.unlink(missing_ok=True)
            
            return CompressionResult(
                format_name="avif_lossless",
                original_size=original_size,
                compressed_size=compressed_size,
                compression_ratio=original_size / compressed_size if compressed_size > 0 else 0,
                compression_time=compress_time,
                decompression_time=decompress_time,
                ssim=ssim,
                psnr=psnr,
                success=True
            )
        except Exception as e:
            return CompressionResult(
                format_name="avif_lossless",
                original_size=os.path.getsize(png_path) if png_path.exists() else 0,
                compressed_size=0,
                compression_ratio=0,
                compression_time=0,
                success=False,
                error=str(e)
            )
    
    def _compress_png_optimized(self, png_path: Path, output_path: Path) -> CompressionResult:
        """Optimize PNG with maximum compression."""
        try:
            original_size = os.path.getsize(png_path)
            
            start = time.time()
            # First copy to output
            shutil.copy(png_path, output_path)
            
            # Then optimize with PIL with maximum compression
            img = Image.open(output_path)
            img.save(output_path, optimize=True, compress_level=9)
            compress_time = time.time() - start
            
            compressed_size = os.path.getsize(output_path)
            
            return CompressionResult(
                format_name="png_optimized",
                original_size=original_size,
                compressed_size=compressed_size,
                compression_ratio=original_size / compressed_size if compressed_size > 0 else 0,
                compression_time=compress_time,
                decompression_time=0,
                ssim=1.0,
                psnr=float('inf'),
                success=True
            )
        except Exception as e:
            return CompressionResult(
                format_name="png_optimized",
                original_size=os.path.getsize(png_path) if png_path.exists() else 0,
                compressed_size=0,
                compression_ratio=0,
                compression_time=0,
                success=False,
                error=str(e)
            )
    
    def run(self) -> List[ImageBenchmark]:
        """Run benchmark on all images."""
        files = self._get_image_files()
        total = len(files)
        
        self._log(f"\n{'='*70}")
        self._log(f"COMPRESSION BENCHMARK")
        self._log(f"{'='*70}")
        self._log(f"Input: {self.input_dir}")
        self._log(f"Output: {self.output_dir}")
        self._log(f"Images: {total}")
        self._log(f"Formats: {', '.join(self.FORMATS)}")
        self._log(f"{'='*70}\n")
        
        for idx, raw_path in enumerate(files):
            self._log(f"\n[{idx+1}/{total}] {raw_path.name}")
            
            # Convert to PNG baseline
            png_path = self.output_dir / "png_baseline" / (raw_path.stem + ".png")
            if not png_path.exists():
                self._log(f"  Converting to PNG...")
                if not self._convert_to_png(raw_path, png_path):
                    continue
            
            # Get image info
            try:
                img = Image.open(png_path)
                width, height = img.size
                img.close()
            except:
                width, height = 0, 0
            
            benchmark = ImageBenchmark(
                image_name=raw_path.name,
                original_path=str(raw_path),
                original_size=os.path.getsize(raw_path),
                width=width,
                height=height
            )
            
            # Compress with each format
            for fmt in self.FORMATS:
                if fmt == "nci3":
                    output_path = self.output_dir / fmt / (raw_path.stem + ".nci3")
                    result = self._compress_nci3(png_path, output_path)
                elif fmt == "jxl_lossless":
                    output_path = self.output_dir / fmt / (raw_path.stem + ".jxl")
                    result = self._compress_jxl_lossless(png_path, output_path)
                elif fmt == "avif_lossless":
                    output_path = self.output_dir / fmt / (raw_path.stem + ".avif")
                    result = self._compress_avif_lossless(png_path, output_path)
                elif fmt == "png_optimized":
                    output_path = self.output_dir / fmt / (raw_path.stem + ".png")
                    result = self._compress_png_optimized(png_path, output_path)
                else:
                    continue
                
                benchmark.results[fmt] = result
                
                if result.success:
                    self._log(f"  {fmt}: {result.compressed_size/(1024*1024):.2f} MB "
                             f"({result.compression_ratio:.1f}:1, {result.compression_time:.1f}s)")
                else:
                    self._log(f"  {fmt}: FAILED - {result.error}")
            
            self.results.append(benchmark)
        
        return self.results
    
    def generate_report(self, report_path: Path) -> str:
        """Generate a markdown report with comparison results."""
        if not self.results:
            return "No results to report."
        
        lines = []
        lines.append("# Compression Benchmark Report")
        lines.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # Summary statistics
        lines.append("## Summary Statistics\n")
        
        stats = {fmt: {"sizes": [], "ratios": [], "times": [], "ssim": []} 
                 for fmt in self.FORMATS}
        
        total_original = 0
        for bm in self.results:
            for fmt, res in bm.results.items():
                if res.success:
                    stats[fmt]["sizes"].append(res.compressed_size)
                    stats[fmt]["ratios"].append(res.compression_ratio)
                    stats[fmt]["times"].append(res.compression_time)
                    if res.ssim > 0:
                        stats[fmt]["ssim"].append(res.ssim)
            total_original += bm.original_size
        
        # Summary table
        lines.append("| Format | Avg Size | Avg Ratio | Avg Time | SSIM | Total Size |")
        lines.append("|--------|----------|-----------|----------|------|------------|")
        
        for fmt in self.FORMATS:
            s = stats[fmt]
            if s["sizes"]:
                avg_size = np.mean(s["sizes"]) / (1024*1024)
                avg_ratio = np.mean(s["ratios"])
                avg_time = np.mean(s["times"])
                avg_ssim = np.mean(s["ssim"]) if s["ssim"] else 0.0
                total_size = sum(s["sizes"]) / (1024*1024*1024)
                lines.append(f"| {fmt} | {avg_size:.2f} MB | {avg_ratio:.2f}:1 | "
                            f"{avg_time:.1f}s | {avg_ssim:.4f} | {total_size:.2f} GB |")
        
        lines.append(f"\n**Original Total**: {total_original/(1024*1024*1024):.2f} GB")
        lines.append(f"**Images Processed**: {len(self.results)}\n")
        
        # Per-image results
        lines.append("## Per-Image Results\n")
        lines.append("| Image | Resolution | NCI3 | JXL | AVIF | PNG |")
        lines.append("|-------|------------|------|-----|------|-----|")
        
        for bm in self.results:
            row = [bm.image_name[:30], f"{bm.width}x{bm.height}"]
            for fmt in self.FORMATS:
                if fmt in bm.results and bm.results[fmt].success:
                    size_mb = bm.results[fmt].compressed_size / (1024*1024)
                    row.append(f"{size_mb:.1f} MB")
                else:
                    row.append("FAIL")
            lines.append("| " + " | ".join(row) + " |")
        
        report_content = "\n".join(lines)
        
        # Save report
        with open(report_path, 'w') as f:
            f.write(report_content)
        
        return report_content
    
    def save_json(self, json_path: Path):
        """Save results as JSON for further analysis."""
        data = {
            "timestamp": datetime.now().isoformat(),
            "input_dir": str(self.input_dir),
            "output_dir": str(self.output_dir),
            "num_images": len(self.results),
            "formats": self.FORMATS,
            "results": []
        }
        
        for bm in self.results:
            bm_data = {
                "image_name": bm.image_name,
                "original_path": bm.original_path,
                "original_size": bm.original_size,
                "width": bm.width,
                "height": bm.height,
                "results": {}
            }
            for fmt, res in bm.results.items():
                bm_data["results"][fmt] = asdict(res)
            data["results"].append(bm_data)
        
        with open(json_path, 'w') as f:
            json.dump(data, f, indent=2)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Compression Benchmark")
    parser.add_argument("input_dir", help="Directory containing test images")
    parser.add_argument("-o", "--output", default="./benchmark_output",
                        help="Output directory for compressed files")
    parser.add_argument("-n", "--max-images", type=int, default=None,
                        help="Maximum number of images to process")
    parser.add_argument("-q", "--quality", type=int, default=6,
                        help="NCI3 quality level (1-8)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress progress output")
    
    args = parser.parse_args()
    
    benchmark = CompressionBenchmark(
        input_dir=args.input_dir,
        output_dir=args.output,
        verbose=not args.quiet,
        quality=args.quality,
        max_images=args.max_images
    )
    
    results = benchmark.run()
    
    # Generate reports
    report_path = Path(args.output) / "benchmark_report.md"
    benchmark.generate_report(report_path)
    print(f"\nReport saved to: {report_path}")
    
    json_path = Path(args.output) / "benchmark_results.json"
    benchmark.save_json(json_path)
    print(f"JSON saved to: {json_path}")


if __name__ == "__main__":
    main()
