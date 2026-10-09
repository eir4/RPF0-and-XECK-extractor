import os
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk

# Import the updated Kaworu (Full Ripper Orchestrator)
from Kaworu import XeckExtractorAutomator

class XECKAnalyzerApp:
    def __init__(self, root):
        self.root = root
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_kaworu = tk.Frame(self.notebook)
        self.notebook.add(self.tab_kaworu, text="Automated Direct Extractor (Kaworu)")

        self.xeck_files = []
        self.output_dir = ""

        self._build_kaworu_tab()

    def _build_kaworu_tab(self):
        tk.Label(
            self.tab_kaworu,
            text="Kaworu: Automated All-in-One XECK Ripper",
            font=("Arial", 11, "bold"),
        ).pack(pady=(10, 0))

        tk.Label(
            self.tab_kaworu,
            text="Extracts verified meshes (with UVs), DDS/PNG textures, materials, and links them automatically.",
            font=("Arial", 9, "italic"),
        ).pack(pady=5)

        btn_frame = tk.Frame(self.tab_kaworu)
        btn_frame.pack(pady=5)

        self.btn_xecks = tk.Button(btn_frame, text="Select XECK Files", command=self.select_xecks)
        self.btn_xecks.pack(side=tk.LEFT, padx=5)

        self.btn_output = tk.Button(btn_frame, text="Select Output Directory", command=self.select_output)
        self.btn_output.pack(side=tk.LEFT, padx=5)

        self.btn_kaworu_run = tk.Button(
            self.tab_kaworu,
            text="Run Full Extraction Pipeline (Kaworu)",
            command=self.start_kaworu_extraction,
            state=tk.DISABLED,
            bg="purple",
            fg="white",
            font=("Arial", 10, "bold"),
        )
        self.btn_kaworu_run.pack(pady=10)

        self.kaworu_log_area = scrolledtext.ScrolledText(
            self.tab_kaworu, width=75, height=20, state=tk.DISABLED, bg="black", fg="lime"
        )
        self.kaworu_log_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

    def log(self, message: str):
        self.kaworu_log_area.config(state=tk.NORMAL)
        self.kaworu_log_area.insert(tk.END, message + "\n")
        self.kaworu_log_area.see(tk.END)
        self.kaworu_log_area.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def select_xecks(self):
        files = filedialog.askopenfilenames(title="Select XECK files", filetypes=[("XECK Files", "*.xeck")])
        if files:
            self.xeck_files = list(files)
            self.log(f"[*] Selected {len(self.xeck_files)} XECK files.")
            self.update_btn_state()

    def select_output(self):
        dir_path = filedialog.askdirectory(title="Select Output Directory")
        if dir_path:
            self.output_dir = dir_path
            self.log(f"[*] Output directory set to: {self.output_dir}")
            self.update_btn_state()

    def update_btn_state(self):
        if self.xeck_files and self.output_dir:
            self.btn_kaworu_run.config(state=tk.NORMAL)

    def start_kaworu_extraction(self):
        self.btn_kaworu_run.config(state=tk.DISABLED)
        self.kaworu_log_area.config(state=tk.NORMAL)
        self.kaworu_log_area.delete(1.0, tk.END)
        self.kaworu_log_area.config(state=tk.DISABLED)
        threading.Thread(target=self.process_kaworu_pipeline, daemon=True).start()

    def process_kaworu_pipeline(self):
        self.log("[*] Initializing Kaworu Full Pipeline Extraction...")
        for xeck_file in self.xeck_files:
            try:
                automator = XeckExtractorAutomator(xeck_path=xeck_file, log_callback=self.log)
                automator.run_pipeline(self.output_dir)
            except Exception as e:
                self.log(f"[!] Critical Error extracting {xeck_file}:\n{traceback.format_exc()}")

        self.log("[✔] All XECK files processed successfully!")
        self.root.after(0, lambda: self.btn_kaworu_run.config(state=tk.NORMAL))

if __name__ == "__main__":
    root = tk.Tk()
    root.title("RAGE Geometry & XECK Universal Extractor Suite")
    root.geometry("800x600")
    app = XECKAnalyzerApp(root)
    root.mainloop()