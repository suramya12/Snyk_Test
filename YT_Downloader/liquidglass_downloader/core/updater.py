"""
Dependency update and version management system.

Provides automatic updates for critical dependencies (especially yt-dlp)
and checks for outdated packages with optional update capability.
"""
from __future__ import annotations
import subprocess
import sys
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from .config import CONFIG
from .logging_util import get_logger

log = get_logger("updater")

# Critical packages that should be auto-updated
CRITICAL_PACKAGES = ["yt-dlp"]

# Packages to check for updates
MONITORED_PACKAGES = [
    "yt-dlp",
    "pydantic",
    "customtkinter",
    "pillow",
    "requests",
    "rich",
]

# Update check cache duration (24 hours)
UPDATE_CHECK_INTERVAL = timedelta(hours=24)


class DependencyUpdater:
    """
    Manages dependency updates and version checking.

    Features:
    - Auto-update critical packages (yt-dlp)
    - Check for outdated dependencies
    - Cache update checks to avoid excessive network requests
    - Graceful error handling
    """

    def __init__(self):
        self.cache_file = CONFIG.data_dir / "update_cache.json"
        self.update_cache = self._load_cache()

    def _load_cache(self) -> Dict:
        """Load cached update information."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                log.warning(f"Failed to load update cache: {e}")
        return {
            "last_check": None,
            "versions": {},
            "outdated": {}
        }

    def _save_cache(self):
        """Save update cache to disk."""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.update_cache, f, indent=2)
        except Exception as e:
            log.warning(f"Failed to save update cache: {e}")

    def should_check_updates(self) -> bool:
        """
        Determine if we should check for updates.

        Returns:
            True if enough time has passed since last check
        """
        if not self.update_cache.get("last_check"):
            return True

        try:
            last_check = datetime.fromisoformat(self.update_cache["last_check"])
            return datetime.now() - last_check > UPDATE_CHECK_INTERVAL
        except Exception:
            return True

    def get_installed_version(self, package: str) -> Optional[str]:
        """
        Get installed version of a package.

        Args:
            package: Package name

        Returns:
            Version string or None if not installed
        """
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", package],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if line.startswith('Version:'):
                        return line.split(':', 1)[1].strip()
        except Exception as e:
            log.warning(f"Failed to get version for {package}: {e}")
        return None

    def get_latest_version(self, package: str) -> Optional[str]:
        """
        Get latest available version from PyPI.

        Args:
            package: Package name

        Returns:
            Latest version string or None if unavailable
        """
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "index", "versions", package],
                capture_output=True,
                text=True,
                timeout=15
            )
            if result.returncode == 0:
                # Parse output to find available versions
                for line in result.stdout.split('\n'):
                    if 'Available versions:' in line:
                        versions = line.split(':', 1)[1].strip()
                        # Get first version (latest)
                        if versions:
                            return versions.split(',')[0].strip()
        except Exception as e:
            log.warning(f"Failed to check latest version for {package}: {e}")
        return None

    def check_outdated_packages(self) -> Dict[str, Tuple[str, str]]:
        """
        Check which monitored packages are outdated.

        Returns:
            Dict mapping package names to (current_version, latest_version) tuples
        """
        if not self.should_check_updates():
            log.info("Using cached update information")
            return self.update_cache.get("outdated", {})

        log.info("Checking for package updates...")
        outdated = {}

        for package in MONITORED_PACKAGES:
            try:
                current = self.get_installed_version(package)
                if not current:
                    log.warning(f"Package {package} not found")
                    continue

                latest = self.get_latest_version(package)
                if not latest:
                    log.warning(f"Could not fetch latest version for {package}")
                    continue

                if current != latest:
                    outdated[package] = (current, latest)
                    log.info(f"{package}: {current} -> {latest} available")

            except Exception as e:
                log.error(f"Error checking {package}: {e}")

        # Update cache
        self.update_cache["last_check"] = datetime.now().isoformat()
        self.update_cache["outdated"] = outdated
        self._save_cache()

        return outdated

    def update_package(self, package: str, force: bool = False) -> bool:
        """
        Update a specific package to the latest version.

        Args:
            package: Package name to update
            force: Force update even if not in critical list

        Returns:
            True if update succeeded, False otherwise
        """
        if not force and package not in CRITICAL_PACKAGES:
            log.warning(f"Skipping non-critical package update: {package}")
            return False

        log.info(f"Updating {package}...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", package],
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode == 0:
                log.info(f"Successfully updated {package}")
                # Clear cache to force recheck
                self.update_cache["last_check"] = None
                self._save_cache()
                return True
            else:
                log.error(f"Failed to update {package}: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            log.error(f"Update timed out for {package}")
            return False
        except Exception as e:
            log.error(f"Error updating {package}: {e}")
            return False

    def update_critical_packages(self) -> Dict[str, bool]:
        """
        Auto-update all critical packages.

        Returns:
            Dict mapping package names to success status
        """
        results = {}

        for package in CRITICAL_PACKAGES:
            log.info(f"Auto-updating critical package: {package}")
            results[package] = self.update_package(package, force=True)

        return results

    def update_yt_dlp(self) -> bool:
        """
        Update yt-dlp specifically (most important for functionality).

        Returns:
            True if successful, False otherwise
        """
        log.info("Updating yt-dlp to latest version...")
        return self.update_package("yt-dlp", force=True)

    def get_update_summary(self) -> str:
        """
        Get a human-readable summary of available updates.

        Returns:
            Summary string
        """
        outdated = self.check_outdated_packages()

        if not outdated:
            return "All packages are up to date!"

        lines = ["Available updates:"]
        for package, (current, latest) in outdated.items():
            lines.append(f"  - {package}: {current} -> {latest}")

        return "\n".join(lines)


# Singleton instance
_updater: Optional[DependencyUpdater] = None


def get_updater() -> DependencyUpdater:
    """Get or create the global updater instance."""
    global _updater
    if _updater is None:
        _updater = DependencyUpdater()
    return _updater


def auto_update_on_startup(enable_critical_only: bool = True) -> Dict[str, bool]:
    """
    Perform automatic updates on application startup.

    Args:
        enable_critical_only: Only update critical packages (default: True)

    Returns:
        Dict mapping package names to update success status
    """
    updater = get_updater()

    if enable_critical_only:
        log.info("Performing critical package updates...")
        return updater.update_critical_packages()
    else:
        log.info("Checking all packages for updates...")
        outdated = updater.check_outdated_packages()
        results = {}

        for package in outdated.keys():
            results[package] = updater.update_package(package, force=True)

        return results


def check_updates_async() -> Dict[str, Tuple[str, str]]:
    """
    Check for updates asynchronously (non-blocking).

    Returns:
        Dict of outdated packages
    """
    updater = get_updater()
    return updater.check_outdated_packages()
