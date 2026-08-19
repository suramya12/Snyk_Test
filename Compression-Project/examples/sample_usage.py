"""
Sample usage of the Image Compression library.

Demonstrates standard, neural (NCI3), and quality analysis workflows.
Replace file paths with your own images before running.
"""

from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.compressor import ImageCompressor
from src.neural_compressor import NeuralCompressor
from src.quality import QualityAnalyzer
from src.utils import format_size


def example_standard_compression():
    """Standard compression to target size."""
    print("\n" + "=" * 60)
    print("EXAMPLE 1: Standard Compression")
    print("=" * 60)

    compressor = ImageCompressor(min_ssim=0.95)

    result = compressor.compress_to_size(
        "sample_image.jpg",
        "output_compressed.webp",
        target_size_mb=3.0,
    )

    if result.success:
        print(f"Compressed successfully!")
        print(f"  Ratio: {result.compression_ratio:.1f}:1")
        print(f"  SSIM:  {result.ssim:.4f}")
    else:
        print(f"Failed: {result.message}")


def example_format_comparison():
    """Compare compression across different formats."""
    print("\n" + "=" * 60)
    print("EXAMPLE 2: Format Comparison")
    print("=" * 60)

    input_image = "sample_image.jpg"
    formats = ["avif", "webp", "jpeg"]

    print(f"\n{'Format':<10} {'Size':<12} {'Ratio':<10} {'SSIM':<10}")
    print("-" * 45)

    for fmt in formats:
        compressor = ImageCompressor(min_ssim=0.95, preferred_format=fmt, verbose=False)
        ext = "jpg" if fmt == "jpeg" else fmt
        result = compressor.compress_to_size(
            input_image, f"output_{fmt}.{ext}", target_ratio=10.0
        )
        if result.success:
            print(
                f"{fmt.upper():<10} {format_size(result.compressed_size):<12} "
                f"{result.compression_ratio:.1f}:1{'':<5} {result.ssim:.4f}"
            )


def example_neural_compression():
    """Neural compression with NCI3 format."""
    print("\n" + "=" * 60)
    print("EXAMPLE 3: Neural Compression (NCI3)")
    print("=" * 60)

    compressor = NeuralCompressor(
        quality=6,
        model_name="mbt2018_mean",
        overlap=64,
        quality_mode="fixed",
    )

    result = compressor.compress("sample_image.png", "output_neural.nci3")

    if result.success:
        print(f"Compressed: {format_size(result.compressed_size)}")
        print(f"Ratio: {result.compression_ratio:.1f}:1")

        # Decompress and verify
        dec = compressor.decompress("output_neural.nci3", "output_decoded.png")
        if dec.success:
            print(f"Decoded: {dec.output_path}")
    else:
        print(f"Failed: {result.message}")


def example_adaptive_quality():
    """Neural compression with per-tile adaptive quality."""
    print("\n" + "=" * 60)
    print("EXAMPLE 4: Adaptive Quality Neural Compression")
    print("=" * 60)

    compressor = NeuralCompressor(
        quality=6,
        overlap=64,
        quality_mode="adaptive",
    )

    result = compressor.compress("sample_image.png", "output_adaptive.nci3")

    if result.success:
        print(f"Compressed with adaptive quality: {format_size(result.compressed_size)}")
        print(f"Ratio: {result.compression_ratio:.1f}:1")


def example_quality_analysis():
    """Analyze quality after compression."""
    print("\n" + "=" * 60)
    print("EXAMPLE 5: Quality Analysis")
    print("=" * 60)

    analyzer = QualityAnalyzer()

    metrics = analyzer.compare_images("original.jpg", "compressed.webp")

    print(f"MSE:  {metrics['mse']:.2f}")
    print(f"PSNR: {metrics['psnr']:.2f} dB")
    print(f"SSIM: {metrics['ssim']:.4f}")
    print(f"Rating: {analyzer.get_quality_rating(metrics)}")


def example_batch_processing():
    """Batch process a folder of images."""
    print("\n" + "=" * 60)
    print("EXAMPLE 6: Batch Processing")
    print("=" * 60)

    compressor = ImageCompressor(min_ssim=0.95)

    results = compressor.batch_compress(
        input_dir="./photos",
        output_dir="./photos_compressed",
        target_ratio=10.0,
    )

    success = sum(1 for r in results if r.success)
    print(f"Compressed {success}/{len(results)} images successfully")


if __name__ == "__main__":
    print("Image Compression Examples")
    print("=" * 60)
    print("Note: These examples require actual image files to run.")
    print("Replace file paths with your own images.")
    print("=" * 60)

    # Uncomment to run:
    # example_standard_compression()
    # example_format_comparison()
    # example_neural_compression()
    # example_adaptive_quality()
    # example_quality_analysis()
    # example_batch_processing()
