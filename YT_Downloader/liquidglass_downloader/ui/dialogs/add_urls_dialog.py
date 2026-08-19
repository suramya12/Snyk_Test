from __future__ import annotations
import customtkinter as ctk

class AddUrlsDialog(ctk.CTkToplevel):
    def __init__(self, master, on_submit):
        super().__init__(master)
        self.title("Add Multiple URLs")
        self.geometry("700x420")
        self.on_submit = on_submit
        self.text = ctk.CTkTextbox(self, width=660, height=320, corner_radius=10)
        self.text.pack(padx=16, pady=(16,8), fill="both", expand=True)
        self.text.insert("1.0", "Paste URLs here, one per line...")
        btn = ctk.CTkButton(self, text="Add to Queue", command=self._submit)
        btn.pack(padx=16, pady=(0,16))

    def _submit(self):
        raw = self.text.get("1.0", "end").strip()
        urls = [line.strip() for line in raw.splitlines() if line.strip()]
        if urls:
            self.on_submit(urls)
        self.destroy()
