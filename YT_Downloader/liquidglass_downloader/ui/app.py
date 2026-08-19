"""
Main application window with sidebar navigation and view management.
"""
from __future__ import annotations
import customtkinter as ctk
import re
import time
import threading

from .theme import init_theme
from ..core.config import CONFIG
from ..core.downloader import DownloadManager
from ..core.constants import CLIPBOARD_POLL_INTERVAL_MS, CLIPBOARD_DEBOUNCE_MS
from ..core.validation import is_valid_url
from ..core.startup import initialize_application, get_startup_info
from ..core.logging_util import get_logger
from .views.queue_view import QueueView
from .views.history_view import HistoryView
from .views.settings_view import SettingsView
from .notifier import toast

log = get_logger("app")
YOUTUBE_URL_RE = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("LiquidGlass Downloader v2.3.0")
        self.geometry("1120x680")
        init_theme(CONFIG.settings.theme)

        # Perform startup initialization in background
        self._startup_result = None
        self._perform_startup_checks()

        self.dm = DownloadManager()

        root = ctk.CTkFrame(self)
        root.pack(fill="both", expand=True)
        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(root, width=200, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="ns")
        ctk.CTkLabel(sidebar, text="LiquidGlass", font=("Segoe UI", 18, "bold")).pack(pady=(18,10))
        self.btn_queue = ctk.CTkButton(sidebar, text="Queue", command=self._show_queue, width=160)
        self.btn_queue.pack(pady=6)
        self.btn_history = ctk.CTkButton(sidebar, text="History", command=self._show_history, width=160)
        self.btn_history.pack(pady=6)
        self.btn_settings = ctk.CTkButton(sidebar, text="Settings", command=self._show_settings, width=160)
        self.btn_settings.pack(pady=6)

        self.content = ctk.CTkFrame(root, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")

        # Status bar FIRST so methods can reference it safely
        self.status = ctk.CTkLabel(self, text="Ready")
        self.status.pack(fill="x", side="bottom", padx=8, pady=4)

        self.queue_view = QueueView(self.content, self.dm)
        self.history_view = HistoryView(self.content)
        self.settings_view = SettingsView(self.content, self.dm, self._theme_changed)

        self.queue_view.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.history_view.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.settings_view.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._show_queue()
        self._last_clipboard = ""
        self._last_clipboard_time = 0.0
        self.after(1200, self._tick)

        # Check startup results after a short delay
        self.after(2000, self._check_startup_results)

    def _perform_startup_checks(self):
        """
        Perform startup initialization in background thread.

        This includes platform compatibility checks and auto-updates
        without blocking the UI from appearing.
        """
        def startup_thread():
            try:
                log.info("Performing startup checks...")
                self._startup_result = initialize_application(async_mode=True)

                if not self._startup_result.success:
                    log.error("Startup checks failed")
                    for error in self._startup_result.errors:
                        log.error(f"  - {error}")
                else:
                    log.info("Startup checks completed successfully")

            except Exception as e:
                log.error(f"Startup check error: {e}")

        thread = threading.Thread(target=startup_thread, daemon=True)
        thread.start()

    def _check_startup_results(self):
        """
        Check startup results and show notifications if needed.

        Called after a short delay to allow the UI to fully load.
        """
        if self._startup_result is None:
            # Not ready yet, check again later
            self.after(1000, self._check_startup_results)
            return

        # Show warnings if any
        if self._startup_result.warnings:
            for warning in self._startup_result.warnings[:3]:  # Limit to 3 warnings
                toast(self, f"Warning: {warning}")

        # Show update notifications
        if self._startup_result.updates_performed:
            updated_packages = [
                pkg for pkg, success in self._startup_result.updates_performed.items()
                if success
            ]
            if updated_packages:
                toast(self, f"Updated: {', '.join(updated_packages)}")

        # Show errors if critical
        if self._startup_result.errors:
            for error in self._startup_result.errors[:2]:  # Limit to 2 errors
                toast(self, f"Error: {error}")

        # Update status bar with version info
        try:
            info = get_startup_info()
            platform = info.get("platform", {})
            py_version = platform.get("python_version", "unknown")
            self.status.configure(text=f"Ready - Python {py_version}")
        except Exception:
            pass

    def _theme_changed(self, mode: str):
        init_theme(mode)
        toast(self, f"Theme switched to {mode}")

    def _show_queue(self):
        self.queue_view.lift()
        if hasattr(self, "status"):
            self.status.configure(text="Queue")

    def _show_history(self):
        self.history_view.lift()
        if hasattr(self, "status"):
            self.status.configure(text="History")

    def _show_settings(self):
        self.settings_view.lift()
        if hasattr(self, "status"):
            self.status.configure(text="Settings")

    def _tick(self):
        """
        Main application tick for clipboard monitoring.

        Runs periodically to check clipboard for video URLs when enabled.
        """
        try:
            if CONFIG.settings.clipboard_watch:
                self.after_idle(self._check_clipboard)
        except Exception as e:
            print(f"Error in tick: {e}")
        finally:
            self.after(CLIPBOARD_POLL_INTERVAL_MS, self._tick)

    def _check_clipboard(self):
        """
        Check clipboard for video URLs with debouncing.

        Implements debouncing to avoid rapid repeated notifications
        when the same URL is detected multiple times in quick succession.
        """
        try:
            data = self.clipboard_get()
            if not data:
                return

            # Debouncing: ignore if clipboard hasn't changed recently
            current_time = time.time()
            if data == self._last_clipboard:
                # Check if enough time has passed for the same URL
                if current_time - self._last_clipboard_time < (CLIPBOARD_DEBOUNCE_MS / 1000):
                    return

            # Check if it's a valid URL and matches video platform patterns
            if is_valid_url(data) and YOUTUBE_URL_RE.search(data):
                self._last_clipboard = data
                self._last_clipboard_time = current_time
                self._handle_clipboard_url(data)
        except Exception:
            # Ignore clipboard errors (common when clipboard is locked by another app)
            pass

    def _handle_clipboard_url(self, url: str):
        """
        Handle detected video URL from clipboard.

        Args:
            url: The detected video URL
        """
        toast(self, "Video link detected! Auto-filled in Queue.")
        self.queue_view.url_entry.delete(0, "end")
        self.queue_view.url_entry.insert(0, url)

def main():
    """
    Main entry point for GUI application.

    Performs platform compatibility checks before starting the GUI.
    """
    try:
        log.info("Starting LiquidGlass Downloader GUI...")
        app = App()
        app.mainloop()
    except Exception as e:
        log.error(f"Fatal error in main loop: {e}")
        raise

if __name__ == "__main__":
    main()
