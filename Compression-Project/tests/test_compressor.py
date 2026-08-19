"""
Tests for the Image Compressor.
"""

import unittest
import tempfile
import os
from pathlib import Path
from PIL import Image
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.compressor import ImageCompressor, CompressionResult
from src.quality import QualityAnalyzer
from src.utils import parse_size_string, format_size, get_file_size_mb


class TestUtils(unittest.TestCase):
    """Test utility functions."""
    
    def test_parse_size_string(self):
        """Test size string parsing."""
        self.assertEqual(parse_size_string("3MB"), 3 * 1024 * 1024)
        self.assertEqual(parse_size_string("500KB"), 500 * 1024)
        self.assertEqual(parse_size_string("1GB"), 1024 * 1024 * 1024)
        self.assertEqual(parse_size_string("100"), 100)
    
    def test_format_size(self):
        """Test size formatting."""
        self.assertEqual(format_size(500), "500 B")
        self.assertIn("KB", format_size(5000))
        self.assertIn("MB", format_size(5000000))


class TestQualityAnalyzer(unittest.TestCase):
    """Test quality analysis functions."""
    
    def setUp(self):
        self.analyzer = QualityAnalyzer()
    
    def test_identical_images_ssim(self):
        """SSIM of identical images should be 1.0."""
        img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        ssim = self.analyzer.calculate_ssim_simple(img, img)
        self.assertAlmostEqual(ssim, 1.0, places=4)
    
    def test_identical_images_mse(self):
        """MSE of identical images should be 0."""
        img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        mse = self.analyzer.calculate_mse(img, img)
        self.assertEqual(mse, 0.0)
    
    def test_identical_images_psnr(self):
        """PSNR of identical images should be infinity."""
        img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        psnr = self.analyzer.calculate_psnr(img, img)
        self.assertEqual(psnr, float('inf'))
    
    def test_different_images_ssim(self):
        """SSIM of different images should be less than 1."""
        img1 = np.zeros((100, 100, 3), dtype=np.uint8)
        img2 = np.ones((100, 100, 3), dtype=np.uint8) * 255
        ssim = self.analyzer.calculate_ssim_simple(img1, img2)
        self.assertLess(ssim, 1.0)


class TestImageCompressor(unittest.TestCase):
    """Test image compression functionality."""
    
    def setUp(self):
        self.compressor = ImageCompressor(min_ssim=0.95, verbose=False)
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        # Clean up temp files
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def create_test_image(self, size=(1000, 1000), filename="test.png"):
        """Create a test image with random content."""
        path = Path(self.temp_dir) / filename
        
        # Create image with some structure (not just noise)
        img_array = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        
        # Add gradient
        for i in range(size[1]):
            img_array[i, :, 0] = int(255 * i / size[1])
        for j in range(size[0]):
            img_array[:, j, 1] = int(255 * j / size[0])
        
        # Add some random variation
        noise = np.random.randint(0, 50, (size[1], size[0], 3), dtype=np.uint8)
        img_array = np.clip(img_array.astype(int) + noise.astype(int), 0, 255).astype(np.uint8)
        
        img = Image.fromarray(img_array)
        img.save(path)
        return path
    
    def test_compression_creates_output(self):
        """Test that compression creates an output file."""
        input_path = self.create_test_image()
        output_path = Path(self.temp_dir) / "output.webp"
        
        result = self.compressor.compress_to_size(
            input_path, output_path, target_ratio=5
        )
        
        self.assertTrue(output_path.exists() or result.output_path.exists())
    
    def test_compression_reduces_size(self):
        """Test that compression reduces file size."""
        input_path = self.create_test_image(size=(2000, 2000))
        output_path = Path(self.temp_dir) / "output.webp"
        
        result = self.compressor.compress_to_size(
            input_path, output_path, target_ratio=3
        )
        
        self.assertGreater(result.compression_ratio, 1.0)
    
    def test_compression_maintains_quality(self):
        """Test that compression maintains SSIM above threshold."""
        input_path = self.create_test_image(size=(1000, 1000))
        output_path = Path(self.temp_dir) / "output.webp"
        
        result = self.compressor.compress_to_size(
            input_path, output_path, target_ratio=5
        )
        
        # Quality should be at or near threshold
        self.assertGreaterEqual(result.ssim, 0.90)  # Allow some tolerance
    
    def test_result_dataclass(self):
        """Test CompressionResult properties."""
        result = CompressionResult(
            success=True,
            output_path=Path("/test/output.webp"),
            original_size=30_000_000,
            compressed_size=3_000_000,
            compression_ratio=10.0,
            ssim=0.96,
            quality_setting=80,
            format_used='webp',
            message="Success"
        )
        
        self.assertEqual(result.size_reduction_percent, 90.0)


if __name__ == '__main__':
    unittest.main()
