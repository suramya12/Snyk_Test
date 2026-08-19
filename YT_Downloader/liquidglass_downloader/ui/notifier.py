import customtkinter as ctk
class Toast(ctk.CTkToplevel):
    def __init__(self, master, message: str, duration=2500):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color="#111318")
        label = ctk.CTkLabel(self, text=message, padx=14, pady=8)
        label.pack()
        self.update_idletasks()
        x = master.winfo_x() + master.winfo_width() - self.winfo_width() - 24
        y = master.winfo_y() + master.winfo_height() - self.winfo_height() - 24
        self.geometry(f"+{x}+{y}")
        self.after(duration, self.destroy)

def toast(master, message: str, duration=2500):
    Toast(master, message, duration)
