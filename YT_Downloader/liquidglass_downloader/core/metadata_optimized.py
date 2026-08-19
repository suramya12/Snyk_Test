"""
Optimized metadata fetching with caching and connection pooling.

Performance improvements:
- Metadata caching to avoid repeat network requests
- Thumbnail caching on disk
- Connection pooling for HTTP requests
- Async metadata fetching
- Batch operations support
"""
from __future__ import annotations
import os
import hashlib
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, Future
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from yt_dlp import YoutubeDL

from .config import CONFIG
from .db_optimized import DB_INSTANCE as DB
from .cache import get_memory_cache, get_thumbnail_cache, cache_in_memory
from .logging_util import get_logger

log = get_logger("metadata")

# Global HTTP session with connection pooling
_http_session: Optional[requests.Session] = None
_http_session_lock = __import__('threading').Lock()

# Metadata fetch executor
_metadata_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="metadata")


def _get_http_session() -> requests.Session:
    """
    Get or create HTTP session with connection pooling and retries.

    Returns:
        Configured requests Session with pooling
    """
    global _http_session

    with _http_session_lock:
        if _http_session is None:
            session = requests.Session()

            # Configure retry strategy
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "POST"]
            )

            # Configure adapter with connection pooling
            adapter = HTTPAdapter(
                max_retries=retry_strategy,
                pool_connections=10,
                pool_maxsize=20,
                pool_block=False
            )

            session.mount("http://", adapter)
            session.mount("https://", adapter)

            # Set timeout
            session.timeout = 15

            _http_session = session
            log.info("HTTP session initialized with connection pooling")

        return _http_session


@cache_in_memory(ttl=3600.0)  # Cache metadata for 1 hour
def _fetch_video_info(url: str) -> Optional[Dict[str, Any]]:
    """
    Fetch video metadata with caching.

    Args:
        url: Video URL

    Returns:
        Video info dict or None
    """
    try:
        with YoutubeDL({"quiet": True, "skip_download": True, "noplaylist": False}) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        log.warning(f"Failed to fetch video info: {e}")
        return None


def _download_thumbnail(url: str, item_id: int) -> Optional[str]:
    """
    Download and cache thumbnail.

    Args:
        url: Thumbnail URL
        item_id: Database item ID

    Returns:
        Path to cached thumbnail or None
    """
    if not url:
        return None

    try:
        # Check thumbnail cache first
        cache_key = f"thumb_{item_id}"
        thumbnail_cache = get_thumbnail_cache()

        cached_thumb = thumbnail_cache.get(cache_key)
        if cached_thumb:
            # Return cached path
            thumb_path = CONFIG.thumb_dir / f"{item_id}.jpg"
            if not thumb_path.exists():
                with open(thumb_path, 'wb') as f:
                    f.write(cached_thumb)
            return str(thumb_path)

        # Download thumbnail
        session = _get_http_session()
        response = session.get(url, timeout=15)

        if response.ok:
            thumb_data = response.content
            thumb_path = CONFIG.thumb_dir / f"{item_id}.jpg"

            # Save to disk
            with open(thumb_path, 'wb') as f:
                f.write(thumb_data)

            # Cache for future use
            thumbnail_cache.set(cache_key, thumb_data, ttl=604800.0)  # 7 days

            log.debug(f"Downloaded and cached thumbnail for item {item_id}")
            return str(thumb_path)

    except Exception as e:
        log.warning(f"Thumbnail download failed for item {item_id}: {e}")

    return None


def fetch_and_store(item_id: int, url: str) -> bool:
    """
    Fetch video metadata and thumbnail, store in database.

    Args:
        item_id: Database item ID
        url: Video URL

    Returns:
        True if successful, False otherwise
    """
    try:
        # Fetch video info (cached)
        info = _fetch_video_info(url)
        if not info:
            log.warning(f"Could not fetch info for item {item_id}")
            return False

        # Extract metadata
        title = info.get("title")
        duration = info.get("duration")
        uploader = info.get("uploader")
        thumbnail_url = info.get("thumbnail")

        # Download and cache thumbnail
        thumb_path = _download_thumbnail(thumbnail_url, item_id) if thumbnail_url else None

        # Update database
        DB.update(
            item_id,
            title=title,
            duration=duration,
            uploader=uploader,
            thumb_path=thumb_path
        )

        log.info(f"Fetched metadata for item {item_id}: {title}")
        return True

    except Exception as e:
        log.error(f"Metadata fetch failed for item {item_id}: {e}")
        return False


def fetch_and_store_async(item_id: int, url: str) -> Future:
    """
    Fetch metadata asynchronously.

    Args:
        item_id: Database item ID
        url: Video URL

    Returns:
        Future that resolves to bool (success status)
    """
    return _metadata_executor.submit(fetch_and_store, item_id, url)


def batch_fetch_metadata(items: list[tuple[int, str]]) -> Dict[int, bool]:
    """
    Fetch metadata for multiple items in parallel.

    Args:
        items: List of (item_id, url) tuples

    Returns:
        Dict mapping item_id to success status
    """
    if not items:
        return {}

    log.info(f"Batch fetching metadata for {len(items)} items")

    # Submit all tasks
    futures = {
        item_id: _metadata_executor.submit(fetch_and_store, item_id, url)
        for item_id, url in items
    }

    # Collect results
    results = {}
    for item_id, future in futures.items():
        try:
            results[item_id] = future.result(timeout=60)
        except Exception as e:
            log.error(f"Batch metadata fetch failed for item {item_id}: {e}")
            results[item_id] = False

    successful = sum(1 for success in results.values() if success)
    log.info(f"Batch metadata fetch complete: {successful}/{len(items)} successful")

    return results


def preload_metadata(urls: list[str]) -> Dict[str, Optional[Dict]]:
    """
    Preload metadata for multiple URLs into cache.

    Args:
        urls: List of video URLs

    Returns:
        Dict mapping URL to info dict
    """
    results = {}

    def fetch_info(url):
        return url, _fetch_video_info(url)

    # Fetch in parallel
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_info, url) for url in urls]

        for future in futures:
            try:
                url, info = future.result(timeout=30)
                results[url] = info
            except Exception as e:
                log.warning(f"Preload failed: {e}")

    log.info(f"Preloaded metadata for {len(results)} URLs")
    return results


def get_video_title(url: str) -> Optional[str]:
    """
    Get video title from cache or fetch if needed.

    Args:
        url: Video URL

    Returns:
        Video title or None
    """
    info = _fetch_video_info(url)
    return info.get("title") if info else None


def clear_metadata_cache():
    """Clear all metadata caches."""
    memory_cache = get_memory_cache()
    memory_cache.clear()
    log.info("Metadata cache cleared")


def get_thumbnail_for_item(item_id: int, url: str) -> Optional[str]:
    """
    Get thumbnail path for item, fetch if not cached.

    Args:
        item_id: Database item ID
        url: Video URL

    Returns:
        Path to thumbnail or None
    """
    # Check if already exists
    thumb_path = CONFIG.thumb_dir / f"{item_id}.jpg"
    if thumb_path.exists():
        return str(thumb_path)

    # Fetch video info to get thumbnail URL
    info = _fetch_video_info(url)
    if info and info.get("thumbnail"):
        return _download_thumbnail(info["thumbnail"], item_id)

    return None


def cleanup_old_thumbnails(days: int = 30):
    """
    Remove thumbnails older than specified days.

    Args:
        days: Age threshold in days
    """
    import time
    from pathlib import Path

    threshold = time.time() - (days * 86400)
    removed = 0

    for thumb_file in CONFIG.thumb_dir.glob("*.jpg"):
        if thumb_file.stat().st_mtime < threshold:
            thumb_file.unlink()
            removed += 1

    if removed > 0:
        log.info(f"Cleaned up {removed} old thumbnails")


def shutdown_metadata_executor():
    """Shutdown metadata fetch executor."""
    _metadata_executor.shutdown(wait=True)
    log.info("Metadata executor shut down")


def close_http_session():
    """Close global HTTP session."""
    global _http_session

    with _http_session_lock:
        if _http_session:
            _http_session.close()
            _http_session = None
            log.info("HTTP session closed")
