from __future__ import annotations
import customtkinter as ctk
from tkinter import filedialog, messagebox
import csv, json, os, subprocess, sys
from ...core.db import DB_INSTANCE as DB
from ..utils import status_color
from ..notifier import toast

def _open_in_folder(path: str):
    if not path: return
    if sys.platform.startswith("win"):
        subprocess.run(["explorer", "/select,", path])
    elif sys.platform == "darwin":
        subprocess.run(["open", "-R", path])
    else:
        subprocess.run(["xdg-open", os.path.dirname(path)])

class HistoryView(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        bar = ctk.CTkFrame(self, corner_radius=10)
        bar.pack(fill="x", padx=10, pady=(10,6))
        self.search_entry = ctk.CTkEntry(bar, width=420, placeholder_text="Search title/url/path...")
        self.search_entry.pack(side="left", padx=10, pady=10)
        self.search_entry.bind("<KeyRelease>", lambda e: self.refresh())
        ctk.CTkButton(bar, text="Clear History", command=self.clear_history).pack(side="right", padx=6, pady=10)
        ctk.CTkButton(bar, text="Export JSON", command=self.export_json).pack(side="right", padx=6, pady=10)
        ctk.CTkButton(bar, text="Export CSV", command=self.export_csv).pack(side="right", padx=6, pady=10)

        self.scroll = ctk.CTkScrollableFrame(self, width=940, height=420, corner_radius=8)
        self.scroll.pack(fill="both", expand=True, padx=10, pady=(0,10))

        self.refresh()

    def _rows_data(self):
        term = self.search_entry.get().strip()
        if term:
            return DB.search(term)
        return DB.list()

    def refresh(self):
        for c in self.scroll.winfo_children():
            c.destroy()
        headers = ["ID", "Title", "Status", "Open"]
        for i, h in enumerate(headers):
            ctk.CTkLabel(self.scroll, text=h, font=("Segoe UI", 12, "bold")).grid(row=0, column=i, padx=6, pady=4, sticky="w")
        for r, item in enumerate(self._rows_data(), start=1):
            ctk.CTkLabel(self.scroll, text=str(item.id)).grid(row=r, column=0, padx=4, pady=2, sticky="w")
            ctk.CTkLabel(self.scroll, text=item.title or "-").grid(row=r, column=1, padx=4, pady=2, sticky="w")
            ctk.CTkLabel(
                self.scroll,
                text=item.status,
                text_color=status_color(item.status),
            ).grid(row=r, column=2, padx=4, pady=2, sticky="w")
            ctk.CTkButton(self.scroll, text="Show in Folder", command=lambda p=item.filepath: _open_in_folder(p)).grid(row=r, column=3, padx=4, pady=2, sticky="w")

    def export_json(self):
        fp = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not fp: return
        rows = [r.__dict__ for r in self._rows_data()]
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2)

    def export_csv(self):
        fp = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not fp: return
        rows = self._rows_data()
        with open(fp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["id","url","title","status","filepath"])
            for r in rows:
                w.writerow([r.id, r.url, r.title, r.status, r.filepath or ""])

    def clear_history(self):
        if not messagebox.askyesno("Clear History", "Remove all finished items?"):
            return
        DB.clear_history()
        self.refresh()
        toast(self, "History cleared")
