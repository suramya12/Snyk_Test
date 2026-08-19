#!/usr/bin/env python3
"""
Image Compression CLI

Compress images to target file size while maintaining >=95% quality (SSIM).
Supports standard (AVIF/WebP/JPEG) and neural (NCI3) compression modes.

Examples:
    # Standard compression to target size
    python compress.py input.jpg -o output.webp --target-size 3MB

    # Compress with specific ratio
    python compress.py input.png --ratio 10 --format webp

    # Neural compression
    python compress.py input.png -o output.nci3 --mode neural --quality 6

    # Neural compression with adaptive quality and overlap
    python compress.py input.png -o output.nci3 --mode neural --quality 6 --quality-mode adaptive --overlap 64

    # Decode neural compressed file
    python compress.py compressed.nci3 --decode -o output.png

    # Batch compress folder
    python compress.py ./images/ -o ./compressed/ --target-size 1MB
"""

import argparse
import sys
from pathlib import Path

from src.compressor import ImageCompressor
from src.quality import QualityAnalyzer
from src.utils import format_size, is_supported_image


def do_neural_compress(args):
    """Handle neural compression mode."""
    from src.neural_compressor import NeuralCompressor

    input_path = Path(args.input)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}.nci3"

    compressor = NeuralCompressor(
        quality=args.quality,
        model_name=args.model,
        tile_size=args.tile_size,
        overlap=args.overlap,
        quality_mode=args.quality_mode,
        verbose=not args.quiet,
    )

    result = compressor.compress(input_path, output_path)

    if result.success:
        print(f"Compressed: {result.output_path}")
        print(f"  Ratio: {result.compression_ratio:.1f}:1")
        print(f"  Size: {format_size(result.original_size)} -> {format_size(result.compressed_size)}")
    else:
        print(f"Compression failed: {result.message}")
        sys.exit(1)

    if args.compare and result.success:
        analyzer = QualityAnalyzer()
        # Decompress to temp file for comparison
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            dec_result = compressor.decompress(result.output_path, tmp_path)
            if dec_result.success:
                analyzer.print_comparison(input_path, tmp_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()


def do_decode(args):
    """Handle neural decompression."""
    from src.neural_compressor import NeuralCompressor

    input_path = Path(args.input)
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_decoded.png"

    compressor = NeuralCompressor(
        verbose=not args.quiet,
        use_onnx=bool(args.onnx_model),
        onnx_model_dir=args.onnx_model,
    )

    result = compressor.decompress(input_path, output_path)

    if result.success:
        print(f"Decoded: {result.output_path}")
    else:
        print(f"Decoding failed: {result.message}")
        sys.exit(1)


def do_standard_compress(args):
    """Handle standard compression mode."""
    input_path = Path(args.input)

    # Normalize format
    fmt = args.format
    if fmt == 'jpg':
        fmt = 'jpeg'

    compressor = ImageCompressor(
        min_ssim=args.min_quality,
        preferred_format=fmt,
        verbose=not args.quiet
    )

    if input_path.is_file():
        if not is_supported_image(input_path):
            print(f"Error: '{input_path}' is not a supported image format")
            sys.exit(1)

        if args.output:
            output_path = Path(args.output)
        else:
            output_path = input_path.parent / f"{input_path.stem}_compressed"
            if fmt:
                ext_map = {'avif': '.avif', 'webp': '.webp', 'jpeg': '.jpg'}
                output_path = output_path.with_suffix(ext_map.get(fmt, '.webp'))
            else:
                output_path = output_path.with_suffix('.webp')

        result = compressor.compress_to_size(
            input_path,
            output_path,
            target_size_str=args.target_size,
            target_ratio=args.ratio or 10.0
        )

        if args.compare and result.success:
            analyzer = QualityAnalyzer()
            analyzer.print_comparison(input_path, result.output_path)

        sys.exit(0 if result.success else 1)

    elif input_path.is_dir():
        if args.output:
            output_dir = Path(args.output)
        else:
            output_dir = input_path.parent / f"{input_path.name}_compressed"

        results = compressor.batch_compress(
            input_path,
            output_dir,
            target_size_mb=float(args.target_size.rstrip('MBmb')) if args.target_size else None,
            target_ratio=args.ratio or 10.0
        )

        success_count = sum(1 for r in results if r.success)
        total_original = sum(r.original_size for r in results)
        total_compressed = sum(r.compressed_size for r in results)

        print(f"\n{'='*60}")
        print(f"BATCH COMPRESSION COMPLETE")
        print(f"{'='*60}")
        print(f"Successful: {success_count}/{len(results)} images")
        print(f"Total size: {format_size(total_original)} -> {format_size(total_compressed)}")
        if total_compressed > 0:
            print(f"Overall ratio: {total_original / total_compressed:.1f}:1")
        print(f"{'='*60}")

        sys.exit(0 if success_count == len(results) else 1)

    else:
        print(f"Error: '{input_path}' is not a valid file or directory")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Compress images with quality guarantee (SSIM >= 0.95)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.jpg -o output.webp --target-size 3MB
  %(prog)s input.png --ratio 10 --format avif
  %(prog)s input.png -o output.nci3 --mode neural --quality 6
  %(prog)s input.png -o output.nci3 --mode neural --quality-mode adaptive
  %(prog)s compressed.nci3 --decode -o output.png
  %(prog)s compressed.nci3 --decode --onnx-model ./onnx_models/ -o output.png
        """
    )

    parser.add_argument(
        'input',
        type=str,
        help='Input image file or directory (or .nci2/.nci3 file with --decode)'
    )

    parser.add_argument(
        '-o', '--output',
        type=str,
        default=None,
        help='Output file or directory'
    )

    # Mode selection
    parser.add_argument(
        '--mode',
        type=str,
        choices=['standard', 'neural'],
        default='standard',
        help='Compression mode: standard (AVIF/WebP/JPEG) or neural (NCI3) (default: standard)'
    )

    parser.add_argument(
        '--decode',
        action='store_true',
        help='Decode a compressed .nci2/.nci3 file instead of compressing'
    )

    # Standard compression options
    parser.add_argument(
        '--target-size',
        type=str,
        default=None,
        help='Target file size (e.g., "3MB", "500KB")'
    )

    parser.add_argument(
        '--ratio',
        type=float,
        default=None,
        help='Target compression ratio (e.g., 10 for 10:1)'
    )

    parser.add_argument(
        '--format',
        type=str,
        choices=['avif', 'webp', 'jpeg', 'jpg'],
        default=None,
        help='Output format for standard mode (default: auto-select best)'
    )

    parser.add_argument(
        '--min-quality',
        type=float,
        default=0.95,
        help='Minimum SSIM quality threshold (default: 0.95)'
    )

    # Neural compression options
    parser.add_argument(
        '--quality',
        type=int,
        default=6,
        help='Neural compression quality level (1-8, default: 6)'
    )

    parser.add_argument(
        '--quality-mode',
        type=str,
        choices=['fixed', 'adaptive'],
        default='fixed',
        help='Quality mode: fixed (uniform) or adaptive (per-tile) (default: fixed)'
    )

    parser.add_argument(
        '--model',
        type=str,
        choices=['elic', 'mbt2018_mean', 'cheng2020_anchor'],
        default='elic',
        help='Neural compression model (default: elic)'
    )

    parser.add_argument(
        '--tile-size',
        type=int,
        default=1024,
        help='Tile size for neural compression (default: 1024)'
    )

    parser.add_argument(
        '--overlap',
        type=int,
        default=64,
        help='Tile overlap in pixels for neural compression (default: 64, 0=no overlap)'
    )

    parser.add_argument(
        '--onnx-model',
        type=str,
        default=None,
        help='Path to ONNX model directory for decoding'
    )

    # General options
    parser.add_argument(
        '--compare',
        action='store_true',
        help='Show detailed quality comparison after compression'
    )

    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Suppress progress output'
    )

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Error: Input path '{input_path}' does not exist")
        sys.exit(1)

    # Route to appropriate handler
    if args.decode:
        do_decode(args)
    elif args.mode == 'neural':
        if not input_path.is_file():
            print("Error: Neural compression requires a single input file")
            sys.exit(1)
        do_neural_compress(args)
    else:
        do_standard_compress(args)


if __name__ == '__main__':
    main()
