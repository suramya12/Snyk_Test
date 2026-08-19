"""
Intelligent caching system for metadata, thumbnails, and API responses.

Performance features:
- LRU cache for frequently accessed data
- Disk cache for thumbnails with automatic cleanup
- TTL-based expiration
- Memory-efficient storage
- Thread-safe operations
"""
from __future__ import annotations
import hashlib
import json
import pickle
import time
import threading
from pathlib import Path
from typing import Any, Optional, Dict, Callable
from functools import wraps
from datetime import datetime, timedelta

from .config import CONFIG
from .logging_util import get_logger

log = get_logger("cache")


class LRUCache:
    """
    Thread-safe LRU cache with TTL support.

    Features:
    - Least Recently Used eviction
    - Time-to-live expiration
    - Maximum size limit
    - Thread-safe operations
    """

    def __init__(self, max_size: int = 1000, default_ttl: float = 300.0):
        """
        Initialize LRU cache.

        Args:
            max_size: Maximum number of items
            default_ttl: Default time-to-live in seconds
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: Dict[str, Any] = {}
        self._access_times: Dict[str, float] = {}
        self._expiry_times: Dict[str, float] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            # Check expiration
            if time.time() > self._expiry_times.get(key, 0):
                # Expired
                self._remove(key)
                self._misses += 1
                return None

            # Update access time
            self._access_times[key] = time.time()
            self._hits += 1
            return self._cache[key]

    def set(self, key: str, value: Any, ttl: Optional[float] = None):
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (default: self.default_ttl)
        """
        with self._lock:
            # Evict if at max capacity
            if len(self._cache) >= self.max_size and key not in self._cache:
                self._evict_lru()

            self._cache[key] = value
            self._access_times[key] = time.time()
            self._expiry_times[key] = time.time() + (ttl or self.default_ttl)

    def _remove(self, key: str):
        """Remove key from cache."""
        self._cache.pop(key, None)
        self._access_times.pop(key, None)
        self._expiry_times.pop(key, None)

    def _evict_lru(self):
        """Evict least recently used item."""
        if not self._access_times:
            return

        lru_key = min(self._access_times, key=self._access_times.get)
        self._remove(lru_key)
        log.debug(f"Evicted LRU key: {lru_key}")

    def clear(self):
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._access_times.clear()
            self._expiry_times.clear()
            log.info("Cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0

            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
            }


class DiskCache:
    """
    Disk-based cache with automatic cleanup.

    Features:
    - Persistent storage on disk
    - Automatic size management
    - TTL-based expiration
    - Efficient file organization
    """

    def __init__(self, cache_dir: Path, max_size_mb: int = 500, default_ttl: float = 86400.0):
        """
        Initialize disk cache.

        Args:
            cache_dir: Directory for cache files
            max_size_mb: Maximum cache size in megabytes
            default_ttl: Default TTL in seconds (default: 24 hours)
        """
        self.cache_dir = cache_dir
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.default_ttl = default_ttl
        self._lock = threading.RLock()

        # Create cache directory
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._metadata_file = self.cache_dir / "metadata.json"
        self._metadata = self._load_metadata()

    def _load_metadata(self) -> Dict:
        """Load cache metadata."""
        if self._metadata_file.exists():
            try:
                with open(self._metadata_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                log.warning(f"Failed to load cache metadata: {e}")
        return {}

    def _save_metadata(self):
        """Save cache metadata."""
        try:
            with open(self._metadata_file, 'w') as f:
                json.dump(self._metadata, f, indent=2)
        except Exception as e:
            log.warning(f"Failed to save cache metadata: {e}")

    def _get_cache_path(self, key: str) -> Path:
        """Get file path for cache key."""
        # Hash key to create filename
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.cache"

    def get(self, key: str) -> Optional[bytes]:
        """
        Get value from disk cache.

        Args:
            key: Cache key

        Returns:
            Cached bytes or None
        """
        with self._lock:
            if key not in self._metadata:
                return None

            # Check expiration
            if time.time() > self._metadata[key].get("expiry", 0):
                self.delete(key)
                return None

            cache_path = self._get_cache_path(key)
            if not cache_path.exists():
                self._metadata.pop(key, None)
                return None

            try:
                with open(cache_path, 'rb') as f:
                    return f.read()
            except Exception as e:
                log.warning(f"Failed to read cache file: {e}")
                return None

    def set(self, key: str, value: bytes, ttl: Optional[float] = None):
        """
        Set value in disk cache.

        Args:
            key: Cache key
            value: Bytes to cache
            ttl: Time-to-live in seconds
        """
        with self._lock:
            # Check size limits
            self._enforce_size_limit(len(value))

            cache_path = self._get_cache_path(key)

            try:
                with open(cache_path, 'wb') as f:
                    f.write(value)

                self._metadata[key] = {
                    "expiry": time.time() + (ttl or self.default_ttl),
                    "size": len(value),
                    "created": time.time(),
                }
                self._save_metadata()

            except Exception as e:
                log.error(f"Failed to write cache file: {e}")

    def delete(self, key: str):
        """Delete cache entry."""
        with self._lock:
            cache_path = self._get_cache_path(key)
            if cache_path.exists():
                cache_path.unlink()

            self._metadata.pop(key, None)
            self._save_metadata()

    def _enforce_size_limit(self, new_size: int):
        """Enforce cache size limit by removing old entries."""
        total_size = sum(meta.get("size", 0) for meta in self._metadata.values())

        if total_size + new_size > self.max_size_bytes:
            # Sort by creation time, oldest first
            sorted_keys = sorted(
                self._metadata.keys(),
                key=lambda k: self._metadata[k].get("created", 0)
            )

            # Remove oldest entries
            for key in sorted_keys:
                if total_size + new_size <= self.max_size_bytes:
                    break

                size = self._metadata[key].get("size", 0)
                self.delete(key)
                total_size -= size
                log.debug(f"Evicted old cache entry: {key}")

    def clear(self):
        """Clear all cache files."""
        with self._lock:
            for cache_file in self.cache_dir.glob("*.cache"):
                cache_file.unlink()

            self._metadata.clear()
            self._save_metadata()
            log.info("Disk cache cleared")

    def get_size(self) -> int:
        """Get total cache size in bytes."""
        return sum(meta.get("size", 0) for meta in self._metadata.values())

    def cleanup_expired(self):
        """Remove expired cache entries."""
        with self._lock:
            now = time.time()
            expired_keys = [
                key for key, meta in self._metadata.items()
                if now > meta.get("expiry", 0)
            ]

            for key in expired_keys:
                self.delete(key)

            if expired_keys:
                log.info(f"Cleaned up {len(expired_keys)} expired cache entries")


# Global cache instances
_memory_cache = LRUCache(max_size=1000, default_ttl=300.0)  # 5 minutes
_disk_cache = DiskCache(CONFIG.data_dir / "cache", max_size_mb=500, default_ttl=86400.0)  # 24 hours
_thumbnail_cache = DiskCache(CONFIG.thumb_dir, max_size_mb=200, default_ttl=604800.0)  # 7 days


def cache_in_memory(ttl: Optional[float] = None):
    """
    Decorator for caching function results in memory.

    Args:
        ttl: Time-to-live in seconds

    Example:
        @cache_in_memory(ttl=60)
        def expensive_function(arg1, arg2):
            return result
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from function name and arguments
            key_parts = [func.__name__]
            key_parts.extend(str(arg) for arg in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = ":".join(key_parts)

            # Try cache first
            result = _memory_cache.get(cache_key)
            if result is not None:
                log.debug(f"Cache hit for {func.__name__}")
                return result

            # Call function and cache result
            result = func(*args, **kwargs)
            _memory_cache.set(cache_key, result, ttl=ttl)
            return result

        return wrapper
    return decorator


def get_memory_cache() -> LRUCache:
    """Get global memory cache instance."""
    return _memory_cache


def get_disk_cache() -> DiskCache:
    """Get global disk cache instance."""
    return _disk_cache


def get_thumbnail_cache() -> DiskCache:
    """Get global thumbnail cache instance."""
    return _thumbnail_cache


def clear_all_caches():
    """Clear all cache instances."""
    _memory_cache.clear()
    _disk_cache.clear()
    _thumbnail_cache.clear()
    log.info("All caches cleared")


def get_cache_stats() -> Dict[str, Any]:
    """Get statistics for all caches."""
    return {
        "memory": _memory_cache.get_stats(),
        "disk_size_mb": _disk_cache.get_size() / (1024 * 1024),
        "thumbnail_size_mb": _thumbnail_cache.get_size() / (1024 * 1024),
    }


def cleanup_caches():
    """Cleanup expired entries in all caches."""
    _disk_cache.cleanup_expired()
    _thumbnail_cache.cleanup_expired()
    log.info("Cache cleanup completed")
