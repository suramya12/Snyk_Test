from __future__ import annotations
import customtkinter as ctk
from tkinter import filedialog, messagebox
from ...core.config import CONFIG
from ...core.downloader import DownloadManager
from ...core.db import DB_INSTANCE as DB
from ..notifier import toast


class SettingsView(ctk.CTkFrame):
    def __init__(self, master, dm: DownloadManager, on_theme_changed):
        super().__init__(master)
        self.dm = dm
        self.on_theme_changed = on_theme_changed
        s = CONFIG.settings

        section1 = ctk.CTkFrame(self, corner_radius=10)
        section1.pack(fill="x", padx=10, pady=(10, 6))
        ctk.CTkLabel(section1, text="General", font=("Segoe UI", 16, "bold")).pack(
            anchor="w", padx=10, pady=(10, 4)
        )

        row = ctk.CTkFrame(section1, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=6)
        self.dir_label = ctk.CTkLabel(row, text=f"Download folder: {s.download_dir}")
        self.dir_label.pack(side="left", expand=True, fill="x")
        ctk.CTkButton(row, text="Change...", command=self.change_dir).pack(
            side="right", padx=6
        )

        row2 = ctk.CTkFrame(section1, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(row2, text="Concurrent downloads").pack(side="left")
        self.conc_slider = ctk.CTkSlider(
            row2, from_=1, to=6, number_of_steps=5, command=self._set_conc
        )
        self.conc_slider.set(s.concurrent_downloads)
        self.conc_slider.pack(side="left", padx=12)
        self.conc_lbl = ctk.CTkLabel(row2, text=str(s.concurrent_downloads))
        self.conc_lbl.pack(side="left")

        section2 = ctk.CTkFrame(self, corner_radius=10)
        section2.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(
            section2, text="Formats & Embeds", font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", padx=10, pady=(10, 4))
        row3 = ctk.CTkFrame(section2, fg_color="transparent")
        row3.pack(fill="x", padx=10, pady=6)
        self.format_opt = ctk.CTkOptionMenu(
            row3,
            values=[
                "bestvideo[height>=2160]+bestaudio/bestvideo[height>=1440]+bestaudio/bestvideo[height>=1080]+bestaudio/best",
                "bestvideo[height>=1440]+bestaudio/bestvideo[height>=1080]+bestaudio/best",
                "bestvideo[height>=1080]+bestaudio/best"
            ],
            command=self._set_format,
        )
        self.format_opt.set(s.format)
        self.format_opt.pack(side="left", padx=(0, 10))
        self.audio_only = ctk.CTkCheckBox(
            row3, text="Audio only (mp3)", command=self._toggle_audio
        )
        self.audio_only.select() if s.audio_only else self.audio_only.deselect()
        self.audio_only.pack(side="left", padx=10)
        self.embed_subs = ctk.CTkCheckBox(
            row3, text="Embed Subtitles", command=self._toggle_subs
        )
        self.embed_subs.select() if s.embed_subtitles else self.embed_subs.deselect()
        self.embed_subs.pack(side="left", padx=10)
        self.embed_thumb = ctk.CTkCheckBox(
            row3, text="Embed Thumbnail", command=self._toggle_thumb
        )
        self.embed_thumb.select() if s.embed_thumbnail else self.embed_thumb.deselect()
        self.embed_thumb.pack(side="left", padx=10)

        section3 = ctk.CTkFrame(self, corner_radius=10)
        section3.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(
            section3, text="Appearance & Behavior", font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", padx=10, pady=(10, 4))
        row4 = ctk.CTkFrame(section3, fg_color="transparent")
        row4.pack(fill="x", padx=10, pady=6)
        self.theme_opt = ctk.CTkOptionMenu(
            row4, values=["System", "Light", "Dark"], command=self._set_theme
        )
        self.theme_opt.set(s.theme)
        self.theme_opt.pack(side="left", padx=(0, 10))
        self.clipboard_watch = ctk.CTkCheckBox(
            row4,
            text="Watch clipboard for YouTube URLs",
            command=self._toggle_clipboard,
        )
        (
            self.clipboard_watch.select()
            if s.clipboard_watch
            else self.clipboard_watch.deselect()
        )
        self.clipboard_watch.pack(side="left", padx=10)

        section4 = ctk.CTkFrame(self, corner_radius=10)
        section4.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(section4, text="Maintenance", font=("Segoe UI", 16, "bold")).pack(
            anchor="w", padx=10, pady=(10, 4)
        )
        row5 = ctk.CTkFrame(section4, fg_color="transparent")
        row5.pack(fill="x", padx=10, pady=6)
        ctk.CTkButton(row5, text="Clear History", command=self._clear_history).pack(
            side="left", padx=6
        )
        ctk.CTkButton(row5, text="Reset Application", command=self._reset_app).pack(
            side="left", padx=6
        )

    def change_dir(self):
        fp = filedialog.askdirectory()
        if not fp:
            return
        s = CONFIG.settings
        s.download_dir = fp
        CONFIG.save(s)
        self.dir_label.configure(text=f"Download folder: {fp}")

    def _set_conc(self, val):
        n = int(float(val))
        self.conc_lbl.configure(text=str(n))
        self.dm.set_concurrency(n)

    def _set_format(self, val):
        s = CONFIG.settings
        s.format = val
        CONFIG.save(s)

    def _toggle_audio(self):
        s = CONFIG.settings
        s.audio_only = not s.audio_only
        CONFIG.save(s)

    def _toggle_subs(self):
        s = CONFIG.settings
        s.embed_subtitles = not s.embed_subtitles
        CONFIG.save(s)

    def _toggle_thumb(self):
        s = CONFIG.settings
        s.embed_thumbnail = not s.embed_thumbnail
        CONFIG.save(s)

    def _set_theme(self, val):
        s = CONFIG.settings
        s.theme = val
        CONFIG.save(s)
        self.on_theme_changed(val)

    def _toggle_clipboard(self):
        s = CONFIG.settings
        s.clipboard_watch = not s.clipboard_watch
        CONFIG.save(s)

    def _clear_history(self):
        if not messagebox.askyesno("Clear History", "Remove all finished items?"):
            return
        DB.clear_history()
        try:
            # Get the root window first
            root = self.winfo_toplevel()
            if hasattr(root, 'history_view'):
                root.history_view.refresh()
        except Exception:
            pass
        toast(self, "History cleared")

    def _reset_app(self):
        if not messagebox.askyesno(
            "Reset Application",
            "This will remove all settings and downloads and restart. Continue?",
        ):
            return
        self.dm.cancel_all()
        import shutil, sys, os

        shutil.rmtree(CONFIG.config_dir, ignore_errors=True)
        shutil.rmtree(CONFIG.data_dir, ignore_errors=True)
        python = sys.executable
        os.execl(python, python, "-m", "liquidglass_downloader.ui.app")
