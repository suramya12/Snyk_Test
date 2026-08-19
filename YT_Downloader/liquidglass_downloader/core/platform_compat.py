"""
Platform compatibility and feature detection.

Provides graceful degradation and platform-specific handling for:
- Operating system differences (Windows, macOS, Linux)
- Python version compatibility
- Optional feature detection
- Safe fallbacks for missing dependencies
"""
from __future__ import annotations
import sys
import platform
import os
from typing import Optional, Dict, Any
from pathlib import Path

from .logging_util import get_logger

log = get_logger("platform")


class PlatformInfo:
    """
    Detect and provide platform-specific information.
    """

    def __init__(self):
        self.system = platform.system()
        self.release = platform.release()
        self.version = platform.version()
        self.machine = platform.machine()
        self.python_version = sys.version_info
        self.is_windows = self.system == "Windows"
        self.is_macos = self.system == "Darwin"
        self.is_linux = self.system == "Linux"
        self.is_64bit = sys.maxsize > 2**32

        log.info(f"Platform: {self.system} {self.release}")
        log.info(f"Python: {self.python_version.major}.{self.python_version.minor}.{self.python_version.micro}")
        log.info(f"Architecture: {'64-bit' if self.is_64bit else '32-bit'}")

    def check_python_version(self, minimum: tuple = (3, 10)) -> bool:
        """
        Check if Python version meets minimum requirement.

        Args:
            minimum: Minimum required version tuple (major, minor)

        Returns:
            True if version is sufficient
        """
        current = (self.python_version.major, self.python_version.minor)
        meets_requirement = current >= minimum

        if not meets_requirement:
            log.warning(
                f"Python {current[0]}.{current[1]} detected. "
                f"Minimum recommended: {minimum[0]}.{minimum[1]}"
            )

        return meets_requirement

    def get_recommended_ffmpeg_path(self) -> Optional[str]:
        """
        Get platform-specific FFmpeg path recommendations.

        Returns:
            Recommended FFmpeg path or None
        """
        if self.is_windows:
            # Common Windows locations
            candidates = [
                "C:\\ffmpeg\\bin\\ffmpeg.exe",
                "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
                os.path.expandvars("%LOCALAPPDATA%\\ffmpeg\\bin\\ffmpeg.exe"),
            ]
        elif self.is_macos:
            # Common macOS locations (Homebrew, MacPorts)
            candidates = [
                "/usr/local/bin/ffmpeg",
                "/opt/homebrew/bin/ffmpeg",
                "/opt/local/bin/ffmpeg",
            ]
        else:  # Linux
            candidates = [
                "/usr/bin/ffmpeg",
                "/usr/local/bin/ffmpeg",
                os.path.expanduser("~/.local/bin/ffmpeg"),
            ]

        for path in candidates:
            if os.path.exists(path):
                return path

        return None

    def get_default_browser(self) -> str:
        """
        Detect default browser for cookie extraction.

        Returns:
            Browser name (chrome, firefox, edge, safari, etc.)
        """
        if self.is_windows:
            # Windows: Most common is Chrome or Edge
            return "chrome"
        elif self.is_macos:
            # macOS: Safari or Chrome
            return "chrome"  # Chrome is more common for downloads
        else:  # Linux
            # Linux: Firefox or Chrome
            return "firefox"

    def check_dependencies(self) -> Dict[str, bool]:
        """
        Check for optional dependencies and features.

        Returns:
            Dict mapping feature names to availability
        """
        features = {}

        # Check for yt-dlp
        try:
            import yt_dlp
            features["yt_dlp"] = True
        except ImportError:
            features["yt_dlp"] = False
            log.error("yt-dlp not found! This is required for the application.")

        # Check for customtkinter (GUI)
        try:
            import customtkinter
            features["gui"] = True
        except ImportError:
            features["gui"] = False
            log.warning("customtkinter not found. GUI mode unavailable.")

        # Check for rich (CLI formatting)
        try:
            import rich
            features["rich_cli"] = True
        except ImportError:
            features["rich_cli"] = False
            log.warning("rich not found. CLI will use basic output.")

        # Check for Pillow (image processing)
        try:
            import PIL
            features["image_processing"] = True
        except ImportError:
            features["image_processing"] = False
            log.warning("Pillow not found. Thumbnail processing may be limited.")

        # Check for FFmpeg
        ffmpeg_path = self.get_recommended_ffmpeg_path()
        features["ffmpeg"] = ffmpeg_path is not None
        if not features["ffmpeg"]:
            log.warning("FFmpeg not found. Video conversion may be limited.")

        return features

    def get_clipboard_support(self) -> bool:
        """
        Check if clipboard operations are supported.

        Returns:
            True if clipboard can be accessed
        """
        # Clipboard support varies by platform and desktop environment
        if self.is_windows or self.is_macos:
            return True
        elif self.is_linux:
            # Linux clipboard depends on X11 or Wayland
            return "DISPLAY" in os.environ or "WAYLAND_DISPLAY" in os.environ
        return False

    def get_notification_support(self) -> bool:
        """
        Check if system notifications are supported.

        Returns:
            True if notifications can be shown
        """
        if self.is_windows:
            # Windows 10+ has native notifications
            return True
        elif self.is_macos:
            # macOS has notification center
            return True
        elif self.is_linux:
            # Linux has notify-send or similar
            try:
                import subprocess
                subprocess.run(["which", "notify-send"], capture_output=True, check=True)
                return True
            except Exception:
                return False
        return False

    def get_compatibility_report(self) -> str:
        """
        Generate a comprehensive compatibility report.

        Returns:
            Human-readable compatibility report
        """
        lines = [
            "=== Platform Compatibility Report ===",
            f"Operating System: {self.system} {self.release}",
            f"Python Version: {self.python_version.major}.{self.python_version.minor}.{self.python_version.micro}",
            f"Architecture: {'64-bit' if self.is_64bit else '32-bit'}",
            "",
            "Feature Availability:",
        ]

        features = self.check_dependencies()
        for feature, available in features.items():
            status = "✓ Available" if available else "✗ Not Available"
            lines.append(f"  {feature}: {status}")

        lines.extend([
            "",
            f"Clipboard Support: {'✓ Yes' if self.get_clipboard_support() else '✗ No'}",
            f"Notifications: {'✓ Yes' if self.get_notification_support() else '✗ No'}",
        ])

        ffmpeg = self.get_recommended_ffmpeg_path()
        if ffmpeg:
            lines.append(f"FFmpeg: {ffmpeg}")

        return "\n".join(lines)


# Singleton instance
_platform_info: Optional[PlatformInfo] = None


def get_platform_info() -> PlatformInfo:
    """Get or create the global platform info instance."""
    global _platform_info
    if _platform_info is None:
        _platform_info = PlatformInfo()
    return _platform_info


def check_compatibility() -> bool:
    """
    Check if the platform meets minimum requirements.

    Returns:
        True if compatible, False otherwise
    """
    info = get_platform_info()

    # Check Python version
    if not info.check_python_version((3, 10)):
        log.error("Python 3.10+ is required")
        return False

    # Check critical dependencies
    features = info.check_dependencies()
    if not features.get("yt_dlp", False):
        log.error("yt-dlp is required but not installed")
        return False

    log.info("Platform compatibility check passed")
    return True


def get_platform_specific_config() -> Dict[str, Any]:
    """
    Get platform-specific configuration overrides.

    Returns:
        Dict of platform-specific settings
    """
    info = get_platform_info()
    config = {}

    # Browser for cookies
    config["default_browser"] = info.get_default_browser()

    # FFmpeg path
    ffmpeg_path = info.get_recommended_ffmpeg_path()
    if ffmpeg_path:
        config["ffmpeg_location"] = ffmpeg_path

    # Clipboard monitoring
    config["clipboard_available"] = info.get_clipboard_support()

    # Notifications
    config["notifications_available"] = info.get_notification_support()

    return config


def show_compatibility_warnings():
    """Log warnings for any compatibility issues."""
    info = get_platform_info()
    features = info.check_dependencies()

    if not features.get("ffmpeg", False):
        log.warning(
            "FFmpeg is not installed. Video merging and conversion will be limited. "
            "Install FFmpeg for full functionality."
        )

    if not features.get("gui", False):
        log.warning(
            "GUI dependencies not available. Only CLI mode will work. "
            "Install 'customtkinter' for GUI support."
        )

    if not info.check_python_version((3, 10)):
        log.warning(
            "Python version is below recommended 3.10. "
            "Some features may not work correctly."
        )
