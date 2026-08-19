from __future__ import annotations
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional
import os
import time

from yt_dlp import YoutubeDL
from .config import CONFIG
from .db import DB_INSTANCE as DB
from .models import Status
from .logging_util import get_logger
from . import metadata
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


class _TaskControl:
    def __init__(self) -> None:
        self.cancel = threading.Event()
        self.pause = threading.Event()


class DownloadManager:
    def __init__(self) -> None:
        self.exec = ThreadPoolExecutor(max_workers=CONFIG.settings.concurrent_downloads)
        self.controls: Dict[int, _TaskControl] = {}
        self.lock = threading.Lock()
        self.active_tasks: Dict[int, Any] = {}  # Store active futures
        
    def __del__(self):
        self.cleanup()
        
    def cleanup(self):
        """Clean up resources and cancel pending tasks"""
        with self.lock:
            for task_id, future in self.active_tasks.items():
                if not future.done():
                    future.cancel()
            self.active_tasks.clear()
            self.exec.shutdown(wait=False)

    def set_concurrency(self, n: int) -> None:
        if n < 1:
            n = 1
        if n == CONFIG.settings.concurrent_downloads:
            return
        CONFIG.settings.concurrent_downloads = n
        CONFIG.save(CONFIG.settings)
        old = self.exec
        self.exec = ThreadPoolExecutor(max_workers=n)
        old.shutdown(wait=False, cancel_futures=True)

    def queue(self, url: str, fmt: Optional[str] = None) -> int:
        """
        Add a URL to the download queue with validation.

        Args:
            url: The video URL to download
            fmt: Optional format string override

        Returns:
            The database ID of the queued item

        Raises:
            URLValidationError: If the URL is invalid or unsupported
        """
        # Validate URL before queuing
        try:
            validated_url = validate_url(url, check_platform=False)
        except URLValidationError as e:
            log.error(f"URL validation failed: {e}")
            raise

        item_id = DB.add_queue_item(validated_url, fmt or CONFIG.settings.format)

        # Submit metadata fetching task
        with self.lock:
            future = self.exec.submit(self._fetch_metadata_safe, item_id, validated_url)
            self.active_tasks[item_id] = future

        log.info("Queued %s -> id %s", validated_url, item_id)
        return item_id
        
    def _fetch_metadata_safe(self, item_id: int, url: str):
        """
        Safely fetch metadata with comprehensive error handling.

        Args:
            item_id: Database ID of the download item
            url: The video URL
        """
        try:
            metadata.fetch_and_store(item_id, url)
        except Exception as e:
            error_msg = self._categorize_error(str(e))
            log.error(f"Error fetching metadata for {url}: {e}")
            DB.update(item_id, status=Status.ERROR.value, errmsg=error_msg)
        finally:
            with self.lock:
                self.active_tasks.pop(item_id, None)

    def start(self, item_id: int) -> None:
        with self.lock:
            # Cancel any existing task
            if item_id in self.active_tasks:
                self.active_tasks[item_id].cancel()
            
            # Create new control and task
            ctl = self.controls.get(item_id) or _TaskControl()
            self.controls[item_id] = ctl
            ctl.cancel.clear()
            ctl.pause.clear()
            
            future = self.exec.submit(self._run, item_id, ctl)
            self.active_tasks[item_id] = future

    def start_all(self) -> None:
        for r in DB.list():
            if r.status in (Status.QUEUED, Status.PAUSED, Status.ERROR):
                self.start(r.id)

    def pause(self, item_id: int) -> None:
        ctl = self.controls.get(item_id)
        if ctl:
            ctl.pause.set()

    def pause_all(self) -> None:
        for r in DB.list():
            self.pause(r.id)

    def cancel(self, item_id: int) -> None:
        ctl = self.controls.get(item_id)
        if ctl:
            ctl.cancel.set()

    def cancel_all(self) -> None:
        for r in DB.list():
            self.cancel(r.id)

    def resume(self, item_id: int) -> None:
        DB.update(item_id, status=Status.QUEUED.value, errmsg=None)
        self.start(item_id)

    def _progress_hook(self, item_id: int, ctl: _TaskControl):
        last: dict[str, float] = {"time": 0.0, "downloaded": -1}

        def hook(d: dict) -> None:
            if ctl.cancel.is_set():
                raise Exception("Canceled by user")
            if ctl.pause.is_set():
                raise Exception("Paused by user")
            status = d.get("status")
            if status == "downloading":
                now = time.time()
                downloaded = d.get("downloaded_bytes") or 0
                if downloaded != last["downloaded"] and now - last["time"] > PROGRESS_UPDATE_THROTTLE:
                    DB.update(
                        item_id,
                        status=Status.DOWNLOADING.value,
                        downloaded_bytes=downloaded,
                        total_bytes=d.get("total_bytes")
                        or d.get("total_bytes_estimate"),
                        speed=d.get("speed"),
                        eta=d.get("eta"),
                        title=d.get("info_dict", {}).get("title"),
                    )
                    last["time"] = now
                    last["downloaded"] = downloaded
            elif status == "finished":
                DB.update(
                    item_id, status=Status.COMPLETED.value, filepath=d.get("filename")
                )

        return hook

    def _build_ydl_opts(
        self, item_id: int, ctl: _TaskControl, fmt: str, postprocessors: list[dict]
    ) -> Dict[str, Any]:
        """
        Build yt-dlp options dictionary with optimal settings.

        Args:
            item_id: Database ID of the download
            ctl: Task control object for pause/cancel
            fmt: Format string for video quality
            postprocessors: List of postprocessor configurations

        Returns:
            Dictionary of yt-dlp options
        """
        outtmpl = os.path.join(CONFIG.settings.download_dir, OUTPUT_TEMPLATE)

        # Get format sort from quality preset if available
        quality_preset = self._get_quality_preset(fmt)
        format_sort = quality_preset.get("format_sort") if quality_preset else [
            "res:2160", "res:1440", "res:1080", "res:720",
            "fps:60", "quality", "codec:h264", "size", "br", "asr"
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
        }

        if CONFIG.settings.cookies_file:
            opts["cookiefile"] = CONFIG.settings.cookies_file
        if postprocessors:
            opts["postprocessors"] = postprocessors
        return opts

    def _get_quality_preset(self, fmt: str) -> Optional[Dict[str, Any]]:
        """Get quality preset configuration if format matches a preset."""
        for preset_name, preset_config in QUALITY_PRESETS.items():
            if preset_config["format"] == fmt:
                return preset_config
        return None

    def _categorize_error(self, error_msg: str) -> str:
        """
        Categorize error messages into user-friendly descriptions.

        Args:
            error_msg: Raw error message from yt-dlp

        Returns:
            User-friendly error message
        """
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
        row = DB.get(item_id)
        if not row:
            return
        
        fmt = row.format or CONFIG.settings.format
        postprocessors: list[dict[str, Any]] = []
        
        # Always try to embed thumbnail for better quality control
        postprocessors.append({
            "key": "EmbedThumbnail",
            "already_have_thumbnail": False
        })
        
        if CONFIG.settings.embed_subtitles:
            postprocessors.append({
                "key": "FFmpegEmbedSubtitle",
                "already_have_subtitle": False
            })
            
        # Add FFmpeg optimization for better quality
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
                    
                    # Update title and format information
                    DB.update(
                        item_id,
                        title=info.get('title'),
                        format=info.get('format_id')
                    )
                    
                    # Actual download
                    ydl.download([row.url])
                
                DB.update(item_id, status=Status.COMPLETED.value)
                log.info("Completed id=%s", item_id)
                break  # Success, exit retry loop
                
            except Exception as e:
                msg = str(e)
                log.warning("Task id=%s attempt %d failed: %s", item_id, retry_count + 1, msg)

                if "Paused by user" in msg:
                    DB.update(item_id, status=Status.PAUSED.value, errmsg=None)
                    break
                elif "Canceled by user" in msg:
                    DB.update(item_id, status=Status.CANCELED.value, errmsg=None)
                    break
                else:
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        sleep_time = RETRY_BACKOFF_BASE * retry_count
                        log.info(f"Retrying in {sleep_time}s... (attempt {retry_count}/{max_retries})")
                        time.sleep(sleep_time)
                        continue
                    else:
                        user_friendly_error = self._categorize_error(msg)
                        DB.update(
                            item_id,
                            status=Status.ERROR.value,
                            errmsg=user_friendly_error
                        )
                        log.error(f"Download failed permanently: {user_friendly_error}")
