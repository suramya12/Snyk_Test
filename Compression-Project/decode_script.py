
import sys
import os
import argparse
from pathlib import Path

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

try:
    from neural_compressor import NeuralCompressor
except ImportError:
    # Try importing assuming we are in src
    try:
        from src.neural_compressor import NeuralCompressor
    except ImportError:
         print("Could not import NeuralCompressor. Make sure you are in the project root.")
         sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description='Decode NCI2/NCI3 neural compressed images',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s compressed.nci2 output.png
  %(prog)s compressed.nci3 output.png
  %(prog)s compressed.nci3 output.png --onnx-model ./onnx_models/
        """
    )

    parser.add_argument(
        'input_file',
        type=str,
        help='Input compressed file (.nci2 or .nci3)'
    )

    parser.add_argument(
        'output_file',
        type=str,
        help='Output image file path'
    )

    parser.add_argument(
        '--onnx-model',
        type=str,
        default=None,
        help='Path to ONNX model directory for faster inference'
    )

    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Suppress progress output'
    )

    args = parser.parse_args()

    input_path = Path(args.input_file)
    output_path = Path(args.output_file)

    if not input_path.exists():
        print(f"Error: Input file {input_path} does not exist.")
        sys.exit(1)

    # Auto-detect format from magic bytes
    with open(input_path, 'rb') as f:
        magic = f.read(4)

    if magic not in (b'NCI2', b'NCI3'):
        print(f"Error: Unrecognized file format (magic: {magic})")
        print("Expected NCI2 or NCI3 format.")
        sys.exit(1)

    fmt_name = magic.decode('ascii')
    if not args.quiet:
        print(f"Detected format: {fmt_name}")
        print(f"Decoding {input_path} to {output_path}...")

    compressor = NeuralCompressor(
        verbose=not args.quiet,
        use_onnx=bool(args.onnx_model),
        onnx_model_dir=args.onnx_model,
    )

    try:
        result = compressor.decompress(input_path, output_path)
        if result.success:
            print("Decompression successful!")
            print(result.message)
            print(f"Output saved to: {output_path}")
        else:
            print("Decompression failed!")
            print(result.message)
            sys.exit(1)

    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
