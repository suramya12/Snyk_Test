"""
Quality analysis utilities for comparing original and compressed images.
"""

import numpy as np
from PIL import Image
from pathlib import Path
from typing import Union, Tuple, Dict
import math


class QualityAnalyzer:
    """Analyze and compare image quality before and after compression."""
    
    @staticmethod
    def calculate_mse(original: np.ndarray, compressed: np.ndarray) -> float:
        """
        Calculate Mean Squared Error between two images.
        
        Lower MSE = more similar images.
        """
        if original.shape != compressed.shape:
            raise ValueError("Images must have the same dimensions")
        
        mse = np.mean((original.astype(float) - compressed.astype(float)) ** 2)
        return float(mse)
    
    @staticmethod
    def calculate_psnr(original: np.ndarray, compressed: np.ndarray) -> float:
        """
        Calculate Peak Signal-to-Noise Ratio (PSNR).
        
        Higher PSNR = better quality.
        - 30-40 dB: Good quality
        - 40-50 dB: Excellent quality
        - > 50 dB: Near perfect
        """
        mse = QualityAnalyzer.calculate_mse(original, compressed)
        
        if mse == 0:
            return float('inf')  # Identical images
        
        max_pixel = 255.0
        psnr = 10 * math.log10((max_pixel ** 2) / mse)
        return psnr
    
    @staticmethod
    def calculate_ssim_simple(original: np.ndarray, compressed: np.ndarray) -> float:
        """
        Calculate a simplified Structural Similarity Index (SSIM).
        
        Returns value between 0 and 1.
        - > 0.95: Excellent quality
        - 0.90-0.95: Good quality
        - 0.80-0.90: Acceptable quality
        - < 0.80: Noticeable degradation
        
        Note: This is a simplified implementation. For production use,
        consider using skimage.metrics.structural_similarity
        """
        if original.shape != compressed.shape:
            raise ValueError("Images must have the same dimensions")
        
        # Convert to float
        img1 = original.astype(float)
        img2 = compressed.astype(float)
        
        # Constants for stability
        C1 = (0.01 * 255) ** 2
        C2 = (0.03 * 255) ** 2
        
        # Calculate means
        mu1 = np.mean(img1)
        mu2 = np.mean(img2)
        
        # Calculate variances and covariance
        sigma1_sq = np.var(img1)
        sigma2_sq = np.var(img2)
        sigma12 = np.mean((img1 - mu1) * (img2 - mu2))
        
        # SSIM formula
        numerator = (2 * mu1 * mu2 + C1) * (2 * sigma12 + C2)
        denominator = (mu1 ** 2 + mu2 ** 2 + C1) * (sigma1_sq + sigma2_sq + C2)
        
        ssim = numerator / denominator
        return float(ssim)
    
    def compare_images(
        self, 
        original_path: Union[str, Path], 
        compressed_path: Union[str, Path]
    ) -> Dict[str, float]:
        """
        Compare original and compressed images using multiple metrics.
        
        Returns:
            Dictionary with MSE, PSNR, and SSIM values
        """
        # Load images
        original = np.array(Image.open(original_path).convert('RGB'))
        compressed_img = Image.open(compressed_path).convert('RGB')
        
        # Resize compressed to match original if needed
        if compressed_img.size != (original.shape[1], original.shape[0]):
            compressed_img = compressed_img.resize(
                (original.shape[1], original.shape[0]), 
                Image.Resampling.LANCZOS
            )
        
        compressed = np.array(compressed_img)
        
        return {
            'mse': self.calculate_mse(original, compressed),
            'psnr': self.calculate_psnr(original, compressed),
            'ssim': self.calculate_ssim_simple(original, compressed),
        }
    
    def get_quality_rating(self, metrics: Dict[str, float]) -> str:
        """
        Get human-readable quality rating based on metrics.
        """
        psnr = metrics.get('psnr', 0)
        ssim = metrics.get('ssim', 0)
        
        if psnr > 40 and ssim > 0.95:
            return "Excellent - Nearly indistinguishable from original"
        elif psnr > 35 and ssim > 0.90:
            return "Good - Minor differences, acceptable for most uses"
        elif psnr > 30 and ssim > 0.80:
            return "Fair - Noticeable compression but still usable"
        else:
            return "Poor - Significant quality loss"
    
    def print_comparison(
        self, 
        original_path: Union[str, Path], 
        compressed_path: Union[str, Path]
    ) -> None:
        """Print a formatted comparison report."""
        import os
        
        metrics = self.compare_images(original_path, compressed_path)
        rating = self.get_quality_rating(metrics)
        
        original_size = os.path.getsize(original_path)
        compressed_size = os.path.getsize(compressed_path)
        ratio = original_size / compressed_size if compressed_size > 0 else 0
        
        print("\n" + "=" * 50)
        print("IMAGE QUALITY COMPARISON")
        print("=" * 50)
        print(f"Original:   {original_path}")
        print(f"Compressed: {compressed_path}")
        print("-" * 50)
        print(f"Original Size:   {original_size / (1024*1024):.2f} MB")
        print(f"Compressed Size: {compressed_size / (1024*1024):.2f} MB")
        print(f"Compression Ratio: {ratio:.1f}:1")
        print("-" * 50)
        print(f"MSE:  {metrics['mse']:.2f}")
        print(f"PSNR: {metrics['psnr']:.2f} dB")
        print(f"SSIM: {metrics['ssim']:.4f}")
        print("-" * 50)
        print(f"Quality Rating: {rating}")
        print("=" * 50 + "\n")

    @staticmethod
    def calculate_tile_seam_metric(
        image: np.ndarray,
        tile_size: int = 1024,
        overlap: int = 0
    ) -> Dict[str, float]:
        """
        Calculate tile seam visibility metric.

        Measures the average absolute difference across tile boundaries
        to quantify seam artifacts. Lower values = less visible seams.

        Args:
            image: Input image as numpy array (H, W, 3)
            tile_size: Tile size used during compression
            overlap: Overlap used during compression (0 for NCI2)

        Returns:
            Dictionary with seam metrics:
            - 'mean_seam_diff': Average absolute difference at seam boundaries
            - 'max_seam_diff': Maximum absolute difference at seam boundaries
            - 'num_seams': Number of seam boundaries measured
        """
        h, w = image.shape[:2]
        stride = tile_size - overlap if overlap > 0 else tile_size
        image_f = image.astype(np.float32)

        diffs = []

        # Measure vertical seams (along x-axis boundaries)
        x = stride
        while x < w - 1:
            left = image_f[:, x - 1, :]
            right = image_f[:, x, :]
            diff = np.abs(left - right).mean()
            diffs.append(diff)
            x += stride

        # Measure horizontal seams (along y-axis boundaries)
        y = stride
        while y < h - 1:
            top = image_f[y - 1, :, :]
            bottom = image_f[y, :, :]
            diff = np.abs(top - bottom).mean()
            diffs.append(diff)
            y += stride

        if not diffs:
            return {
                'mean_seam_diff': 0.0,
                'max_seam_diff': 0.0,
                'num_seams': 0,
            }

        return {
            'mean_seam_diff': float(np.mean(diffs)),
            'max_seam_diff': float(np.max(diffs)),
            'num_seams': len(diffs),
        }
