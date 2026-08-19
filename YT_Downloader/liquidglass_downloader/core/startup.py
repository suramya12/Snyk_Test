"""
Application startup initialization and health checks.

Performs essential startup tasks including:
- Platform compatibility verification
- Dependency version checking and updates
- Configuration validation
- Database initialization
- System health checks
"""
from __future__ import annotations
import threading
from typing import Dict, List, Optional

from .config import CONFIG
from .platform_compat import (
    get_platform_info,
    check_compatibility,
    show_compatibility_warnings,
    get_platform_specific_config,
)
from .updater import get_updater, auto_update_on_startup
from .logging_util import get_logger

log = get_logger("startup")


class StartupResult:
    """
    Container for startup initialization results.
    """

    def __init__(self):
        self.success = True
        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.updates_performed: Dict[str, bool] = {}
        self.platform_info: Optional[Dict] = None

    def add_warning(self, message: str):
        """Add a non-critical warning."""
        self.warnings.append(message)
        log.warning(message)

    def add_error(self, message: str):
        """Add a critical error."""
        self.errors.append(message)
        self.success = False
        log.error(message)

    def get_summary(self) -> str:
        """Get human-readable summary of startup results."""
        lines = ["=== Startup Summary ==="]

        if self.success:
            lines.append("Status: ✓ Success")
        else:
            lines.append("Status: ✗ Failed")

        if self.updates_performed:
            lines.append("\nUpdates Performed:")
            for package, success in self.updates_performed.items():
                status = "✓" if success else "✗"
                lines.append(f"  {status} {package}")

        if self.warnings:
            lines.append("\nWarnings:")
            for warning in self.warnings:
                lines.append(f"  ⚠ {warning}")

        if self.errors:
            lines.append("\nErrors:")
            for error in self.errors:
                lines.append(f"  ✗ {error}")

        return "\n".join(lines)


def perform_startup_checks(async_updates: bool = True) -> StartupResult:
    """
    Perform comprehensive startup initialization.

    Args:
        async_updates: Run dependency updates asynchronously (default: True)

    Returns:
        StartupResult with detailed initialization status
    """
    result = StartupResult()
    log.info("Starting application initialization...")

    # Step 1: Platform compatibility check
    log.info("Checking platform compatibility...")
    try:
        if not check_compatibility():
            result.add_error("Platform compatibility check failed")
            return result  # Fatal error, cannot continue

        # Show non-fatal compatibility warnings
        show_compatibility_warnings()

        # Get platform-specific configuration
        platform_config = get_platform_specific_config()
        result.platform_info = platform_config

        # Apply platform-specific settings if not already configured
        if CONFIG.settings.browser_for_cookies == "chrome":
            CONFIG.settings.browser_for_cookies = platform_config.get(
                "default_browser", "chrome"
            )

    except Exception as e:
        result.add_error(f"Platform check failed: {str(e)}")
        return result

    # Step 2: Dependency updates
    if CONFIG.settings.auto_update_enabled:
        log.info("Auto-update is enabled")

        if async_updates:
            # Run updates in background thread to not block startup
            def update_thread():
                try:
                    updates = auto_update_on_startup(
                        enable_critical_only=CONFIG.settings.auto_update_ytdlp_only
                    )
                    result.updates_performed = updates

                    # Log update results
                    for package, success in updates.items():
                        if success:
                            log.info(f"Successfully updated {package}")
                        else:
                            result.add_warning(f"Failed to update {package}")

                except Exception as e:
                    result.add_warning(f"Auto-update failed: {str(e)}")

            thread = threading.Thread(target=update_thread, daemon=True)
            thread.start()
            log.info("Auto-update running in background...")

        else:
            # Run updates synchronously (blocks startup)
            try:
                result.updates_performed = auto_update_on_startup(
                    enable_critical_only=CONFIG.settings.auto_update_ytdlp_only
                )

                for package, success in result.updates_performed.items():
                    if success:
                        log.info(f"Successfully updated {package}")
                    else:
                        result.add_warning(f"Failed to update {package}")

            except Exception as e:
                result.add_warning(f"Auto-update failed: {str(e)}")

    # Step 3: Check for available updates (if enabled)
    if CONFIG.settings.check_updates_on_startup and not CONFIG.settings.auto_update_enabled:
        log.info("Checking for available updates...")
        try:
            updater = get_updater()
            outdated = updater.check_outdated_packages()

            if outdated and CONFIG.settings.notify_updates_available:
                result.add_warning(
                    f"{len(outdated)} package(s) have updates available: "
                    f"{', '.join(outdated.keys())}"
                )

        except Exception as e:
            log.warning(f"Failed to check for updates: {str(e)}")

    # Step 4: Validate configuration
    log.info("Validating configuration...")
    try:
        # Ensure download directory exists
        from pathlib import Path
        download_dir = Path(CONFIG.settings.download_dir)
        if not download_dir.exists():
            try:
                download_dir.mkdir(parents=True, exist_ok=True)
                log.info(f"Created download directory: {download_dir}")
            except Exception as e:
                result.add_warning(
                    f"Could not create download directory: {str(e)}"
                )

        # Validate concurrent downloads setting
        if CONFIG.settings.concurrent_downloads < 1:
            CONFIG.settings.concurrent_downloads = 1
            result.add_warning("Adjusted concurrent downloads to minimum value (1)")

        if CONFIG.settings.concurrent_downloads > 10:
            CONFIG.settings.concurrent_downloads = 10
            result.add_warning("Adjusted concurrent downloads to maximum value (10)")

    except Exception as e:
        result.add_warning(f"Configuration validation issue: {str(e)}")

    # Step 5: Database verification
    log.info("Verifying database...")
    try:
        from .db import DB_INSTANCE

        # Test database connection
        stats = DB_INSTANCE.get_statistics()
        log.info(f"Database connected. Items in database: {sum(stats.values())}")

    except Exception as e:
        result.add_error(f"Database initialization failed: {str(e)}")

    # Final summary
    log.info("Startup initialization complete")
    log.info(result.get_summary())

    return result


def quick_startup() -> bool:
    """
    Perform minimal startup checks without updates.

    Useful for CLI mode or when full initialization is not needed.

    Returns:
        True if basic startup succeeded
    """
    log.info("Performing quick startup check...")

    try:
        # Basic compatibility check
        if not check_compatibility():
            log.error("Basic compatibility check failed")
            return False

        # Verify database
        from .db import DB_INSTANCE
        DB_INSTANCE.get_statistics()

        log.info("Quick startup successful")
        return True

    except Exception as e:
        log.error(f"Quick startup failed: {str(e)}")
        return False


def get_startup_info() -> Dict:
    """
    Get startup information for display.

    Returns:
        Dict with version, platform, and dependency info
    """
    info = {}

    try:
        # Version info
        info["app_version"] = "2.3.0"

        # Platform info
        platform_info = get_platform_info()
        info["platform"] = {
            "system": platform_info.system,
            "python_version": f"{platform_info.python_version.major}.{platform_info.python_version.minor}.{platform_info.python_version.micro}",
            "architecture": "64-bit" if platform_info.is_64bit else "32-bit",
        }

        # Dependencies
        info["features"] = platform_info.check_dependencies()

        # Update status
        updater = get_updater()
        info["last_update_check"] = updater.update_cache.get("last_check", "Never")

    except Exception as e:
        log.warning(f"Failed to gather startup info: {str(e)}")

    return info


# Initialize on module import (non-blocking)
_startup_result: Optional[StartupResult] = None


def get_last_startup_result() -> Optional[StartupResult]:
    """Get the result from the last startup check."""
    return _startup_result


def initialize_application(async_mode: bool = True) -> StartupResult:
    """
    Initialize the application with full checks and updates.

    Args:
        async_mode: Run updates asynchronously (default: True)

    Returns:
        StartupResult with initialization details
    """
    global _startup_result
    _startup_result = perform_startup_checks(async_updates=async_mode)
    return _startup_result
