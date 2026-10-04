import os
import threading
import traceback
from pathlib import Path
from typing import Optional
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk

# Import Geometry & Analysis Children
from Rei import XeckOffsetCrossReferencer
from Shinji import XeckObjExtractor
from Asuka import UniversalKeyAnalyzer

# Import Automated Direct Extractor Child (Kaworu)
from Kaworu import XeckExtractorAutomator

# Import Structural Byte-Mapper & TOC Analyzer Child (Katsuragi)
from Katsuragi import KatsuragiMain

# Import Texture Extractor Child (Misato)
from Misato import MisatoExtractor

# Import legacy RPF Extractor
import rpf_extractor


class ThemeManager:
    """Manages toggling between standard OS theme and the 'Eira' Poster Dark Theme."""

    def __init__(self, root):
        self.root = root
        self.style = ttk.Style()
        self.initial_theme = self.style.theme_use()
        self.is_dark = tk.BooleanVar(value=False)

        # Pack the top bar FIRST so it strictly claims the top of the window
        self.top_bar = tk.Frame(root)
        self.top_bar.pack(side=tk.TOP, fill=tk.X)

        self.toggle_btn = tk.Checkbutton(
            self.top_bar,
            text="★ Enable 'Eira Presents' Poster Theme ★",
            variable=self.is_dark,
            command=self.toggle_theme,
            font=("Arial", 9, "bold")
        )
        self.toggle_btn.pack(side=tk.RIGHT, padx=10, pady=2)

        # Placeholders for the banners
        self.banner_label = None
        self.img_dark = None
        self.img_default = None

    def set_banners(self, banner_label, img_dark, img_default):
        """Called from main() to attach the resized images."""
        self.banner_label = banner_label
        self.img_dark = img_dark
        self.img_default = img_default

        # Set initial image
        if self.banner_label and self.img_default:
            self.banner_label.config(image=self.img_default)

    def init_colors(self):
        self.save_original_colors(self.root)

    def save_original_colors(self, widget):
        if not hasattr(widget, '_orig_bg'):
            try:
                widget._orig_bg = widget.cget('bg')
            except tk.TclError:
                widget._orig_bg = ""

            try:
                widget._orig_fg = widget.cget('fg')
            except tk.TclError:
                widget._orig_fg = ""

            try:
                widget._orig_selectcolor = widget.cget('selectcolor')
            except tk.TclError:
                widget._orig_selectcolor = ""

        for child in widget.winfo_children():
            self.save_original_colors(child)

    def apply_theme_recursive(self, widget, is_dark):
        widg_type = widget.winfo_class().lower()
        dark_bg = "#0a0403"
        dark_fg = "#fdf4e3"
        accent_color = "#fc5c00"
        btn_bg = "#1f0c08"

        try:
            orig_bg = getattr(widget, '_orig_bg', '')
            orig_fg = getattr(widget, '_orig_fg', '')

            if widg_type in ('text', 'canvas'):
                pass
            elif widg_type == 'entry':
                widget.config(bg=btn_bg if is_dark else orig_bg, fg=accent_color if is_dark else orig_fg,
                              insertbackground=accent_color if is_dark else 'black')
            elif widg_type in ('frame', 'tframe', 'tk', 'toplevel'):
                if widg_type == 'frame' and str(orig_bg).lower() == 'grey' and widget.cget('width') == 2:
                    widget.config(bg=accent_color if is_dark else orig_bg)
                else:
                    widget.config(bg=dark_bg if is_dark else orig_bg)
            elif widg_type in ('label', 'labelframe'):
                widget.config(bg=dark_bg if is_dark else orig_bg, fg=dark_fg if is_dark else orig_fg)
            elif widg_type in ('checkbutton', 'radiobutton'):
                widget.config(bg=dark_bg if is_dark else orig_bg, fg=accent_color if is_dark else orig_fg)
                widget.config(selectcolor="#2a110d" if is_dark else getattr(widget, '_orig_selectcolor', 'white'))
            elif widg_type == 'button':
                widget.config(bg=btn_bg if is_dark else orig_bg, fg=accent_color if is_dark else orig_fg)
        except tk.TclError:
            pass

        for child in widget.winfo_children():
            self.apply_theme_recursive(child, is_dark)

    def toggle_theme(self):
        dark = self.is_dark.get()
        if dark:
            self.style.theme_use('default')
            self.style.configure("TNotebook", background="#0a0403", borderwidth=0)
            self.style.configure("TNotebook.Tab", background="#1f0c08", foreground="#fc5c00", padding=[10, 4],
                                 font=("Arial", 9, "bold"))
            self.style.map("TNotebook.Tab", background=[("selected", "#fc5c00")], foreground=[("selected", "#0a0403")])
            self.style.configure("TFrame", background="#0a0403")
            if self.banner_label and self.img_dark:
                self.banner_label.config(image=self.img_dark)
        else:
            self.style.theme_use(self.initial_theme)
            if self.banner_label and self.img_default:
                self.banner_label.config(image=self.img_default)

        self.apply_theme_recursive(self.root, dark)


class GUIProxy(tk.Frame):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.parent = parent

    def title(self, title_string):
        pass

    def geometry(self, geometry_string):
        pass


class XECKAnalyzerApp:
    def __init__(self, root):
        self.root = root

        # Tabbed interface
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_kaworu = tk.Frame(self.notebook)
        self.tab_secondary = tk.Frame(self.notebook)

        self.notebook.add(self.tab_kaworu, text="Automated Direct Extractor (Kaworu)")
        self.notebook.add(self.tab_secondary, text="Advanced Modules (Misato/Katsuragi/3 Children)")

        self.xeck_files = []
        self.csv_files = []
        self.output_dir = ""

        self._build_kaworu_tab()
        self._build_secondary_tab()

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

        self.btn_xecks_kaworu = tk.Button(btn_frame, text="Select XECK Files", command=self.select_xecks)
        self.btn_xecks_kaworu.pack(side=tk.LEFT, padx=5)

        self.btn_output_kaworu = tk.Button(btn_frame, text="Select Output Directory", command=self.select_output)
        self.btn_output_kaworu.pack(side=tk.LEFT, padx=5)

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
            self.tab_kaworu, width=75, height=20, state=tk.DISABLED, bg="black", fg="purple"
        )
        self.kaworu_log_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

    def _build_secondary_tab(self):
        tk.Label(
            self.tab_secondary,
            text="Advanced XECK Processing Modules",
            font=("Arial", 11, "bold"),
        ).pack(pady=(10, 0))

        # File Selection
        file_frame = tk.Frame(self.tab_secondary)
        file_frame.pack(pady=5)

        self.btn_xecks_sec = tk.Button(file_frame, text="Select XECK Files", command=self.select_xecks)
        self.btn_xecks_sec.grid(row=0, column=0, padx=5, pady=2, sticky="ew")
        self.lbl_xecks = tk.Label(file_frame, text="0 XECK files selected")
        self.lbl_xecks.grid(row=0, column=1, sticky="w")

        self.btn_csvs_sec = tk.Button(file_frame, text="Select CSV Files (For 3 Children/Katsuragi)", command=self.select_csvs)
        self.btn_csvs_sec.grid(row=1, column=0, padx=5, pady=2, sticky="ew")
        self.lbl_csvs = tk.Label(file_frame, text="0 CSV files selected")
        self.lbl_csvs.grid(row=1, column=1, sticky="w")

        self.btn_out_sec = tk.Button(file_frame, text="Select Output Directory", command=self.select_output)
        self.btn_out_sec.grid(row=2, column=0, padx=5, pady=2, sticky="ew")
        self.lbl_output = tk.Label(file_frame, text="Unset")
        self.lbl_output.grid(row=2, column=1, sticky="w")

        # Module Selection
        mod_frame = tk.LabelFrame(self.tab_secondary, text="Select Processing Module")
        mod_frame.pack(pady=10, fill=tk.X, padx=15)

        self.var_module = tk.StringVar(value="misato")
        tk.Radiobutton(mod_frame, text="Misato (Standalone Texture Ripper)", variable=self.var_module, value="misato").pack(anchor="w", padx=10)
        tk.Radiobutton(mod_frame, text="Katsuragi (TOC & Binary Mapper)", variable=self.var_module, value="katsuragi").pack(anchor="w", padx=10)
        tk.Radiobutton(mod_frame, text="The 3 Children: Rei, Shinji, Asuka (Geometry & Analysis)", variable=self.var_module, value="3children").pack(anchor="w", padx=10)

        # Specific Configuration Options
        opt_frame = tk.Frame(self.tab_secondary)
        opt_frame.pack(pady=5)

        self.var_strip = tk.BooleanVar(value=False)
        tk.Checkbutton(opt_frame, text="[3 Children] Use Triangle Strip Topology", variable=self.var_strip).pack(side=tk.LEFT, padx=10)

        tk.Label(opt_frame, text="[Katsuragi] Base Offset:").pack(side=tk.LEFT)
        self.ent_katsuragi_base = tk.Entry(opt_frame, width=8)
        self.ent_katsuragi_base.insert(0, "0x400")
        self.ent_katsuragi_base.pack(side=tk.LEFT, padx=5)

        # Run Button
        self.btn_run_sec = tk.Button(
            self.tab_secondary,
            text="Run Selected Module",
            command=self.run_secondary_module,
            state=tk.DISABLED,
            bg="blue",
            fg="white",
            font=("Arial", 10, "bold"),
        )
        self.btn_run_sec.pack(pady=10)

        self.sec_log_area = scrolledtext.ScrolledText(
            self.tab_secondary, width=75, height=12, state=tk.DISABLED, bg="black", fg="cyan"
        )
        self.sec_log_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

    def log(self, message: str, target_area: Optional[scrolledtext.ScrolledText] = None):
        area = target_area or self.sec_log_area
        area.config(state=tk.NORMAL)
        area.insert(tk.END, message + "\n")
        area.see(tk.END)
        area.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def select_xecks(self):
        files = filedialog.askopenfilenames(title="Select XECK files", filetypes=[("XECK Files", "*.xeck"), ("All Files", "*.*")])
        if files:
            self.xeck_files = list(files)
            self.lbl_xecks.config(text=f"{len(self.xeck_files)} XECK file(s) selected.")
            self.log(f"[*] Selected {len(self.xeck_files)} XECK files.", target_area=self.kaworu_log_area)
            self.log(f"[*] Selected {len(self.xeck_files)} XECK files.", target_area=self.sec_log_area)
            self.update_btn_states()

    def select_csvs(self):
        files = filedialog.askopenfilenames(title="Select RenderDoc CSVs", filetypes=[("CSV Files", "*.csv")])
        if files:
            self.csv_files = list(files)
            self.lbl_csvs.config(text=f"{len(self.csv_files)} CSV file(s) selected.")
            self.update_btn_states()

    def select_output(self):
        dir_path = filedialog.askdirectory(title="Select Output Directory")
        if dir_path:
            self.output_dir = dir_path
            self.lbl_output.config(text=f"Output: {self.output_dir}")
            self.log(f"[*] Output set: {self.output_dir}", target_area=self.kaworu_log_area)
            self.log(f"[*] Output set: {self.output_dir}", target_area=self.sec_log_area)
            self.update_btn_states()

    def update_btn_states(self):
        if self.xeck_files and self.output_dir:
            self.btn_kaworu_run.config(state=tk.NORMAL)
            self.btn_run_sec.config(state=tk.NORMAL)
        else:
            self.btn_kaworu_run.config(state=tk.DISABLED)
            self.btn_run_sec.config(state=tk.DISABLED)

    # --- KAWORU ---
    def start_kaworu_extraction(self):
        self.btn_kaworu_run.config(state=tk.DISABLED)
        self.kaworu_log_area.config(state=tk.NORMAL)
        self.kaworu_log_area.delete(1.0, tk.END)
        self.kaworu_log_area.config(state=tk.DISABLED)
        threading.Thread(target=self.process_kaworu_pipeline, daemon=True).start()

    def process_kaworu_pipeline(self):
        self.log("[*] Initializing Kaworu Full Pipeline Extraction...", target_area=self.kaworu_log_area)
        for xeck_file in self.xeck_files:
            try:
                automator = XeckExtractorAutomator(xeck_path=xeck_file, log_callback=lambda msg: self.log(msg, target_area=self.kaworu_log_area))
                automator.run_pipeline(self.output_dir)
            except Exception as e:
                self.log(f"[!] Critical Error extracting {xeck_file}:\n{traceback.format_exc()}", target_area=self.kaworu_log_area)

        self.log("[✔] All XECK files processed successfully!", target_area=self.kaworu_log_area)
        self.root.after(0, lambda: self.btn_kaworu_run.config(state=tk.NORMAL))

    # --- SECONDARY MODULES (MISATO, KATSURAGI, 3 CHILDREN) ---
    def run_secondary_module(self):
        mode = self.var_module.get()
        self.btn_run_sec.config(state=tk.DISABLED)
        self.sec_log_area.config(state=tk.NORMAL)
        self.sec_log_area.delete(1.0, tk.END)
        self.sec_log_area.config(state=tk.DISABLED)

        if mode == "misato":
            threading.Thread(target=self.process_misato_pipeline, daemon=True).start()
        elif mode == "katsuragi":
            threading.Thread(target=self.process_katsuragi_pipeline, daemon=True).start()
        elif mode == "3children":
            threading.Thread(target=self.process_3children_pipeline, daemon=True).start()

    def process_misato_pipeline(self):
        self.log("[*] Initializing Misato Direct Texture Extraction...")
        for xeck_file in self.xeck_files:
            try:
                extractor = MisatoExtractor(xeck_path=xeck_file, log_callback=self.log)
                extractor.run_pipeline(self.output_dir)
            except Exception as e:
                self.log(f"[!] Exception during Misato extraction for {xeck_file}: {e}")

        self.log("[✔] All XECK files processed via Misato Textures Extractor!")
        self.root.after(0, lambda: self.btn_run_sec.config(state=tk.NORMAL))

    def process_katsuragi_pipeline(self):
        self.log("[*] Initializing Katsuragi Binary Byte-Mapper & TOC Analyzer...")
        try:
            graphics_base = int(self.ent_katsuragi_base.get(), 16)
        except ValueError:
            graphics_base = 0x400
            self.log("[!] Invalid base offset hex entered. Defaulting to 0x400.")

        csv_folder = os.path.dirname(self.csv_files[0]) if self.csv_files else ""
        if not csv_folder:
            self.log("[!] Warning: No RenderDoc CSVs selected. Mapping will categorize unknown/empty/title blocks only.")

        magi_log_directory = os.path.join(self.output_dir, "magi_logs")

        for xeck_file in self.xeck_files:
            self.log(f"\n[>] Mapping Container: {os.path.basename(xeck_file)}")
            try:
                mapper = KatsuragiMain(xeck_path=xeck_file, graphics_base=graphics_base, magi_log_dir=magi_log_directory)
                mapper.run_all(csv_folder=csv_folder, output_dir=self.output_dir)
                self.log(f"    [+] Katsuragi mapping finished for {os.path.basename(xeck_file)}.")
            except Exception as e:
                self.log(f"    [!] Exception during Katsuragi mapping for {xeck_file}: {e}")

        self.log("\n[✔] All XECK containers mapped and analyzed via Katsuragi Module!")
        self.root.after(0, lambda: self.btn_run_sec.config(state=tk.NORMAL))

    def process_3children_pipeline(self):
        if not self.csv_files:
            self.log("[!] Error: You must select RenderDoc CSV files to run Geometry & Analysis (The 3 Children).")
            self.root.after(0, lambda: self.btn_run_sec.config(state=tk.NORMAL))
            return

        self.log("[*] Initializing Cross-Examination Pipeline (Rei -> Shinji -> Asuka)...")
        offset_results_cache = []
        is_strip = self.var_strip.get()

        for csv_file in self.csv_files:
            csv_name = os.path.basename(csv_file)
            self.log(f"\n[>] [Child 1: Rei] Parsing RenderDoc CSV: {csv_name}")
            try:
                referencer = XeckOffsetCrossReferencer(csv_file)
                geom_data = referencer.get_geometry_data()
            except Exception as e:
                self.log(f"    [!] Error in Rei parsing CSV: {e}")
                continue

            for xeck_file in self.xeck_files:
                xeck_name = os.path.basename(xeck_file)
                try:
                    xeck_bytes = Path(xeck_file).read_bytes()
                except Exception as e:
                    self.log(f"    [!] Failed to read {xeck_name}")
                    continue

                v_matches = referencer.locate_vertex_buffer(xeck_bytes, ">") or referencer.locate_vertex_buffer(xeck_bytes, "<")
                i_matches = referencer.locate_index_buffer(xeck_bytes, ">") or referencer.locate_index_buffer(xeck_bytes, "<")

                if v_matches or i_matches:
                    self.log(f"    [+] Match found in {xeck_name}!")
                    offset_results_cache.append({"csv_name": csv_name, "xeck_name": xeck_name, "v_matches": v_matches, "i_matches": i_matches})
                    
                    obj_name = f"{os.path.splitext(csv_name)[0]}_from_{os.path.splitext(xeck_name)[0]}.obj"
                    obj_path = os.path.join(self.output_dir, obj_name)
                    
                    self.log(f"    [>] [Child 2: Shinji] Exporting mesh to {obj_name}...")
                    XeckObjExtractor.export_obj(output_path=obj_path, positions=geom_data["positions"], indices=geom_data["indices"], is_triangle_strip=is_strip)

        self.log("\n[>] [Child 3: Asuka] Analyzing offsets & writing Universal Key report...")
        try:
            analyzer = UniversalKeyAnalyzer(self.output_dir)
            analyzer.generate_report(offset_results_cache)
            self.log("    [+] Universal Key Analysis completed.")
        except Exception as e:
            self.log(f"    [!] Error in Asuka generating report: {e}")

        self.log("\n[+] Full Pipeline Execution Complete!")
        self.root.after(0, lambda: self.btn_run_sec.config(state=tk.NORMAL))


def main():
    root = tk.Tk()
    root.title("RAGE Geometry & XECK Universal Extractor Suite")
    root.geometry("1420x650")

    try:
        app_icon = tk.PhotoImage(file="Rockstar_San_Diego_Logo.png")
        root.iconphoto(False, app_icon)
    except Exception:
        pass

    # 1. INITIALIZE THEME MANAGER FIRST (Claims the top of the window)
    theme_manager = ThemeManager(root)

    # 2. CREATE AND PACK THE FRAMES
    left_frame = GUIProxy(root, width=650, height=650)
    left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
    left_frame.pack_propagate(False)

    separator = tk.Frame(root, bg="grey", width=2)
    separator.pack(side=tk.LEFT, fill=tk.Y, padx=5)

    right_frame = GUIProxy(root, width=750, height=650)
    right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
    right_frame.pack_propagate(False)

    # 3. LOAD AND RESIZE IMAGES
    try:
        from PIL import Image, ImageTk

        img_d_raw = Image.open("Dark-Mode.png")
        img_def_raw = Image.open("Default.png")

        # Force the image to fit cleanly in the left pane (550px wide)
        target_width = 550
        ratio_d = target_width / float(img_d_raw.width)
        ratio_def = target_width / float(img_def_raw.width)

        # Resize while maintaining aspect ratio
        img_d_res = img_d_raw.resize((target_width, int(img_d_raw.height * ratio_d)), Image.Resampling.LANCZOS)
        img_def_res = img_def_raw.resize((target_width, int(img_def_raw.height * ratio_def)), Image.Resampling.LANCZOS)

        root.img_dark = ImageTk.PhotoImage(img_d_res)
        root.img_default = ImageTk.PhotoImage(img_def_res)

    except ImportError:
        print("[!] Pillow (PIL) not installed. Using raw Tkinter subsampling.")
        try:
            # Fallback: Just divide the image size by 2 natively
            root.img_dark = tk.PhotoImage(file="Dark-Mode.png").subsample(2, 2)
            root.img_default = tk.PhotoImage(file="Default.png").subsample(2, 2)
        except Exception:
            root.img_dark, root.img_default = None, None
    except Exception as e:
        print(f"[!] Error loading banner images: {e}")
        root.img_dark, root.img_default = None, None

    # 4. CREATE BANNER WITH PADDING
    banner_label = tk.Label(left_frame)
    # padx=20 ensures empty padding on the left and right sides
    banner_label.pack(side=tk.BOTTOM, pady=10, padx=20)

    # 5. ATTACH BANNERS TO THEME MANAGER
    theme_manager.set_banners(banner_label, root.img_dark, root.img_default)

    # 6. INITIALIZE MODULES
    try:
        rpf_app = rpf_extractor.RPFExtractorApp(left_frame)
        rpf_app.lbl_files.config(text="★ Rockstar Package File v0 Extractor ★\n\nNo files selected", font=("Arial", 11, "bold"))
    except Exception as e:
        tk.Label(left_frame, text=f"Failed to load RPF Extractor module:\n{e}").pack(pady=20)

    xeck_app = XECKAnalyzerApp(right_frame)

    root.update_idletasks()
    theme_manager.init_colors()

    root.mainloop()


if __name__ == "__main__":
    main()
