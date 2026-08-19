"""
Optimized download manager with resource pooling and event-driven progress.

Performance optimizations:
- Dynamic thread pool sizing based on system resources
- Progress event system to reduce database writes
- Memory-efficient streaming
- Better cancellation and cleanup
- Resource throttling and limits
"""
from __future__ import annotations
import threading
import time
import os
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Dict, Any, Optional, Callable, Set
from collections import deque
from dataclasses import dataclass

from yt_dlp import YoutubeDL

from .config import CONFIG
from .db_optimized import DB_INSTANCE as DB
from .models import Status
from .metadata_optimized import fetch_and_store_async
from .logging_util import get_logger
from .constants import (
    DEFAULT_MAX_RETRIES,
    YTDLP_RETRIES,
    FRAGMENT_RETRIES,
    PROGRESS_UPDATE_THROTTLE,
    RETRY_BACKOFF_BASE,
    OUTPUT_TEMPLATE,
    YTDLP_DEFAULT_OPTIONS,
    YOUTUBE_EXTRACTOR_ARGS,
    HTTP_HEADERS,
    ERROR_MESSAGES,
    QUALITY_PRESETS,
)
from .validation import validate_url, URLValidationError

log = get_logger("downloader")


@dataclass
class ProgressEvent:
    """Progress update event."""
    item_id: int
    status: Status
    downloaded_bytes: Optional[int] = None
    total_bytes: Optional[int] = None
    speed: Optional[float] = None
    eta: Optional[int] = None
    title: Optional[str] = None
    error_message: Optional[str] = None


class _TaskControl:
    """Task control for pause/cancel operations."""

    def __init__(self) -> None:
        self.cancel = threading.Event()
        self.pause = threading.Event()
        self.last_progress_time = 0.0


class ProgressAggregator:
    """
    Aggregates progress updates to reduce database writes.

    Batches updates and only writes to database periodically.
    """

    def __init__(self, flush_interval: float = 1.0):
        """
        Initialize progress aggregator.

        Args:
            flush_interval: Time between database flushes in seconds
        """
        self.flush_interval = flush_interval
        self._pending: Dict[int, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._last_flush = time.time()
        self._running = True
        self._flush_thread = threading.Thread(target=self._flush_worker, daemon=True)
        self._flush_thread.start()

    def add_progress(self, item_id: int, **fields):
        """Add progress update for item."""
        with self._lock:
            if item_id not in self._pending:
                self._pending[item_id] = {}
            self._pending[item_id].update(fields)

    def _flush_worker(self):
        """Background worker to flush updates periodically."""
        while self._running:
            time.sleep(0.5)

            if time.time() - self._last_flush >= self.flush_interval:
                self.flush()

    def flush(self):
        """Flush pending updates to database."""
        with self._lock:
            if not self._pending:
                return

            # Batch update all pending changes
            updates = [(item_id, fields) for item_id, fields in self._pending.items()]
            self._pending.clear()
            self._last_flush = time.time()

        # Write to database outside lock
        try:
            DB.batch_update(updates)
        except Exception as e:
            log.error(f"Failed to flush progress updates: {e}")

    def stop(self):
        """Stop aggregator and flush remaining updates."""
        self._running = False
        self.flush()


class DownloadManager:
    """
    Optimized download manager with resource pooling and event system.

    Features:
    - Dynamic thread pool sizing
    - Progress aggregation to reduce DB writes
    - Event-driven progress updates
    - Better resource cleanup
    - Memory-efficient operations
    """

    def __init__(self) -> None:
        # Determine optimal worker count
        cpu_count = os.cpu_count() or 2
        max_workers = min(CONFIG.settings.concurrent_downloads, cpu_count * 2)

        self.exec = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="download"
        )
        self.controls: Dict[int, _TaskControl] = {}
        self.active_tasks: Dict[int, Future] = {}
        self.lock = threading.Lock()

        # Progress aggregation
        self.progress_aggregator = ProgressAggregator(flush_interval=1.0)

        # Event listeners
        self._event_listeners: Set[Callable[[ProgressEvent], None]] = set()
        self._listener_lock = threading.Lock()

        # Statistics
        self.stats = {
            "total_downloads": 0,
            "successful": 0,
            "failed": 0,
            "canceled": 0,
        }

        log.info(f"DownloadManager initialized with {max_workers} workers")

    def add_progress_listener(self, listener: Callable[[ProgressEvent], None]):
        """
        Add progress event listener.

        Args:
            listener: Callback function that receives ProgressEvent
        """
        with self._listener_lock:
            self._event_listeners.add(listener)

    def remove_progress_listener(self, listener: Callable[[ProgressEvent], None]):
        """Remove progress event listener."""
        with self._listener_lock:
            self._event_listeners.discard(listener)

    def _emit_progress(self, event: ProgressEvent):
        """Emit progress event to all listeners."""
        with self._listener_lock:
            for listener in self._event_listeners:
                try:
                    listener(event)
                except Exception as e:
                    log.error(f"Progress listener error: {e}")

    def __del__(self):
        self.cleanup()

    def cleanup(self):
        """Clean up resources and cancel pending tasks."""
        log.info("Cleaning up download manager...")

        with self.lock:
            # Cancel all active tasks
            for item_id, future in self.active_tasks.items():
                if not future.done():
                    future.cancel()

            self.active_tasks.clear()

        # Flush remaining progress updates
        self.progress_aggregator.stop()

        # Shutdown executor
        self.exec.shutdown(wait=False)

        log.info("Download manager cleaned up")

    def set_concurrency(self, n: int) -> None:
        """
        Change concurrent download limit.

        Args:
            n: New concurrency limit
        """
        if n < 1:
            n = 1

        cpu_count = os.cpu_count() or 2
        n = min(n, cpu_count * 2)  # Cap at 2x CPU count

        if n == CONFIG.settings.concurrent_downloads:
            return

        CONFIG.settings.concurrent_downloads = n
        CONFIG.save(CONFIG.settings)

        # Recreate executor with new size
        old = self.exec
        self.exec = ThreadPoolExecutor(max_workers=n, thread_name_prefix="download")
        old.shutdown(wait=False, cancel_futures=True)

        log.info(f"Concurrency changed to {n}")

    def queue(self, url: str, fmt: Optional[str] = None) -> int:
        """
        Add URL to download queue with validation.

        Args:
            url: Video URL
            fmt: Optional format override

        Returns:
            Database ID of queued item

        Raises:
            URLValidationError: If URL is invalid
        """
        # Validate URL
        try:
            validated_url = validate_url(url, check_platform=False)
        except URLValidationError as e:
            log.error(f"URL validation failed: {e}")
            raise

        # Add to database
        item_id = DB.add_queue_item(validated_url, fmt or CONFIG.settings.format)

        # Fetch metadata asynchronously
        with self.lock:
            future = fetch_and_store_async(item_id, validated_url)
            self.active_tasks[item_id] = future

        log.info(f"Queued URL {validated_url} -> item {item_id}")

        # Emit event
        self._emit_progress(ProgressEvent(item_id=item_id, status=Status.QUEUED))

        return item_id

    def start(self, item_id: int) -> None:
        """Start download for item."""
        with self.lock:
            # Cancel any existing task
            if item_id in self.active_tasks:
                existing = self.active_tasks[item_id]
                if not existing.done():
                    existing.cancel()

            # Create control
            ctl = self.controls.get(item_id) or _TaskControl()
            self.controls[item_id] = ctl
            ctl.cancel.clear()
            ctl.pause.clear()

            # Submit download task
            future = self.exec.submit(self._run, item_id, ctl)
            self.active_tasks[item_id] = future

        log.info(f"Started download for item {item_id}")

    def start_all(self) -> None:
        """Start all queued/paused/error items."""
        items = DB.list(status=None)
        startable = [
            item for item in items
            if item.status in (Status.QUEUED, Status.PAUSED, Status.ERROR)
        ]

        for item in startable:
            self.start(item.id)

        log.info(f"Started {len(startable)} downloads")

    def pause(self, item_id: int) -> None:
        """Pause download."""
        ctl = self.controls.get(item_id)
        if ctl:
            ctl.pause.set()
            log.info(f"Paused item {item_id}")

    def pause_all(self) -> None:
        """Pause all active downloads."""
        items = DB.list(status=Status.DOWNLOADING.value)
        for item in items:
            self.pause(item.id)

    def cancel(self, item_id: int) -> None:
        """Cancel download."""
        ctl = self.controls.get(item_id)
        if ctl:
            ctl.cancel.set()
            log.info(f"Canceled item {item_id}")

    def cancel_all(self) -> None:
        """Cancel all downloads."""
        for item_id in list(self.controls.keys()):
            self.cancel(item_id)

    def resume(self, item_id: int) -> None:
        """Resume paused download."""
        DB.update(item_id, status=Status.QUEUED.value, errmsg=None)
        self.start(item_id)
        log.info(f"Resumed item {item_id}")

    def _progress_hook(self, item_id: int, ctl: _TaskControl):
        """
        Create progress hook for yt-dlp.

        Uses progress aggregator to reduce database writes.
        """
        def hook(d: dict) -> None:
            if ctl.cancel.is_set():
                raise Exception("Canceled by user")
            if ctl.pause.is_set():
                raise Exception("Paused by user")

            status = d.get("status")

            if status == "downloading":
                now = time.time()

                # Throttle progress updates
                if now - ctl.last_progress_time < PROGRESS_UPDATE_THROTTLE:
                    return

                ctl.last_progress_time = now

                downloaded = d.get("downloaded_bytes") or 0
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                speed = d.get("speed")
                eta = d.get("eta")
                title = d.get("info_dict", {}).get("title")

                # Add to aggregator
                self.progress_aggregator.add_progress(
                    item_id,
                    status=Status.DOWNLOADING.value,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    speed=speed,
                    eta=eta,
                    title=title,
                )

                # Emit event
                self._emit_progress(ProgressEvent(
                    item_id=item_id,
                    status=Status.DOWNLOADING,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    speed=speed,
                    eta=eta,
                    title=title,
                ))

            elif status == "finished":
                filepath = d.get("filename")
                self.progress_aggregator.add_progress(
                    item_id,
                    status=Status.COMPLETED.value,
                    filepath=filepath
                )

                self._emit_progress(ProgressEvent(
                    item_id=item_id,
                    status=Status.COMPLETED
                ))

        return hook

    def _build_ydl_opts(
        self, item_id: int, ctl: _TaskControl, fmt: str, postprocessors: list[dict]
    ) -> Dict[str, Any]:
        """Build optimized yt-dlp options."""
        outtmpl = os.path.join(CONFIG.settings.download_dir, OUTPUT_TEMPLATE)

        # Get quality preset
        quality_preset = self._get_quality_preset(fmt)
        format_sort = quality_preset.get("format_sort") if quality_preset else [
            "res:2160", "res:1440", "res:1080", "res:720",
            "fps:60", "quality", "codec:h264"
        ]

        opts: Dict[str, Any] = {
            **YTDLP_DEFAULT_OPTIONS,
            "outtmpl": outtmpl,
            "format": "bestaudio/best" if CONFIG.settings.audio_only else fmt,
            "merge_output_format": "mp3" if CONFIG.settings.audio_only else "mp4",
            "retries": YTDLP_RETRIES,
            "fragment_retries": FRAGMENT_RETRIES,
            "retry_sleep": lambda n: RETRY_BACKOFF_BASE * (n + 1),
            "progress_hooks": [self._progress_hook(item_id, ctl)],
            "http_headers": {
                "User-Agent": CONFIG.settings.user_agent,
                **HTTP_HEADERS,
            },
            "cookiesfrombrowser": (CONFIG.settings.browser_for_cookies,) if CONFIG.settings.use_cookies_from_browser else None,
            "extractor_args": YOUTUBE_EXTRACTOR_ARGS,
            "format_sort": format_sort,
            "concurrent_fragment_downloads": 3,  # Download fragments concurrently
        }

        if CONFIG.settings.cookies_file:
            opts["cookiefile"] = CONFIG.settings.cookies_file
        if postprocessors:
            opts["postprocessors"] = postprocessors

        return opts

    def _get_quality_preset(self, fmt: str) -> Optional[Dict[str, Any]]:
        """Get quality preset configuration."""
        for preset_config in QUALITY_PRESETS.values():
            if preset_config["format"] == fmt:
                return preset_config
        return None

    def _categorize_error(self, error_msg: str) -> str:
        """Categorize error into user-friendly message."""
        error_lower = error_msg.lower()

        if any(x in error_lower for x in ["not found", "404", "removed", "deleted"]):
            return ERROR_MESSAGES["not_found"]
        elif any(x in error_lower for x in ["private", "unavailable"]):
            return ERROR_MESSAGES["private"]
        elif any(x in error_lower for x in ["geo", "region", "country"]):
            return ERROR_MESSAGES["geo_blocked"]
        elif any(x in error_lower for x in ["copyright", "claim"]):
            return ERROR_MESSAGES["copyright"]
        elif any(x in error_lower for x in ["live", "premiere"]):
            return ERROR_MESSAGES["live_stream"]
        elif any(x in error_lower for x in ["timeout", "timed out"]):
            return ERROR_MESSAGES["timeout"]
        elif any(x in error_lower for x in ["format", "quality"]):
            return ERROR_MESSAGES["format_unavailable"]
        elif any(x in error_lower for x in ["metadata", "extract"]):
            return ERROR_MESSAGES["metadata"]
        elif any(x in error_lower for x in ["permission", "access denied", "disk"]):
            return ERROR_MESSAGES["permission"]
        elif any(x in error_lower for x in ["network", "connection"]):
            return ERROR_MESSAGES["network"]
        else:
            return f"{ERROR_MESSAGES['unknown']} ({error_msg[:100]})"

    def _run(self, item_id: int, ctl: _TaskControl) -> None:
        """Execute download with retry logic."""
        row = DB.get(item_id)
        if not row:
            return

        fmt = row.format or CONFIG.settings.format
        postprocessors: list[dict[str, Any]] = []

        # Configure postprocessors
        postprocessors.append({
            "key": "EmbedThumbnail",
            "already_have_thumbnail": False
        })

        if CONFIG.settings.embed_subtitles:
            postprocessors.append({
                "key": "FFmpegEmbedSubtitle",
                "already_have_subtitle": False
            })

        postprocessors.append({
            "key": "FFmpegVideoConvertor",
            "preferedformat": "mp4",
            "when": "video"
        })

        ydl_opts = self._build_ydl_opts(item_id, ctl, fmt, postprocessors)
        max_retries = DEFAULT_MAX_RETRIES
        retry_count = 0

        while retry_count < max_retries:
            try:
                DB.update(item_id, status=Status.QUEUED.value)

                with YoutubeDL(ydl_opts) as ydl:
                    # Pre-check video availability
                    info = ydl.extract_info(row.url, download=False)
                    if not info:
                        raise Exception("Could not fetch video information")

                    # Update title
                    DB.update(item_id, title=info.get('title'))

                    # Download
                    ydl.download([row.url])

                DB.update(item_id, status=Status.COMPLETED.value)
                self.stats["successful"] += 1
                log.info(f"Completed item {item_id}")
                break

            except Exception as e:
                msg = str(e)
                log.warning(f"Item {item_id} attempt {retry_count + 1} failed: {msg}")

                if "Paused by user" in msg:
                    DB.update(item_id, status=Status.PAUSED.value, errmsg=None)
                    break
                elif "Canceled by user" in msg:
                    DB.update(item_id, status=Status.CANCELED.value, errmsg=None)
                    self.stats["canceled"] += 1
                    break
                else:
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        sleep_time = RETRY_BACKOFF_BASE * retry_count
                        log.info(f"Retrying in {sleep_time}s... ({retry_count}/{max_retries})")
                        time.sleep(sleep_time)
                        continue
                    else:
                        user_friendly_error = self._categorize_error(msg)
                        DB.update(item_id, status=Status.ERROR.value, errmsg=user_friendly_error)
                        self.stats["failed"] += 1
                        log.error(f"Download failed: {user_friendly_error}")

        # Cleanup
        with self.lock:
            self.active_tasks.pop(item_id, None)
            self.controls.pop(item_id, None)

    def get_stats(self) -> Dict[str, int]:
        """Get download statistics."""
        return self.stats.copy()
