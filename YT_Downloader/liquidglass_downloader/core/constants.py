"""
Application-wide constants and configuration defaults.
"""
from __future__ import annotations

# Download Manager Constants
DEFAULT_CONCURRENT_DOWNLOADS = 3
MAX_CONCURRENT_DOWNLOADS = 10
MIN_CONCURRENT_DOWNLOADS = 1

# Retry Configuration
DEFAULT_MAX_RETRIES = 3
YTDLP_RETRIES = 5
FRAGMENT_RETRIES = 5

# Progress Update Throttling (seconds)
PROGRESS_UPDATE_THROTTLE = 0.5
UI_REFRESH_INTERVAL = 1.0  # 1 second

# Retry Backoff (seconds)
RETRY_BACKOFF_BASE = 5
RETRY_SLEEP_MULTIPLIER = 5

# UI Constants
TOAST_DURATION_MS = 2500
CLIPBOARD_POLL_INTERVAL_MS = 2000
CLIPBOARD_DEBOUNCE_MS = 500

# Database Constants
MAX_HISTORY_ITEMS = 10000
DATABASE_VERSION = 1

# Logging Constants
LOG_BACKUP_COUNT = 3
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Network Constants
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
    "Mobile/15E148 Safari/604.1"
)

# File Templates
OUTPUT_TEMPLATE = "%(title)s [%(id)s].%(ext)s"

# Quality Presets
QUALITY_PRESETS = {
    "best": {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "description": "Best available quality (4K/1440p/1080p)",
        "format_sort": ["res:2160", "res:1440", "res:1080", "fps:60", "quality", "codec:h264"]
    },
    "1080p": {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]",
        "description": "1080p Full HD",
        "format_sort": ["res:1080", "fps:60", "quality", "codec:h264"]
    },
    "720p": {
        "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
        "description": "720p HD",
        "format_sort": ["res:720", "fps:60", "quality", "codec:h264"]
    },
    "480p": {
        "format": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]",
        "description": "480p SD",
        "format_sort": ["res:480", "quality", "codec:h264"]
    },
    "audio": {
        "format": "bestaudio/best",
        "description": "Audio only (best quality)",
        "format_sort": ["abr", "asr"]
    },
}

# Format String (backwards compatibility)
DEFAULT_FORMAT = QUALITY_PRESETS["best"]["format"]

# Error Messages
ERROR_MESSAGES = {
    "network": "Network error. Please check your connection and try again.",
    "not_found": "Video not found or has been removed.",
    "private": "This video is private or restricted.",
    "geo_blocked": "This video is not available in your region.",
    "copyright": "This video has been removed due to copyright issues.",
    "live_stream": "Live streams cannot be downloaded until they complete.",
    "timeout": "Connection timed out. Please try again.",
    "format_unavailable": "The requested format is not available for this video.",
    "metadata": "Failed to fetch video information. The URL may be invalid.",
    "permission": "Permission denied. Check file permissions and disk space.",
    "unknown": "An unexpected error occurred. Please try again or report this issue.",
}

# Status Colors (for UI)
STATUS_COLORS = {
    "queued": "#888888",
    "downloading": "#3b82f6",
    "completed": "#22c55e",
    "error": "#ef4444",
    "paused": "#f59e0b",
    "canceled": "#6b7280",
}

# Download Options
YTDLP_DEFAULT_OPTIONS = {
    "continuedl": True,
    "ignoreerrors": False,
    "noprogress": True,
    "nopart": False,
    "writethumbnail": True,
    "verbose": True,
    "skip_unavailable_fragments": False,
}

# Platform-specific settings
YOUTUBE_EXTRACTOR_ARGS = {
    "youtube": {
        "player_client": ["ios"],
        "player_skip": ["webpage", "js"]
    }
}

# HTTP Headers
HTTP_HEADERS = {
    "Referer": "https://www.youtube.com/",
}
