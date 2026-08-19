"""
UI utility functions for status colors and formatting.
"""
from __future__ import annotations

from ..core.models import Status
from ..core.constants import STATUS_COLORS as _COLORS


# Map Status enum to color tuples for light/dark mode
_STATUS_COLORS = {
    Status.COMPLETED: (_COLORS["completed"], _COLORS["completed"]),
    Status.ERROR: (_COLORS["error"], _COLORS["error"]),
    Status.PAUSED: (_COLORS["paused"], _COLORS["paused"]),
    Status.CANCELED: (_COLORS["canceled"], _COLORS["canceled"]),
    Status.DOWNLOADING: (_COLORS["downloading"], _COLORS["downloading"]),
    Status.QUEUED: (_COLORS["queued"], _COLORS["queued"]),
}


def status_color(status: Status | str) -> tuple[str, str]:
    """
    Return color tuple for a given download status.

    Args:
        status: Status enum or status string

    Returns:
        Tuple of (light_color, dark_color) for the status
    """
    if isinstance(status, str):
        try:
            status = Status(status)
        except ValueError:
            return _STATUS_COLORS[Status.QUEUED]
    return _STATUS_COLORS.get(status, _STATUS_COLORS[Status.QUEUED])


def format_bytes(bytes_val: int) -> str:
    """
    Format bytes into human-readable string.

    Args:
        bytes_val: Number of bytes

    Returns:
        Formatted string (e.g., "1.5 MB", "2.3 GB")
    """
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 ** 2:
        return f"{bytes_val / 1024:.1f} KB"
    elif bytes_val < 1024 ** 3:
        return f"{bytes_val / (1024 ** 2):.1f} MB"
    else:
        return f"{bytes_val / (1024 ** 3):.2f} GB"


def format_speed(speed: float) -> str:
    """
    Format download speed into human-readable string.

    Args:
        speed: Speed in bytes per second

    Returns:
        Formatted string (e.g., "1.5 MB/s")
    """
    if speed < 1024:
        return f"{speed:.0f} B/s"
    elif speed < 1024 ** 2:
        return f"{speed / 1024:.1f} KB/s"
    else:
        return f"{speed / (1024 ** 2):.1f} MB/s"


def format_duration(seconds: int) -> str:
    """
    Format duration in seconds to HH:MM:SS.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted time string
    """
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}m {secs}s"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m"

