import os
import sys
import csv
import time
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class KnownCsvEntry:
    csv_name: str
    object_name: str
    target_offset: Optional[int]
    raw_info: str


@dataclass
class XeckBlock:
    block_id: int
    category: str
    name: str
    start_offset: int
    end_offset: int
    size: int
    source_csv: str
    hex_preview: str
    notes: str


class MagiBridge:
    """
    Child Subprocess Manager for MAGI.
    Spawns MAGI as a child process and streams real-time progress logs over standard input pipes.
    """
    def __init__(self, magi_script_path: str = "magi.py", log_dir: str = "./magi_logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.magi_script = Path(magi_script_path)
        self.process: Optional[subprocess.Popen] = None
        self._spawn_magi()

    def _spawn_magi(self):
        """Spawns MAGI child process using sys.executable."""
        script_target = self.magi_script if self.magi_script.exists() else Path("magi.py")
        try:
            self.process = subprocess.Popen(
                [sys.executable, str(script_target), str(self.log_dir)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1  # Line buffered
            )
            self.send_event("INIT", f"MAGI listener child process spawned successfully (PID: {self.process.pid}).")
        except Exception as e:
            print(f"[Katsuragi Warning] Could not spawn MAGI child process: {e}")
            self.process = None

    def send_event(self, event_type: str, details: str):
        """Sends a structured log event to MAGI's stdin pipe."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        msg = f"[{timestamp}] [{event_type}] {details}\n"

        if self.process and self.process.stdin and self.process.poll() is None:
            try:
                self.process.stdin.write(msg)
                self.process.stdin.flush()
            except Exception as e:
                print(f"[Katsuragi] Pipe error writing to MAGI: {e}")
        else:
            # Fallback direct file writer if MAGI process is unreachable
            fallback_log = self.log_dir / "katsuragi_archive.log"
            with open(fallback_log, "a", encoding="utf-8") as f:
                f.write(msg)

    def close(self):
        if self.process:
            self.send_event("SHUTDOWN", "Katsuragi execution completed. Closing MAGI listener.")
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                self.process.wait(timeout=2)
            except Exception:
                self.process.kill()


def render_progress_bar(current: int, total: int, prefix: str = 'Progress', length: int = 35):
    """Prints a clean terminal percentage bar."""
    if total <= 0:
        total = 1
    percent = f"{100 * (current / float(total)):.1f}"
    filled_len = int(length * current // total)
    bar = '=' * filled_len + '-' * (length - filled_len)
    sys.stdout.write(f'\r[Katsuragi] {prefix} |{bar}| {percent}% ({current}/{total})')
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write('\n')


class KatsuragiMain:
    """
    Main Indexer Module: Katsuragi
    Processes CSV files individually, updates MAGI progress logs in real-time,
    and forces hard-drive flushes after every file.
    """
    MESH_ZONE_CUTOFF = 0x156ACF0  # Safeguard boundary against GPU TDR / non-geometry ranges

    def __init__(self, xeck_path: str, graphics_base: int = 0x400, magi_log_dir: str = "./magi_logs"):
        self.xeck_path = Path(xeck_path)
        self.graphics_base = graphics_base
        self.magi = MagiBridge(log_dir=magi_log_dir)

        if not self.xeck_path.exists():
            self.magi.send_event("ERROR", f"XECK file not found at path: {self.xeck_path}")
            raise FileNotFoundError(f"XECK container file not found: {self.xeck_path}")

        with open(self.xeck_path, "rb") as f:
            self.data = f.read()

        self.magi.send_event("FILE_LOADED", f"Successfully loaded {self.xeck_path.name} ({len(self.data)} bytes).")
        self.known_entries: List[KnownCsvEntry] = []
        self.blocks: List[XeckBlock] = []

    def index_single_csv(self, csv_file: Path) -> List[KnownCsvEntry]:
        """Indexes one single CSV file into memory."""
        entries = []
        self.magi.send_event("CSV_START", f"Parsing CSV file: {csv_file.name}")

        try:
            with open(csv_file, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                next(reader, None)  # Skip header
                for row in reader:
                    if not row:
                        continue
                    offset_val = None
                    for col in row:
                        col_str = col.strip()
                        if col_str.startswith(("0x", "0X")):
                            try:
                                offset_val = int(col_str, 16)
                                break
                            except ValueError:
                                pass
                        elif col_str.isdigit() and len(col_str) >= 4:
                            try:
                                val = int(col_str)
                                if 0 <= val < len(self.data):
                                    offset_val = val
                                    break
                            except ValueError:
                                pass

                    entries.append(KnownCsvEntry(
                        csv_name=csv_file.name,
                        object_name=csv_file.stem,
                        target_offset=offset_val,
                        raw_info=" | ".join(row[:5])
                    ))

            self.magi.send_event("CSV_DONE", f"Finished {csv_file.name}. Found {len(entries)} records.")
        except Exception as e:
            self.magi.send_event("CSV_ERROR", f"Error indexing {csv_file.name}: {e}")
            print(f"\n[Katsuragi Error] Processing {csv_file.name}: {e}")

        return entries

    def process_csv_directory(self, csv_folder_path: str, output_dir: str):
        """
        Iterates over all CSV files ONE AT A TIME.
        Flushes progress to disk on each step so no data is lost if execution halts.
        """
        folder = Path(csv_folder_path)
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        if not folder.exists() or not folder.is_dir():
            self.magi.send_event("WARN", f"CSV directory not found: {csv_folder_path}")
            print(f"[Katsuragi] CSV Directory '{csv_folder_path}' not found.")
            return

        csv_files = sorted(list(folder.glob("*.csv")))
        total_csvs = len(csv_files)

        if total_csvs == 0:
            self.magi.send_event("WARN", f"No CSV files found in directory: {csv_folder_path}")
            print("[Katsuragi] No CSV files found.")
            return

        self.magi.send_event("BATCH_START", f"Starting batch processing of {total_csvs} CSV files.")

        # Prepare real-time incremental output spreadsheet
        incremental_csv_path = out_path / f"{self.xeck_path.stem}_Incremental_Analysis.csv"

        with open(incremental_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["CSV_File", "Object_Name", "Target_Offset_Hex", "Target_Offset_Dec", "Raw_Info"])
            f.flush()
            os.fsync(f.fileno())

        render_progress_bar(0, total_csvs, prefix="CSV Indexing Progress")

        for idx, csv_file in enumerate(csv_files, start=1):
            # 1. Index current CSV file
            entries = self.index_single_csv(csv_file)
            self.known_entries.extend(entries)

            # 2. Append directly to disk & force OS file flush
            with open(incremental_csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                for entry in entries:
                    off_hex = hex(entry.target_offset) if entry.target_offset is not None else "N/A"
                    off_dec = entry.target_offset if entry.target_offset is not None else "N/A"
                    writer.writerow([entry.csv_name, entry.object_name, off_hex, off_dec, entry.raw_info])
                f.flush()
                os.fsync(f.fileno())

            # 3. Inform MAGI child script
            self.magi.send_event(
                "CHECKPOINT",
                f"Completed {idx}/{total_csvs} ({csv_file.name}). Total records archived: {len(self.known_entries)}"
            )

            # 4. Update terminal percentage bar
            render_progress_bar(idx, total_csvs, prefix="CSV Indexing Progress")

        print(f"\n[Katsuragi] CSV Indexing complete. Incremental log saved at: {incremental_csv_path}")

    def map_xeck_structure(self, output_dir: str):
        """
        Maps binary blocks across the XECK file using anti-TDR alignment rules.
        """
        self.magi.send_event("MAP_START", "Beginning binary block mapping scan across XECK container.")
        self.blocks.clear()
        file_len = len(self.data)
        block_counter = 0
        current_offset = 0

        # Header Block
        if file_len >= 0x40:
            preview = self.data[0:0x40].hex(" ").upper()
            self.blocks.append(XeckBlock(
                block_id=block_counter, category="Title Block", name="RAGE Resource Container Header",
                start_offset=0x00, end_offset=0x3F, size=0x40, source_csv="N/A",
                hex_preview=preview[:96], notes="Resource Magic, Version Flags, Segment Page Pointers"
            ))
            block_counter += 1
            current_offset = 0x40

        # Build fast lookup map for indexed offsets
        known_map = {}
        for entry in self.known_entries:
            if entry.target_offset is not None:
                rel_off = entry.target_offset
                if rel_off >= 0x1000000:
                    rel_off = (rel_off % 0x100000) + self.graphics_base
                if 0 <= rel_off < file_len:
                    known_map[rel_off] = entry

        render_progress_bar(current_offset, file_len, prefix="XECK Structure Scanning")

        while current_offset < file_len:
            # Check for known CSV offset match
            if current_offset in known_map:
                entry = known_map[current_offset]
                start_off = current_offset
                block_size = 0x400
                current_offset = min(file_len, current_offset + block_size)
                preview = self.data[start_off:start_off + 32].hex(" ").upper()

                self.blocks.append(XeckBlock(
                    block_id=block_counter, category="Known Object Block", name=f"CSV Object: {entry.object_name}",
                    start_offset=start_off, end_offset=current_offset - 1, size=block_size,
                    source_csv=entry.csv_name, hex_preview=preview, notes=f"Matched via {entry.csv_name}"
                ))
                block_counter += 1
                render_progress_bar(current_offset, file_len, prefix="XECK Structure Scanning")
                continue

            # DDS Texture Magic Header
            if self.data[current_offset:current_offset + 4] == b"DDS ":
                start_off = current_offset
                current_offset = min(file_len, current_offset + 0x20000)
                preview = self.data[start_off:start_off + 32].hex(" ").upper()

                self.blocks.append(XeckBlock(
                    block_id=block_counter, category="Known Object Block", name="Embedded DDS Texture Stream",
                    start_offset=start_off, end_offset=current_offset - 1, size=current_offset - start_off,
                    source_csv="N/A", hex_preview=preview, notes="DDS Magic Header"
                ))
                block_counter += 1
                render_progress_bar(current_offset, file_len, prefix="XECK Structure Scanning")
                continue

            # Non-aligned or post-mesh cutoff safety check (prevents GPU TDR freezes)
            is_aligned = (current_offset % 16 == 0)
            in_mesh_zone = (current_offset <= self.MESH_ZONE_CUTOFF)

            step = 0x400 if (not in_mesh_zone or not is_aligned) else 0x200
            cat_name = "Auxiliary Data Block" if (not in_mesh_zone or not is_aligned) else "Unknown Data Block"

            start_off = current_offset
            current_offset = min(file_len, current_offset + step)
            preview = self.data[start_off:start_off + min(32, current_offset - start_off)].hex(" ").upper()

            self.blocks.append(XeckBlock(
                block_id=block_counter, category=cat_name, name="Binary Payload Stream",
                start_offset=start_off, end_offset=current_offset - 1, size=current_offset - start_off,
                source_csv="N/A", hex_preview=preview, notes="Aligned geometry or auxiliary stream"
            ))
            block_counter += 1
            render_progress_bar(current_offset, file_len, prefix="XECK Structure Scanning")

        render_progress_bar(file_len, file_len, prefix="XECK Structure Scanning")
        self.magi.send_event("MAP_DONE", f"Structural mapping complete. Mapped {len(self.blocks)} blocks.")

    def run_all(self, csv_folder: str, output_dir: str):
        """Main execution workflow."""
        print(f"[*] Starting Katsuragi Main on container: {self.xeck_path.name}")
        self.process_csv_directory(csv_folder, output_dir)
        self.map_xeck_structure(output_dir)
        self.magi.close()
        print(f"[✔] Katsuragi processing finished successfully.")



if __name__ == "__main__":
    xeck_file = sys.argv[1] if len(sys.argv) > 1 else "char_usa.xeck"
    csv_dir = sys.argv[2] if len(sys.argv) > 2 else "./csv_captures/"
    output_directory = sys.argv[3] if len(sys.argv) > 3 else "./katsuragi_output/"

    if os.path.exists(xeck_file):
        katsuragi = KatsuragiMain(xeck_file)
        katsuragi.run_all(csv_folder=csv_dir, output_dir=output_directory)
    else:
        print(f"[Katsuragi Main Error] Target XECK file '{xeck_file}' not found.")
