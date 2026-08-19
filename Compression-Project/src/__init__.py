"""
Image Compression Package

Provides standard (AVIF/WebP/JPEG), neural (NCI3), and super-resolution
compression with quality analysis utilities.
"""

from .compressor import ImageCompressor
from .neural_compressor import NeuralCompressor, NeuralCompressionResult
from .sr_compressor import SuperResolutionCompressor
from .quality import QualityAnalyzer
from .utils import get_file_size_mb, format_size

__version__ = "2.0.0"
__all__ = [
    "ImageCompressor",
    "NeuralCompressor",
    "NeuralCompressionResult",
    "SuperResolutionCompressor",
    "QualityAnalyzer",
    "get_file_size_mb",
    "format_size",
]
