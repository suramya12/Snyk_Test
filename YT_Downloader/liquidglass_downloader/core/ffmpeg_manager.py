"""
FFmpeg detection, validation, and management.

Handles FFmpeg path detection across platforms
Validates FFmpeg installation and capabilities
Provides fallback behaviors when FFmpeg is unavailable
"""
from __future__ import annotations
import subprocess
import shutil
import re
from pathlib import Path
from typing import Optional, Dict, Tuple
from dataclasses import dataclass

from .platform_compat import get_platform_info
from .logging_util import get_logger

log = get_logger("ffmpeg")


@dataclass
class FFmpegInfo:
    """FFmpeg installation information."""
    path: str
    version: str
    has_audio_codecs: bool
    has_video_codecs: bool
    capabilities: Dict[str, bool]


class FFmpegManager:
    """
    Manages FFmpeg detection and validation.

    Features:
    - Auto-detection across platforms
    - Version checking
    - Capability validation
    - Fallback recommendations
    """

    # Minimum acceptable FFmpeg version
    MINIMUM_VERSION = (4, 0, 0)

    def __init__(self):
        self._cached_path: Optional[str] = None
        self._cached_info: Optional[FFmpegInfo] = None

    def find_ffmpeg(self, custom_path: Optional[str] = None) -> Optional[str]:
        """
        Find FFmpeg executable.

        Args:
            custom_path: Optional custom FFmpeg path

        Returns:
            Path to FFmpeg or None if not found
        """
        # Check cache first
        if self._cached_path:
            return self._cached_path

        # Try custom path first
        if custom_path:
            if self._validate_ffmpeg_path(custom_path):
                self._cached_path = custom_path
                return custom_path
            else:
                log.warning(f"Custom FFmpeg path invalid: {custom_path}")

        # Try platform-specific locations
        platform_info = get_platform_info()
        platform_path = platform_info.get_recommended_ffmpeg_path()

        if platform_path and self._validate_ffmpeg_path(platform_path):
            self._cached_path = platform_path
            return platform_path

        # Try system PATH
        system_ffmpeg = shutil.which('ffmpeg')
        if system_ffmpeg and self._validate_ffmpeg_path(system_ffmpeg):
            self._cached_path = system_ffmpeg
            return system_ffmpeg

        # Try common locations
        common_paths = self._get_common_paths()
        for path in common_paths:
            if self._validate_ffmpeg_path(path):
                self._cached_path = path
                return path

        log.warning("FFmpeg not found on system")
        return None

    def _get_common_paths(self) -> list[str]:
        """Get list of common FFmpeg installation paths."""
        platform_info = get_platform_info()

        if platform_info.is_windows:
            return [
                r"C:\ffmpeg\bin\ffmpeg.exe",
                r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
                str(Path.home() / "ffmpeg" / "bin" / "ffmpeg.exe"),
            ]
        elif platform_info.is_macos:
            return [
                "/usr/local/bin/ffmpeg",
                "/opt/homebrew/bin/ffmpeg",
                "/opt/local/bin/ffmpeg",
                str(Path.home() / ".local" / "bin" / "ffmpeg"),
            ]
        else:  # Linux
            return [
                "/usr/bin/ffmpeg",
                "/usr/local/bin/ffmpeg",
                "/snap/bin/ffmpeg",
                str(Path.home() / ".local" / "bin" / "ffmpeg"),
            ]

    def _validate_ffmpeg_path(self, path: str) -> bool:
        """
        Validate that path points to working FFmpeg.

        Args:
            path: Path to check

        Returns:
            True if valid FFmpeg executable
        """
        try:
            path_obj = Path(path)
            if not path_obj.exists():
                return False

            # Try to run ffmpeg -version
            result = subprocess.run(
                [path, '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )

            return result.returncode == 0 and 'ffmpeg version' in result.stdout.lower()

        except Exception as e:
            log.debug(f"FFmpeg validation failed for {path}: {e}")
            return False

    def get_ffmpeg_info(self, ffmpeg_path: Optional[str] = None) -> Optional[FFmpegInfo]:
        """
        Get detailed FFmpeg information.

        Args:
            ffmpeg_path: Optional path to FFmpeg

        Returns:
            FFmpegInfo or None if FFmpeg not available
        """
        # Check cache
        if self._cached_info and not ffmpeg_path:
            return self._cached_info

        # Find FFmpeg
        path = ffmpeg_path or self.find_ffmpeg()
        if not path:
            return None

        try:
            # Get version
            result = subprocess.run(
                [path, '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                return None

            output = result.stdout

            # Parse version
            version_match = re.search(r'ffmpeg version (\S+)', output)
            version = version_match.group(1) if version_match else "unknown"

            # Check capabilities
            capabilities = {
                'libx264': 'libx264' in output,
                'libx265': 'libx265' in output,
                'aac': 'aac' in output,
                'mp3': 'mp3' in output or 'libmp3lame' in output,
                'opus': 'opus' in output or 'libopus' in output,
            }

            info = FFmpegInfo(
                path=path,
                version=version,
                has_audio_codecs=any([capabilities['aac'], capabilities['mp3']]),
                has_video_codecs=any([capabilities['libx264'], capabilities['libx265']]),
                capabilities=capabilities
            )

            self._cached_info = info
            return info

        except Exception as e:
            log.error(f"Failed to get FFmpeg info: {e}")
            return None

    def check_version(self, version_string: str) -> Tuple[bool, str]:
        """
        Check if FFmpeg version meets minimum requirement.

        Args:
            version_string: Version string (e.g., "4.4.2")

        Returns:
            Tuple of (meets_requirement, message)
        """
        try:
            # Parse version
            version_match = re.search(r'(\d+)\.(\d+)\.(\d+)', version_string)
            if not version_match:
                return False, "Could not parse version"

            major, minor, patch = map(int, version_match.groups())
            version_tuple = (major, minor, patch)

            if version_tuple >= self.MINIMUM_VERSION:
                return True, f"Version {version_string} is acceptable"
            else:
                min_ver = '.'.join(map(str, self.MINIMUM_VERSION))
                return False, f"Version {version_string} is below minimum {min_ver}"

        except Exception as e:
            return False, f"Version check failed: {e}"

    def is_available(self) -> bool:
        """Check if FFmpeg is available."""
        return self.find_ffmpeg() is not None

    def get_merge_command(
        self,
        video_path: str,
        audio_path: str,
        output_path: str,
        ffmpeg_path: Optional[str] = None
    ) -> list[str]:
        """
        Generate FFmpeg merge command.

        Args:
            video_path: Path to video file
            audio_path: Path to audio file
            output_path: Path to output file
            ffmpeg_path: Optional FFmpeg path

        Returns:
            Command list for subprocess
        """
        path = ffmpeg_path or self.find_ffmpeg()
        if not path:
            raise RuntimeError("FFmpeg not found")

        return [
            path,
            '-i', video_path,
            '-i', audio_path,
            '-c:v', 'copy',      # Copy video stream
            '-c:a', 'copy',      # Copy audio stream
            '-y',                # Overwrite output
            output_path
        ]

    def merge_files(
        self,
        video_path: str,
        audio_path: str,
        output_path: str,
        ffmpeg_path: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Merge video and audio files using FFmpeg.

        Args:
            video_path: Path to video file
            audio_path: Path to audio file
            output_path: Path to output file
            ffmpeg_path: Optional FFmpeg path

        Returns:
            Tuple of (success, message)
        """
        try:
            cmd = self.get_merge_command(video_path, audio_path, output_path, ffmpeg_path)

            log.info(f"Merging {video_path} + {audio_path} -> {output_path}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode == 0:
                log.info("Merge successful")
                return True, "Merge completed successfully"
            else:
                error_msg = result.stderr or "Unknown error"
                log.error(f"Merge failed: {error_msg}")
                return False, f"Merge failed: {error_msg}"

        except subprocess.TimeoutExpired:
            return False, "Merge timed out after 5 minutes"
        except Exception as e:
            return False, f"Merge error: {str(e)}"

    def get_installation_instructions(self) -> str:
        """
        Get platform-specific FFmpeg installation instructions.

        Returns:
            Installation instructions string
        """
        platform_info = get_platform_info()

        if platform_info.is_windows:
            return """
FFmpeg Installation for Windows:

1. Download FFmpeg from: https://ffmpeg.org/download.html
   (Choose "Windows builds from gyan.dev" or "BtbN builds")

2. Extract the ZIP file to C:\\ffmpeg

3. Add to PATH:
   - Open System Properties → Environment Variables
   - Edit "Path" variable
   - Add: C:\\ffmpeg\\bin

4. Restart the application

Or use package manager:
   winget install ffmpeg
   or
   choco install ffmpeg
"""
        elif platform_info.is_macos:
            return """
FFmpeg Installation for macOS:

Using Homebrew (recommended):
   brew install ffmpeg

Using MacPorts:
   sudo port install ffmpeg

Or download from: https://ffmpeg.org/download.html
"""
        else:  # Linux
            return """
FFmpeg Installation for Linux:

Ubuntu/Debian:
   sudo apt update
   sudo apt install ffmpeg

Fedora:
   sudo dnf install ffmpeg

Arch Linux:
   sudo pacman -S ffmpeg

Or download from: https://ffmpeg.org/download.html
"""

    def clear_cache(self):
        """Clear cached FFmpeg information."""
        self._cached_path = None
        self._cached_info = None


# Global instance
_ffmpeg_manager = FFmpegManager()


def get_ffmpeg_manager() -> FFmpegManager:
    """Get global FFmpeg manager instance."""
    return _ffmpeg_manager


def is_ffmpeg_available() -> bool:
    """Quick check if FFmpeg is available."""
    return _ffmpeg_manager.is_available()


def get_ffmpeg_path() -> Optional[str]:
    """Get FFmpeg path if available."""
    return _ffmpeg_manager.find_ffmpeg()


def get_installation_guide() -> str:
    """Get FFmpeg installation instructions."""
    return _ffmpeg_manager.get_installation_instructions()
