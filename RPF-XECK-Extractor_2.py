import os
import threading
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

# Import legacy RPF Extractor
import rpf_extractor


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

        self.tab_geometry = tk.Frame(self.notebook)
        self.tab_kaworu = tk.Frame(self.notebook)
        self.tab_katsuragi = tk.Frame(self.notebook)
        self.tab_textures = tk.Frame(self.notebook)
        self.tab_skeleton = tk.Frame(self.notebook)

        self.notebook.add(self.tab_geometry, text="Geometry & Analysis (CSV)")
        self.notebook.add(self.tab_kaworu, text="Automated Direct Extractor (Kaworu)")
        self.notebook.add(self.tab_katsuragi, text="TOC & Binary Mapper (Katsuragi)")
        self.notebook.add(self.tab_textures, text="Textures Module")
        self.notebook.add(self.tab_skeleton, text="Skeleton/Bones Module")

        self.xeck_files = []
        self.csv_files = []
        self.output_dir = ""

        # Build UI Tabs
        self._build_geometry_tab()
        self._build_kaworu_tab()
        self._build_katsuragi_tab()
        self._build_texture_tab()
        self._build_skeleton_tab()

    def _build_geometry_tab(self):
        tk.Label(
            self.tab_geometry,
            text="XECK Cross-Examiner & Universal Key Suite",
            font=("Arial", 11, "bold"),
        ).pack(pady=(10, 0))

        self.lbl_xecks = tk.Label(self.tab_geometry, text="0 XECK files selected", wraplength=300)
        self.lbl_xecks.pack(pady=3)
        self.btn_xecks = tk.Button(self.tab_geometry, text="Select XECK Files", command=self.select_xecks)
        self.btn_xecks.pack(pady=3)

        self.lbl_csvs = tk.Label(self.tab_geometry, text="0 CSV files selected", wraplength=300)
        self.lbl_csvs.pack(pady=3)
        self.btn_csvs = tk.Button(self.tab_geometry, text="Select RenderDoc CSVs", command=self.select_csvs)
        self.btn_csvs.pack(pady=3)

        self.lbl_output = tk.Label(self.tab_geometry, text="Output Directory: Unset (Required)", wraplength=300)
        self.lbl_output.pack(pady=3)
        self.btn_output = tk.Button(self.tab_geometry, text="Select Output Directory", command=self.select_output)
        self.btn_output.pack(pady=3)

        self.var_strip = tk.BooleanVar(value=False)
        self.chk_strip = tk.Checkbutton(
            self.tab_geometry,
            text="Use Triangle Strip Topology (For Faces/Necks)",
            variable=self.var_strip,
        )
        self.chk_strip.pack(pady=5)

        self.btn_analyze = tk.Button(
            self.tab_geometry,
            text="Start Cross-Examination Pipeline",
            command=self.start_analysis,
            state=tk.DISABLED,
            bg="blue",
            fg="white",
            font=("Arial", 10, "bold"),
        )
        self.btn_analyze.pack(pady=10)

        self.log_area = scrolledtext.ScrolledText(
            self.tab_geometry, width=75, height=12, state=tk.DISABLED, bg="black", fg="cyan"
        )
        self.log_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

    def _build_kaworu_tab(self):
        tk.Label(
            self.tab_kaworu,
            text="Kaworu: Direct XECK Container Extractor",
            font=("Arial", 11, "bold"),
        ).pack(pady=(10, 0))

        tk.Label(
            self.tab_kaworu,
            text="Discovers and extracts ALL registered sub-meshes (including body parts),\n"
            "DDS textures, and bone IDs directly without needing RenderDoc CSVs.",
            font=("Arial", 9, "italic"),
        ).pack(pady=5)

        # Removed legacy Endian and Graphics Base UI elements as Kaworu auto-detects them now

        self.btn_kaworu_run = tk.Button(
            self.tab_kaworu,
            text="Run Automated Direct Extraction (Kaworu)",
            command=self.start_kaworu_extraction,
            bg="purple",
            fg="white",
            font=("Arial", 10, "bold"),
        )
        self.btn_kaworu_run.pack(pady=10)

        self.kaworu_log_area = scrolledtext.ScrolledText(
            self.tab_kaworu, width=75, height=14, state=tk.DISABLED, bg="black", fg="lime"
        )
        self.kaworu_log_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

    def _build_katsuragi_tab(self):
        tk.Label(
            self.tab_katsuragi,
            text="Katsuragi: Container Byte Mapper & TOC Reverse-Engineering Suite",
            font=("Arial", 11, "bold"),
        ).pack(pady=(10, 0))

        tk.Label(
            self.tab_katsuragi,
            text="Indexes RenderDoc CSV records, performs continuous 0x00->EOF byte-mapping,\n"
            "categorizes blocks (Title, TOC, Empty, Known, Unknown), and exports detailed Text Maps\n"
            "and Analysis CSV Spreadsheets for TOC reverse-engineering.",
            font=("Arial", 9, "italic"),
        ).pack(pady=5)

        base_frame = tk.Frame(self.tab_katsuragi)
        base_frame.pack(pady=5)
        tk.Label(base_frame, text="Graphics Base Offset: ").pack(side=tk.LEFT)
        self.ent_katsuragi_base = tk.Entry(base_frame, width=10)
        self.ent_katsuragi_base.insert(0, "0x400")
        self.ent_katsuragi_base.pack(side=tk.LEFT)

        self.btn_katsuragi_run = tk.Button(
            self.tab_katsuragi,
            text="Run Binary Mapping & TOC Analysis (Katsuragi)",
            command=self.start_katsuragi_mapping,
            bg="darkorange",
            fg="white",
            font=("Arial", 10, "bold"),
        )
        self.btn_katsuragi_run.pack(pady=10)

        self.katsuragi_log_area = scrolledtext.ScrolledText(
            self.tab_katsuragi, width=75, height=14, state=tk.DISABLED, bg="black", fg="gold"
        )
        self.katsuragi_log_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

    def _build_texture_tab(self):
        tk.Label(self.tab_textures, text="Texture Extraction Module (Powered by Kaworu)", font=("Arial", 11, "bold")).pack(pady=20)

    def _build_skeleton_tab(self):
        tk.Label(self.tab_skeleton, text="Skeleton & Rigging Module (Powered by Kaworu)", font=("Arial", 11, "bold")).pack(pady=20)

    def log(self, message: str, target_area: Optional[scrolledtext.ScrolledText] = None):
        area = target_area or self.log_area
        area.config(state=tk.NORMAL)
        area.insert(tk.END, message + "\n")
        area.see(tk.END)
        area.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def kaworu_log(self, message: str):
        self.log(message, target_area=self.kaworu_log_area)

    def katsuragi_log(self, message: str):
        self.log(message, target_area=self.katsuragi_log_area)

    def update_btn_state(self):
        if self.xeck_files and self.csv_files and self.output_dir:
            self.btn_analyze.config(state=tk.NORMAL)
        else:
            self.btn_analyze.config(state=tk.DISABLED)

    def select_xecks(self):
        files = filedialog.askopenfilenames(
            title="Select XECK files",
            filetypes=[("XECK Files", "*.xeck"), ("All Files", "*.*")],
        )
        if files:
            self.xeck_files = list(files)
            self.lbl_xecks.config(text=f"{len(self.xeck_files)} XECK file(s) selected.")
            self.update_btn_state()

    def select_csvs(self):
        files = filedialog.askopenfilenames(
            title="Select RenderDoc CSVs", filetypes=[("CSV Files", "*.csv")]
        )
        if files:
            self.csv_files = list(files)
            self.lbl_csvs.config(text=f"{len(self.csv_files)} CSV file(s) selected.")
            self.update_btn_state()

    def select_output(self):
        dir_path = filedialog.askdirectory(title="Select Output Directory")
        if dir_path:
            self.output_dir = dir_path
            self.lbl_output.config(text=f"Output: {self.output_dir}")
            self.update_btn_state()

    def start_analysis(self):
        self.btn_analyze.config(state=tk.DISABLED)
        self.log_area.config(state=tk.NORMAL)
        self.log_area.delete(1.0, tk.END)
        self.log_area.config(state=tk.DISABLED)
        threading.Thread(target=self.process_pipeline, daemon=True).start()

    def process_pipeline(self):
        self.log("[*] Initializing Cross-Examination Pipeline...")
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
                    offset_results_cache.append(
                        {
                            "csv_name": csv_name,
                            "xeck_name": xeck_name,
                            "v_matches": v_matches,
                            "i_matches": i_matches,
                        }
                    )

                    obj_name = f"{os.path.splitext(csv_name)[0]}_from_{os.path.splitext(xeck_name)[0]}.obj"
                    obj_path = os.path.join(self.output_dir, obj_name)

                    self.log(f"    [>] [Child 2: Shinji] Exporting mesh to {obj_name}...")
                    XeckObjExtractor.export_obj(
                        output_path=obj_path,
                        positions=geom_data["positions"],
                        indices=geom_data["indices"],
                        is_triangle_strip=is_strip,
                    )

        self.log("\n[>] [Child 3: Asuka] Analyzing offsets & writing Universal Key report...")
        try:
            analyzer = UniversalKeyAnalyzer(self.output_dir)
            analyzer.generate_report(offset_results_cache)
            self.log("    [+] Universal Key Analysis completed.")
        except Exception as e:
            self.log(f"    [!] Error in Asuka generating report: {e}")

        self.log("\n[+] Full Pipeline Execution Complete!")
        self.root.after(0, lambda: self.btn_analyze.config(state=tk.NORMAL))

    def start_kaworu_extraction(self):
        if not self.xeck_files:
            self.kaworu_log("[!] Error: No XECK files selected. Select XECK files under 'Geometry & Analysis' tab first.")
            return

        if not self.output_dir:
            self.kaworu_log("[!] Error: Output directory not selected. Select Output Directory first.")
            return

        self.btn_kaworu_run.config(state=tk.DISABLED)
        self.kaworu_log_area.config(state=tk.NORMAL)
        self.kaworu_log_area.delete(1.0, tk.END)
        self.kaworu_log_area.config(state=tk.DISABLED)

        threading.Thread(target=self.process_kaworu_pipeline, daemon=True).start()

    def process_kaworu_pipeline(self):
        self.kaworu_log("[*] Initializing Kaworu Direct Automated Extraction...")

        for xeck_file in self.xeck_files:
            try:
                # Kaworu now calculates parameters intrinsically. Only xeck_path is needed.
                automator = XeckExtractorAutomator(xeck_path=xeck_file)
                # Updated method call to match Kaworu.py's run_pipeline
                automator.run_pipeline(self.output_dir)
                self.kaworu_log(f"    [+] Successfully extracted meshes for {os.path.basename(xeck_file)}")
            except Exception as e:
                self.kaworu_log(f"[!] Exception during Kaworu extraction for {xeck_file}: {e}")

        self.kaworu_log("[✔] All XECK files processed via Kaworu Automator! Check your console output for detailed vertex logs.")
        self.root.after(0, lambda: self.btn_kaworu_run.config(state=tk.NORMAL))

    def start_katsuragi_mapping(self):
        if not self.xeck_files:
            self.katsuragi_log("[!] Error: No XECK files selected. Select XECK files under 'Geometry & Analysis' tab first.")
            return

        if not self.output_dir:
            self.katsuragi_log("[!] Error: Output directory not selected. Select Output Directory first.")
            return

        self.btn_katsuragi_run.config(state=tk.DISABLED)
        self.katsuragi_log_area.config(state=tk.NORMAL)
        self.katsuragi_log_area.delete(1.0, tk.END)
        self.katsuragi_log_area.config(state=tk.DISABLED)

        threading.Thread(target=self.process_katsuragi_pipeline, daemon=True).start()

    def process_katsuragi_pipeline(self):
        self.katsuragi_log("[*] Initializing Katsuragi Binary Byte-Mapper & TOC Analyzer...")

        try:
            graphics_base = int(self.ent_katsuragi_base.get(), 16)
        except ValueError:
            graphics_base = 0x400
            self.katsuragi_log("[!] Invalid base offset hex entered. Defaulting to 0x400.")

        csv_folder = ""
        if self.csv_files:
            csv_folder = os.path.dirname(self.csv_files[0])
            self.katsuragi_log(f"[*] Derived RenderDoc CSV Folder: {csv_folder}")
        else:
            self.katsuragi_log("[!] Warning: No RenderDoc CSVs selected. Mapping will categorize unknown/empty/title blocks only.")

        magi_log_directory = os.path.join(self.output_dir, "magi_logs")

        for xeck_file in self.xeck_files:
            self.katsuragi_log(f"\n[>] Mapping Container: {os.path.basename(xeck_file)}")
            try:
                mapper = KatsuragiMain(
                    xeck_path=xeck_file,
                    graphics_base=graphics_base,
                    magi_log_dir=magi_log_directory,
                )
                mapper.run_all(csv_folder=csv_folder, output_dir=self.output_dir)

                self.katsuragi_log(f"    [+] Katsuragi mapping finished for {os.path.basename(xeck_file)}.")
                self.katsuragi_log(f"    [+] Incremental analysis CSV and MAGI log files exported to output directory.")

            except Exception as e:
                self.katsuragi_log(f"    [!] Exception during Katsuragi mapping for {xeck_file}: {e}")

        self.katsuragi_log("\n[✔] All XECK containers mapped and analyzed via Katsuragi Module!")
        self.root.after(0, lambda: self.btn_katsuragi_run.config(state=tk.NORMAL))


def main():
    root = tk.Tk()
    root.title("RAGE Geometry & XECK Universal Extractor Suite")
    root.geometry("1420x650")

    left_frame = GUIProxy(root, width=650, height=650)
    left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
    left_frame.pack_propagate(False)

    separator = tk.Frame(root, bg="grey", width=2)
    separator.pack(side=tk.LEFT, fill=tk.Y, padx=5)

    right_frame = GUIProxy(root, width=750, height=650)
    right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
    right_frame.pack_propagate(False)

    try:
        rpf_app = rpf_extractor.RPFExtractorApp(left_frame)
        rpf_app.lbl_files.config(text="OpenRPF0 Extractor\n\nNo files selected")
    except Exception as e:
        tk.Label(left_frame, text=f"Failed to load RPF Extractor module:\n{e}").pack(pady=20)

    xeck_app = XECKAnalyzerApp(right_frame)

    root.mainloop()


if __name__ == "__main__":
    main()