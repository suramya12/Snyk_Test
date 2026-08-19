"""
Utility functions for image compression.
"""

import os
from pathlib import Path
from typing import Union


def get_file_size_mb(file_path: Union[str, Path]) -> float:
    """Get file size in megabytes."""
    return os.path.getsize(file_path) / (1024 * 1024)


def get_file_size_bytes(file_path: Union[str, Path]) -> int:
    """Get file size in bytes."""
    return os.path.getsize(file_path)


def format_size(size_bytes: int) -> str:
    """Format byte size to human readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def parse_size_string(size_str: str) -> int:
    """
    Parse a size string like '3MB' or '500KB' to bytes.
    
    Args:
        size_str: Size string (e.g., '3MB', '500KB', '1GB')
        
    Returns:
        Size in bytes
    """
    size_str = size_str.strip().upper()
    
    # Order matters: check longer units first
    units = [
        ('GB', 1024 * 1024 * 1024),
        ('MB', 1024 * 1024),
        ('KB', 1024),
        ('B', 1),
    ]
    
    for unit, multiplier in units:
        if size_str.endswith(unit):
            number = size_str[:-len(unit)].strip()
            return int(float(number) * multiplier)
    
    # If no unit, assume bytes
    return int(size_str)


def get_supported_formats() -> dict:
    """Return dictionary of supported output formats and their extensions."""
    return {
        'jpeg': ['.jpg', '.jpeg'],
        'webp': ['.webp'],
        'png': ['.png'],
    }


def is_supported_image(file_path: Union[str, Path]) -> bool:
    """Check if file is a supported image format."""
    supported = ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif']
    ext = Path(file_path).suffix.lower()
    return ext in supported


def ensure_directory(path: Union[str, Path]) -> Path:
    """Ensure directory exists, create if not."""
    path = Path(path)
    if path.suffix:  # It's a file path
        path = path.parent
    path.mkdir(parents=True, exist_ok=True)
    return path
