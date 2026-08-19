from __future__ import annotations
import customtkinter as ctk
from PIL import Image
import os
import threading

from ...core.db import DB_INSTANCE as DB
from ...core.models import QueueItem
from ...core.config import CONFIG
from ...core.downloader import DownloadManager
from ..notifier import toast
from ..utils import status_color

def _fmt_bytes(n: int | None) -> str:
    if not n: return "-"
    for unit in ["B","KB","MB","GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

def _fmt_speed(s: float | None) -> str:
    if not s: return "-"
    return f"{_fmt_bytes(s)}/s"

def _fmt_eta(e: int | None) -> str:
    if not e: return "-"
    m, s = divmod(int(e), 60)
    h, m = divmod(m, 60)
    if h: return f"{h}h {m}m"
    if m: return f"{m}m {s}s"
    return f"{s}s"

class QueueCard(ctk.CTkFrame):
    def __init__(self, master, item: QueueItem, dm: DownloadManager):
        super().__init__(master, corner_radius=12)
        self.item = item
        self.dm = dm
        self.grid_columnconfigure(1, weight=1)

        img = None
        if item.thumb_path and os.path.exists(item.thumb_path):
            try:
                img = ctk.CTkImage(Image.open(item.thumb_path), size=(96, 54))
            except Exception:
                pass
        self.thumb = ctk.CTkLabel(self, text="", image=img, width=100)
        self.thumb.grid(row=0, column=0, rowspan=3, padx=10, pady=10)

        title = item.title or "(resolving title...)"
        self.title_lbl = ctk.CTkLabel(self, text=title, font=("Segoe UI", 14, "bold"))
        self.title_lbl.grid(row=0, column=1, sticky="w", padx=(0,6), pady=(8,4))

        meta = f"{item.uploader or ''}"
        self.meta_lbl = ctk.CTkLabel(self, text=meta, text_color=('#a1a1aa', '#a1a1aa'))
        self.meta_lbl.grid(row=1, column=1, sticky="w", padx=(0,6))

        total = item.total_bytes or 0
        got = item.downloaded_bytes or 0
        progress = (got / total) if total else 0
        self.pbar = ctk.CTkProgressBar(self)
        self.pbar.set(progress)
        self.pbar.grid(row=2, column=1, sticky="ew", padx=(0,6), pady=(0,8))

        stats = (
            f"{_fmt_bytes(got)} / {_fmt_bytes(total)} "
            f"({progress*100:.1f}%)   •   {item.status}   •   {_fmt_speed(item.speed)}   •   ETA {_fmt_eta(item.eta)}"
        )
        self.stats_lbl = ctk.CTkLabel(self, text=stats, text_color=status_color(item.status))
        self.stats_lbl.grid(row=3, column=1, sticky="w", padx=(0,6), pady=(0,8))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=0, column=2, rowspan=4, padx=6, pady=6, sticky="e")
        ctk.CTkButton(btns, text="Start", width=64, command=lambda: self.dm.start(item.id)).grid(row=0, column=0, padx=3, pady=3)
        ctk.CTkButton(btns, text="Pause", width=64, command=lambda: self.dm.pause(item.id)).grid(row=0, column=1, padx=3, pady=3)
        ctk.CTkButton(btns, text="Resume", width=64, command=lambda: self.dm.resume(item.id)).grid(row=1, column=0, padx=3, pady=3)
        ctk.CTkButton(btns, text="Cancel", width=64, command=lambda: self.dm.cancel(item.id)).grid(row=1, column=1, padx=3, pady=3)
        ctk.CTkButton(btns, text="↑", width=44, command=lambda: (DB.move_up(item.id), self.master.master.refresh())).grid(row=2, column=0, padx=3, pady=3)
        ctk.CTkButton(btns, text="↓", width=44, command=lambda: (DB.move_down(item.id), self.master.master.refresh())).grid(row=2, column=1, padx=3, pady=3)

    def update_from(self, item: QueueItem):
        self.item = item
        self.title_lbl.configure(text=item.title or self.title_lbl.cget("text"))
        total = item.total_bytes or 0
        got = item.downloaded_bytes or 0
        progress = (got / total) if total else 0
        self.pbar.set(progress)
        stats = (
            f"{_fmt_bytes(got)} / {_fmt_bytes(total)} "
            f"({progress*100:.1f}%)   •   {item.status}   •   {_fmt_speed(item.speed)}   •   ETA {_fmt_eta(item.eta)}"
        )
        self.stats_lbl.configure(text=stats, text_color=status_color(item.status))

class QueueView(ctk.CTkFrame):
    def __init__(self, master, dm: DownloadManager):
        super().__init__(master)
        self.dm = dm
        self.refresh_lock = threading.Lock()
        self.is_refreshing = False

        header = ctk.CTkFrame(self, corner_radius=10)
        header.pack(fill="x", padx=10, pady=(10,6))
        self.url_entry = ctk.CTkEntry(header, placeholder_text="Paste a YouTube URL…", width=520)
        self.url_entry.pack(side="left", padx=(10,8), pady=10)
        ctk.CTkButton(header, text="Add", command=self._add_one).pack(side="left", padx=4)
        ctk.CTkButton(header, text="Add Multiple", command=self._open_multi).pack(side="left", padx=4)
        ctk.CTkButton(header, text="Start All", command=self._start_all).pack(side="left", padx=4)
        ctk.CTkButton(header, text="Pause All", command=self._pause_all).pack(side="left", padx=4)
        ctk.CTkButton(header, text="Cancel All", command=self._cancel_all).pack(side="left", padx=4)

        self.scroll = ctk.CTkScrollableFrame(self, width=940, height=420, corner_radius=8)
        self.scroll.pack(fill="both", expand=True, padx=10, pady=(0,10))
        self.card_widgets = {}
        self.after(100, self.refresh)

    def _add_one(self):
        url = self.url_entry.get().strip()
        if not url: return
        self.dm.queue(url, CONFIG.settings.format)
        self.url_entry.delete(0, "end")
        toast(self, "Added to queue")

    def _open_multi(self):
        from ..dialogs.add_urls_dialog import AddUrlsDialog
        def on_submit(urls):
            for u in urls:
                self.dm.queue(u, CONFIG.settings.format)
            toast(self, f"Added {len(urls)} items")
            self.refresh()
        AddUrlsDialog(self, on_submit)

    def _start_all(self): self.dm.start_all()
    def _pause_all(self): self.dm.pause_all()
    def _cancel_all(self): self.dm.cancel_all()

    def refresh(self):
        if self.is_refreshing:
            return
        
        self.is_refreshing = True
        try:
            items = DB.list()
            seen = set()
            
            # Update existing cards and identify new ones
            for it in items:
                seen.add(it.id)
                card = self.card_widgets.get(it.id)
                if card:
                    card.update_from(it)
                else:
                    # Create new card
                    card = QueueCard(self.scroll, it, self.dm)
                    self.card_widgets[it.id] = card
            
            # Remove old cards
            for iid in list(self.card_widgets.keys()):
                if iid not in seen:
                    self.card_widgets[iid].destroy()
                    del self.card_widgets[iid]
            
            # Re-grid all cards to maintain order
            for row, it in enumerate(items):
                card = self.card_widgets.get(it.id)
                if card:
                    card.grid(row=row, column=0, sticky="ew", padx=8, pady=6)
        finally:
            self.is_refreshing = False
            self.after(1000, self.refresh)  # Schedule next refresh
