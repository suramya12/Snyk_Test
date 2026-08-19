"""
Smart quality selection and format management.

Implements the quality hierarchy: 8K → 4K → 1440p → 1080p
Enforces minimum quality policy (1080p by default)
Handles quality confirmation dialogs
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import IntEnum

from .logging_util import get_logger

log = get_logger("quality")


class QualityLevel(IntEnum):
    """Video quality levels in priority order."""
    Q_8K = 4320      # 8K (7680×4320)
    Q_4K = 2160      # 4K (3840×2160)
    Q_1440P = 1440   # 1440p (2560×1440)
    Q_1080P = 1080   # 1080p (1920×1080)
    Q_720P = 720     # 720p (1280×720)
    Q_480P = 480     # 480p (854×480)
    Q_360P = 360     # 360p (640×360)
    Q_240P = 240     # 240p (426×240)


@dataclass
class FormatInfo:
    """Information about an available format."""
    format_id: str
    height: int
    width: int
    fps: Optional[int]
    vcodec: str
    acodec: str
    filesize: Optional[int]
    ext: str
    has_video: bool
    has_audio: bool
    quality_label: str  # e.g., "4K", "1080p"

    @property
    def resolution(self) -> str:
        """Get resolution string."""
        return f"{self.width}x{self.height}"

    @property
    def is_combined(self) -> bool:
        """Check if format has both video and audio."""
        return self.has_video and self.has_audio


class QualityPolicy:
    """
    Quality policy enforcement.

    Default policy: Minimum 1080p
    """

    # Minimum acceptable quality (can be configured)
    MINIMUM_HEIGHT = QualityLevel.Q_1080P

    # Preferred quality order
    QUALITY_PRIORITY = [
        QualityLevel.Q_8K,
        QualityLevel.Q_4K,
        QualityLevel.Q_1440P,
        QualityLevel.Q_1080P,
    ]

    @classmethod
    def get_quality_label(cls, height: int) -> str:
        """Get human-readable quality label."""
        if height >= QualityLevel.Q_8K:
            return "8K"
        elif height >= QualityLevel.Q_4K:
            return "4K"
        elif height >= QualityLevel.Q_1440P:
            return "1440p"
        elif height >= QualityLevel.Q_1080P:
            return "1080p"
        elif height >= QualityLevel.Q_720P:
            return "720p"
        elif height >= QualityLevel.Q_480P:
            return "480p"
        elif height >= QualityLevel.Q_360P:
            return "360p"
        else:
            return "240p"

    @classmethod
    def meets_minimum(cls, height: int) -> bool:
        """Check if quality meets minimum requirement."""
        return height >= cls.MINIMUM_HEIGHT

    @classmethod
    def requires_confirmation(cls, height: int) -> bool:
        """
        Check if quality requires user confirmation.

        Returns True if quality is >= 1080p but < 4K
        """
        return (height >= QualityLevel.Q_1080P and
                height < QualityLevel.Q_4K)

    @classmethod
    def should_reject(cls, height: int) -> bool:
        """Check if quality should be rejected (below minimum)."""
        return height < cls.MINIMUM_HEIGHT


class QualitySelector:
    """
    Smart quality selector implementing the hierarchy.

    Priority: 8K → 4K → 1440p → 1080p
    """

    def __init__(self):
        self.policy = QualityPolicy()

    def parse_formats(self, formats: List[Dict[str, Any]]) -> List[FormatInfo]:
        """
        Parse yt-dlp format list into FormatInfo objects.

        Args:
            formats: List of format dicts from yt-dlp

        Returns:
            List of FormatInfo objects
        """
        parsed = []

        for fmt in formats:
            try:
                height = fmt.get('height') or 0
                width = fmt.get('width') or 0

                if height == 0:
                    continue  # Skip audio-only or unknown formats

                format_info = FormatInfo(
                    format_id=fmt.get('format_id', ''),
                    height=height,
                    width=width,
                    fps=fmt.get('fps'),
                    vcodec=fmt.get('vcodec', 'none'),
                    acodec=fmt.get('acodec', 'none'),
                    filesize=fmt.get('filesize'),
                    ext=fmt.get('ext', 'mp4'),
                    has_video=fmt.get('vcodec', 'none') != 'none',
                    has_audio=fmt.get('acodec', 'none') != 'none',
                    quality_label=self.policy.get_quality_label(height)
                )

                parsed.append(format_info)

            except Exception as e:
                log.warning(f"Failed to parse format: {e}")
                continue

        return parsed

    def get_best_quality(self, formats: List[FormatInfo]) -> Optional[FormatInfo]:
        """
        Get the best quality format according to priority.

        Args:
            formats: List of available formats

        Returns:
            Best quality format or None
        """
        if not formats:
            return None

        # Sort by height (descending), then fps (descending)
        sorted_formats = sorted(
            formats,
            key=lambda f: (f.height, f.fps or 0),
            reverse=True
        )

        return sorted_formats[0] if sorted_formats else None

    def select_format(
        self,
        formats: List[FormatInfo],
        prefer_combined: bool = True
    ) -> Tuple[Optional[FormatInfo], str]:
        """
        Select best format according to quality policy.

        Args:
            formats: Available formats
            prefer_combined: Prefer formats with both video and audio

        Returns:
            Tuple of (selected_format, decision_reason)

        Decision reasons:
            - "best_quality": Selected best available quality
            - "needs_confirmation": Quality >= 1080p but < 4K, needs user confirmation
            - "below_minimum": Quality < 1080p, should be rejected
            - "no_formats": No suitable formats found
        """
        if not formats:
            return None, "no_formats"

        # Filter by combined/separate if preferred
        if prefer_combined:
            combined = [f for f in formats if f.is_combined]
            if combined:
                formats = combined

        # Get best quality
        best = self.get_best_quality(formats)

        if not best:
            return None, "no_formats"

        # Apply policy
        if self.policy.should_reject(best.height):
            log.warning(f"Best quality {best.quality_label} is below minimum 1080p")
            return best, "below_minimum"

        if self.policy.requires_confirmation(best.height):
            log.info(f"Quality {best.quality_label} requires user confirmation")
            return best, "needs_confirmation"

        # 4K or better - perfect!
        log.info(f"Selected best quality: {best.quality_label}")
        return best, "best_quality"

    def get_format_string_for_quality(
        self,
        quality_height: int,
        prefer_mp4: bool = True
    ) -> str:
        """
        Generate yt-dlp format string for target quality.

        Args:
            quality_height: Target height (e.g., 2160 for 4K)
            prefer_mp4: Prefer MP4 container

        Returns:
            yt-dlp format string
        """
        # Build format filter
        ext_filter = "[ext=mp4]" if prefer_mp4 else ""

        # Prefer formats with FPS >= 60
        format_str = (
            f"bestvideo[height<={quality_height}]{ext_filter}[fps>=60]+"
            f"bestaudio{ext_filter}/bestvideo[height<={quality_height}]{ext_filter}+"
            f"bestaudio{ext_filter}/best[height<={quality_height}]"
        )

        return format_str

    def generate_quality_formats(self) -> Dict[str, str]:
        """
        Generate format strings for all quality levels.

        Returns:
            Dict mapping quality labels to format strings
        """
        return {
            "8K": self.get_format_string_for_quality(QualityLevel.Q_8K),
            "4K": self.get_format_string_for_quality(QualityLevel.Q_4K),
            "1440p": self.get_format_string_for_quality(QualityLevel.Q_1440P),
            "1080p": self.get_format_string_for_quality(QualityLevel.Q_1080P),
            "720p": self.get_format_string_for_quality(QualityLevel.Q_720P),
            "best": "bestvideo+bestaudio/best",
        }

    def analyze_available_qualities(
        self,
        formats: List[FormatInfo]
    ) -> Dict[str, Any]:
        """
        Analyze available qualities for display to user.

        Args:
            formats: List of available formats

        Returns:
            Analysis dict with quality breakdown
        """
        if not formats:
            return {
                "has_8k": False,
                "has_4k": False,
                "has_1440p": False,
                "has_1080p": False,
                "best_quality": None,
                "best_height": 0,
                "qualities": []
            }

        # Group by quality
        qualities = {}
        for fmt in formats:
            label = fmt.quality_label
            if label not in qualities:
                qualities[label] = []
            qualities[label].append(fmt)

        best = self.get_best_quality(formats)

        return {
            "has_8k": any(f.height >= QualityLevel.Q_8K for f in formats),
            "has_4k": any(f.height >= QualityLevel.Q_4K for f in formats),
            "has_1440p": any(f.height >= QualityLevel.Q_1440P for f in formats),
            "has_1080p": any(f.height >= QualityLevel.Q_1080P for f in formats),
            "best_quality": best.quality_label if best else None,
            "best_height": best.height if best else 0,
            "qualities": sorted(qualities.keys(),
                              key=lambda q: max(f.height for f in qualities[q]),
                              reverse=True)
        }


# Global instance
_quality_selector = QualitySelector()


def get_quality_selector() -> QualitySelector:
    """Get global quality selector instance."""
    return _quality_selector


def analyze_video_quality(url: str, ydl_opts: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Analyze available video qualities without downloading.

    Args:
        url: Video URL
        ydl_opts: Optional yt-dlp options

    Returns:
        Quality analysis dict
    """
    from yt_dlp import YoutubeDL

    opts = ydl_opts or {}
    opts.update({
        'quiet': True,
        'skip_download': True,
        'no_warnings': True,
    })

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

            if not info:
                return {"error": "Could not extract video information"}

            formats = info.get('formats', [])
            selector = get_quality_selector()
            parsed_formats = selector.parse_formats(formats)
            analysis = selector.analyze_available_qualities(parsed_formats)

            # Add video metadata
            analysis.update({
                "title": info.get('title'),
                "duration": info.get('duration'),
                "uploader": info.get('uploader'),
                "thumbnail": info.get('thumbnail'),
            })

            return analysis

    except Exception as e:
        log.error(f"Quality analysis failed: {e}")
        return {"error": str(e)}
