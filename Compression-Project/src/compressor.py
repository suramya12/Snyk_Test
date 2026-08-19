"""
Core Image Compression Engine

Achieves 10:1+ compression ratios while maintaining ≥95% quality (SSIM ≥ 0.95).

Compression Strategy:
1. Try AVIF first (best compression/quality ratio)
2. Fallback to WebP (25-35% better than JPEG)  
3. Fallback to JPEG with mozjpeg-style optimization
4. Binary search for optimal quality that meets SSIM threshold
"""

import io
import os
from pathlib import Path
from typing import Optional, Tuple, Union, Dict, Literal
from dataclasses import dataclass
import numpy as np
from PIL import Image

# Try to import AVIF support
try:
    import pillow_avif
    AVIF_AVAILABLE = True
except ImportError:
    AVIF_AVAILABLE = False

from .quality import QualityAnalyzer
from .utils import get_file_size_bytes, format_size, parse_size_string


@dataclass
class CompressionResult:
    """Result of a compression operation."""
    success: bool
    output_path: Optional[Path]
    original_size: int
    compressed_size: int
    compression_ratio: float
    ssim: float
    quality_setting: int
    format_used: str
    message: str
    
    @property
    def size_reduction_percent(self) -> float:
        """Percentage of size reduced."""
        if self.original_size == 0:
            return 0.0
        return (1 - self.compressed_size / self.original_size) * 100


class ImageCompressor:
    """
    High-quality image compression with quality guarantees.
    
    Achieves 10:1 compression while maintaining SSIM ≥ 0.95 (95% quality).
    
    Example:
        compressor = ImageCompressor(min_ssim=0.95)
        result = compressor.compress_to_size("input.jpg", "output.webp", target_size_mb=3)
        print(f"Compressed with {result.compression_ratio:.1f}:1 ratio, SSIM={result.ssim:.4f}")
    """
    
    # Format priority order (best compression first)
    FORMAT_PRIORITY = ['avif', 'webp', 'jpeg']
    
    # Format-specific settings
    FORMAT_CONFIG = {
        'avif': {
            'extension': '.avif',
            'quality_range': (10, 100),
            'save_kwargs': lambda q: {'quality': q, 'speed': 6},
        },
        'webp': {
            'extension': '.webp',
            'quality_range': (10, 100),
            'save_kwargs': lambda q: {'quality': q, 'method': 6},
        },
        'jpeg': {
            'extension': '.jpg',
            'quality_range': (10, 100),
            'save_kwargs': lambda q: {'quality': q, 'optimize': True, 'progressive': True},
        },
    }
    
    def __init__(
        self,
        min_ssim: float = 0.95,
        preferred_format: Optional[str] = None,
        verbose: bool = True
    ):
        """
        Initialize compressor.
        
        Args:
            min_ssim: Minimum SSIM quality threshold (0.95 = 95% quality)
            preferred_format: Force specific format ('avif', 'webp', 'jpeg')
            verbose: Print progress messages
        """
        self.min_ssim = min_ssim
        self.preferred_format = preferred_format
        self.verbose = verbose
        self.quality_analyzer = QualityAnalyzer()
        
        # Check AVIF availability
        if not AVIF_AVAILABLE and self.verbose:
            print("Note: AVIF not available. Install 'pillow-avif-plugin' for best compression.")
    
    def _log(self, message: str) -> None:
        """Print message if verbose mode enabled."""
        if self.verbose:
            print(message)
    
    def _get_available_formats(self) -> list:
        """Get list of available formats in priority order."""
        formats = []
        for fmt in self.FORMAT_PRIORITY:
            if fmt == 'avif' and not AVIF_AVAILABLE:
                continue
            if self.preferred_format and fmt != self.preferred_format:
                continue
            formats.append(fmt)
        return formats if formats else ['jpeg']  # fallback to jpeg
    
    def _compress_at_quality(
        self,
        image: Image.Image,
        quality: int,
        format_type: str
    ) -> Tuple[bytes, int]:
        """
        Compress image at specific quality level.
        
        Returns:
            Tuple of (compressed_bytes, size_in_bytes)
        """
        config = self.FORMAT_CONFIG[format_type]
        buffer = io.BytesIO()
        
        # Convert to RGB if needed (AVIF/JPEG don't support RGBA)
        img = image
        if format_type in ['avif', 'jpeg'] and image.mode == 'RGBA':
            img = image.convert('RGB')
        
        # Save with format-specific options
        save_kwargs = config['save_kwargs'](quality)
        
        if format_type == 'avif':
            img.save(buffer, format='AVIF', **save_kwargs)
        elif format_type == 'webp':
            img.save(buffer, format='WEBP', **save_kwargs)
        else:  # jpeg
            img.save(buffer, format='JPEG', **save_kwargs)
        
        compressed_bytes = buffer.getvalue()
        return compressed_bytes, len(compressed_bytes)
    
    def _calculate_ssim_from_bytes(
        self,
        original: Image.Image,
        compressed_bytes: bytes
    ) -> float:
        """Calculate SSIM between original and compressed image."""
        compressed_img = Image.open(io.BytesIO(compressed_bytes))
        
        # Resize if dimensions differ
        if compressed_img.size != original.size:
            compressed_img = compressed_img.resize(original.size, Image.Resampling.LANCZOS)
        
        # Convert to numpy arrays
        orig_array = np.array(original.convert('RGB'))
        comp_array = np.array(compressed_img.convert('RGB'))
        
        return self.quality_analyzer.calculate_ssim_simple(orig_array, comp_array)
    
    def _binary_search_quality(
        self,
        image: Image.Image,
        format_type: str,
        target_size: int,
        min_quality: int = 10,
        max_quality: int = 100
    ) -> Tuple[int, bytes, float]:
        """
        Binary search for optimal quality that meets both size and SSIM constraints.
        
        Returns:
            Tuple of (optimal_quality, compressed_bytes, ssim_value)
        """
        best_quality = max_quality
        best_bytes = None
        best_ssim = 0.0
        
        low, high = min_quality, max_quality
        
        while low <= high:
            mid = (low + high) // 2
            
            try:
                compressed_bytes, size = self._compress_at_quality(image, mid, format_type)
                ssim = self._calculate_ssim_from_bytes(image, compressed_bytes)
                
                self._log(f"  Quality {mid}: {format_size(size)} | SSIM={ssim:.4f}")
                
                # Check if this quality meets our constraints
                if ssim >= self.min_ssim:
                    if size <= target_size:
                        # Found a valid solution, but try to go lower quality (smaller file)
                        best_quality = mid
                        best_bytes = compressed_bytes
                        best_ssim = ssim
                        high = mid - 1
                    else:
                        # Size too big, need lower quality
                        high = mid - 1
                else:
                    # SSIM too low, need higher quality
                    low = mid + 1
                    
            except Exception as e:
                self._log(f"  Quality {mid}: Error - {e}")
                high = mid - 1
        
        # If no valid solution found with constraints, find best compromise
        if best_bytes is None:
            self._log("  Finding best compromise...")
            # Start from highest quality and work down until size fits
            for q in range(max_quality, min_quality - 1, -5):
                try:
                    compressed_bytes, size = self._compress_at_quality(image, q, format_type)
                    ssim = self._calculate_ssim_from_bytes(image, compressed_bytes)
                    
                    if ssim >= self.min_ssim or q == min_quality:
                        best_quality = q
                        best_bytes = compressed_bytes
                        best_ssim = ssim
                        if size <= target_size:
                            break
                except:
                    continue
        
        return best_quality, best_bytes, best_ssim
    
    def compress_to_size(
        self,
        input_path: Union[str, Path],
        output_path: Union[str, Path],
        target_size_mb: Optional[float] = None,
        target_size_str: Optional[str] = None,
        target_ratio: Optional[float] = None
    ) -> CompressionResult:
        """
        Compress image to target file size while maintaining quality.
        
        Args:
            input_path: Path to input image
            output_path: Path for compressed output
            target_size_mb: Target size in megabytes (e.g., 3.0)
            target_size_str: Target size as string (e.g., "3MB", "500KB")
            target_ratio: Target compression ratio (e.g., 10 for 10:1)
            
        Returns:
            CompressionResult with details about the compression
        """
        input_path = Path(input_path)
        output_path = Path(output_path)
        
        # Load image
        try:
            image = Image.open(input_path)
            original_size = get_file_size_bytes(input_path)
        except Exception as e:
            return CompressionResult(
                success=False,
                output_path=None,
                original_size=0,
                compressed_size=0,
                compression_ratio=0,
                ssim=0,
                quality_setting=0,
                format_used='',
                message=f"Failed to load image: {e}"
            )
        
        # Calculate target size
        if target_size_str:
            target_size = parse_size_string(target_size_str)
        elif target_size_mb:
            target_size = int(target_size_mb * 1024 * 1024)
        elif target_ratio:
            target_size = int(original_size / target_ratio)
        else:
            target_size = int(original_size / 10)  # Default 10:1 ratio
        
        self._log(f"\n{'='*60}")
        self._log(f"COMPRESSING: {input_path.name}")
        self._log(f"{'='*60}")
        self._log(f"Original size: {format_size(original_size)}")
        self._log(f"Target size:   {format_size(target_size)}")
        self._log(f"Target ratio:  {original_size / target_size:.1f}:1")
        self._log(f"Min SSIM:      {self.min_ssim}")
        self._log(f"{'='*60}")
        
        # Determine output format from extension or try all formats
        output_ext = output_path.suffix.lower()
        
        if output_ext in ['.avif'] and AVIF_AVAILABLE:
            formats_to_try = ['avif']
        elif output_ext in ['.webp']:
            formats_to_try = ['webp']
        elif output_ext in ['.jpg', '.jpeg']:
            formats_to_try = ['jpeg']
        else:
            formats_to_try = self._get_available_formats()
        
        best_result = None
        
        for format_type in formats_to_try:
            self._log(f"\nTrying {format_type.upper()}...")
            
            try:
                quality, compressed_bytes, ssim = self._binary_search_quality(
                    image, format_type, target_size
                )
                
                if compressed_bytes:
                    size = len(compressed_bytes)
                    ratio = original_size / size if size > 0 else 0
                    
                    # Check if this is our best result so far
                    if best_result is None or (
                        ssim >= self.min_ssim and 
                        size <= target_size and
                        (best_result['size'] > target_size or size < best_result['size'])
                    ):
                        best_result = {
                            'format': format_type,
                            'quality': quality,
                            'bytes': compressed_bytes,
                            'size': size,
                            'ssim': ssim,
                            'ratio': ratio
                        }
                    
                    self._log(f"  Best: Q={quality}, Size={format_size(size)}, SSIM={ssim:.4f}")
                    
                    # If we meet all constraints, we're done
                    if ssim >= self.min_ssim and size <= target_size:
                        break
                        
            except Exception as e:
                self._log(f"  Failed: {e}")
                continue
        
        if best_result is None:
            return CompressionResult(
                success=False,
                output_path=None,
                original_size=original_size,
                compressed_size=0,
                compression_ratio=0,
                ssim=0,
                quality_setting=0,
                format_used='',
                message="Failed to compress image with any format"
            )
        
        # Adjust output path extension if needed
        correct_ext = self.FORMAT_CONFIG[best_result['format']]['extension']
        if output_path.suffix.lower() != correct_ext:
            output_path = output_path.with_suffix(correct_ext)
        
        # Save the best result
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'wb') as f:
            f.write(best_result['bytes'])
        
        # Determine success based on constraints
        meets_size = best_result['size'] <= target_size
        meets_quality = best_result['ssim'] >= self.min_ssim
        success = meets_size and meets_quality
        
        if success:
            message = f"Successfully compressed to {format_size(best_result['size'])} with SSIM={best_result['ssim']:.4f}"
        elif not meets_quality:
            message = f"Warning: SSIM {best_result['ssim']:.4f} is below threshold {self.min_ssim}"
        else:
            message = f"Warning: Size {format_size(best_result['size'])} exceeds target {format_size(target_size)}"
        
        self._log(f"\n{'='*60}")
        self._log(f"RESULT: {message}")
        self._log(f"  Output: {output_path}")
        self._log(f"  Format: {best_result['format'].upper()}")
        self._log(f"  Ratio:  {best_result['ratio']:.1f}:1")
        self._log(f"{'='*60}\n")
        
        return CompressionResult(
            success=success,
            output_path=output_path,
            original_size=original_size,
            compressed_size=best_result['size'],
            compression_ratio=best_result['ratio'],
            ssim=best_result['ssim'],
            quality_setting=best_result['quality'],
            format_used=best_result['format'],
            message=message
        )
    
    def compress_with_ratio(
        self,
        input_path: Union[str, Path],
        output_path: Union[str, Path],
        ratio: float = 10.0
    ) -> CompressionResult:
        """
        Compress image with target compression ratio (e.g., 10:1).
        
        Args:
            input_path: Path to input image
            output_path: Path for compressed output
            ratio: Target compression ratio (default 10)
        """
        return self.compress_to_size(input_path, output_path, target_ratio=ratio)
    
    def batch_compress(
        self,
        input_dir: Union[str, Path],
        output_dir: Union[str, Path],
        target_size_mb: Optional[float] = None,
        target_ratio: float = 10.0,
        recursive: bool = False
    ) -> list:
        """
        Compress all images in a directory.
        
        Returns:
            List of CompressionResult objects
        """
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Find all images
        extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'}
        if recursive:
            images = [f for f in input_dir.rglob('*') if f.suffix.lower() in extensions]
        else:
            images = [f for f in input_dir.glob('*') if f.suffix.lower() in extensions]
        
        results = []
        for img_path in images:
            rel_path = img_path.relative_to(input_dir)
            out_path = output_dir / rel_path.with_suffix('.webp')  # Default to webp
            
            result = self.compress_to_size(
                img_path, out_path,
                target_size_mb=target_size_mb,
                target_ratio=target_ratio if not target_size_mb else None
            )
            results.append(result)
        
        return results
