import os
import struct
import zlib
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, scrolledtext
from queue import Queue


class RPFExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("eira's RPF0 Extractor GUI - Universal Endian")
        self.root.geometry("700x500")

        # UI Elements
        self.lbl_files = tk.Label(root, text="No files selected", wraplength=500, justify="left")
        self.lbl_files.pack(pady=10)

        self.btn_select_files = tk.Button(root, text="Select RPF0 Files", command=self.select_files)
        self.btn_select_files.pack(pady=5)

        self.lbl_output = tk.Label(root, text="Default Output: Same as source files", wraplength=500)
        self.lbl_output.pack(pady=10)

        self.btn_select_output = tk.Button(root, text="Select Output Directory (Optional)", command=self.select_output)
        self.btn_select_output.pack(pady=5)

        self.btn_extract = tk.Button(root, text="Start Extraction", command=self.start_extraction, state=tk.DISABLED,
                                     bg="green", fg="white", font=("Arial", 10, "bold"))
        self.btn_extract.pack(pady=15)

        self.log_area = scrolledtext.ScrolledText(root, width=80, height=15, state=tk.DISABLED, bg="black",
                                                  fg="lightgreen")
        self.log_area.pack(padx=10, pady=10)

        self.selected_files = []
        self.output_dir = ""
        self.extraction_thread = None

    def log(self, message):
        """Thread-safe logging to the GUI."""
        self.log_area.config(state=tk.NORMAL)
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.see(tk.END)
        self.log_area.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def select_files(self):
        files = filedialog.askopenfilenames(title="Select RPF0 files",
                                            filetypes=[("RPF Files", "*.rpf *.RPF"), ("All Files", "*.*")])
        if files:
            self.selected_files = list(files)
            self.lbl_files.config(text=f"{len(self.selected_files)} file(s) selected.")
            self.btn_extract.config(state=tk.NORMAL)

    def select_output(self):
        dir_path = filedialog.askdirectory(title="Select Output Directory")
        if dir_path:
            self.output_dir = dir_path
            self.lbl_output.config(text=f"Output: {self.output_dir}")

    def start_extraction(self):
        self.btn_extract.config(state=tk.DISABLED)
        self.btn_select_files.config(state=tk.DISABLED)
        self.log_area.config(state=tk.NORMAL)
        self.log_area.delete(1.0, tk.END)
        self.log_area.config(state=tk.DISABLED)

        self.extraction_thread = threading.Thread(target=self.process_extraction_queue, daemon=True)
        self.extraction_thread.start()

    def process_extraction_queue(self):
        queue = Queue()
        for file in self.selected_files:
            out_path = self.output_dir if self.output_dir else os.path.dirname(file)
            folder_name = os.path.splitext(os.path.basename(file))[0] + "_extracted"
            queue.put((file, os.path.join(out_path, folder_name)))

        while not queue.empty():
            current_rpf, current_out = queue.get()
            self.log(f"[*] Starting extraction: {os.path.basename(current_rpf)}")

            nested_rpfs = self.extract_rpf0(current_rpf, current_out)

            for nested_rpf in nested_rpfs:
                nested_folder = os.path.splitext(nested_rpf)[0] + "_extracted"
                queue.put((nested_rpf, nested_folder))
                self.log(f"[*] Nested archive queued: {os.path.basename(nested_rpf)}")

        self.log("\n[+] All extractions completed successfully!")
        self.root.after(0, lambda: self.btn_extract.config(state=tk.NORMAL))
        self.root.after(0, lambda: self.btn_select_files.config(state=tk.NORMAL))

    def extract_rpf0(self, rpf_path, output_dir):
        nested_rpfs_found = []

        try:
            with open(rpf_path, 'rb') as f:
                header_data = f.read(20)
                if len(header_data) < 20:
                    raise ValueError("File is too small to be a valid RPF.")

                # Auto-Detect Endianness (Xbox 360 vs PC)
                toc_size_be, obj_count_be, _, _ = struct.unpack('>IIII', header_data[4:20])
                toc_size_le, obj_count_le, _, _ = struct.unpack('<IIII', header_data[4:20])

                # If Big-Endian obj_count is impossibly large, it's a Little-Endian PC file
                if obj_count_be > 1000000 and obj_count_le < 1000000:
                    endian = '<'
                    obj_count = obj_count_le
                    self.log("    -> Detected PC Little-Endian architecture.")
                else:
                    endian = '>'
                    obj_count = obj_count_be
                    self.log("    -> Detected Console Big-Endian architecture.")

                f.seek(2048)  # TOC offset
                entries = []

                for i in range(obj_count):
                    entry_data = f.read(16)

                    if len(entry_data) < 16:
                        raise EOFError(f"Unexpected End of File at index {i}. Archive may be corrupted.")

                    # Read INT24 using appropriate endianness
                    name_offset = int.from_bytes(entry_data[0:3], byteorder='big' if endian == '>' else 'little')
                    identifier_flag = entry_data[3]

                    val1, val2, val3 = struct.unpack(f'{endian}III', entry_data[4:16])

                    entries.append({
                        'index': i,
                        'name_offset': name_offset,
                        'is_dir': identifier_flag == 0x80,
                        'val1': val1,
                        'val2': val2,
                        'val3': val3
                    })

                names_start_offset = 2048 + (obj_count * 16)

                def get_entry_name(offset):
                    saved_pos = f.tell()
                    f.seek(names_start_offset + offset)
                    chars = []
                    while True:
                        char = f.read(1)
                        if not char or char == b'\x00':
                            break
                        chars.append(char)
                    f.seek(saved_pos)
                    return b''.join(chars).decode('ascii', errors='ignore')

                def process_directory(entry_index, current_path):
                    directory_entry = entries[entry_index]
                    first_child_index = directory_entry['val1']
                    child_count = directory_entry['val2']

                    # Failsafe: Convert byte offset to array index if needed
                    if first_child_index >= len(entries) and first_child_index % 16 == 0:
                        first_child_index = first_child_index // 16

                    for i in range(child_count):
                        child_index = first_child_index + i

                        if child_index >= len(entries):
                            continue  # Skip corrupted structural links

                        child_entry = entries[child_index]

                        entry_name = get_entry_name(child_entry['name_offset'])
                        if entry_name == "/":
                            entry_name = "root"

                        target_path = os.path.join(current_path, entry_name)

                        if child_entry['is_dir']:
                            os.makedirs(target_path, exist_ok=True)
                            process_directory(child_index, target_path)
                        else:
                            data_offset = child_entry['val1']
                            compressed_size = child_entry['val2']
                            uncompressed_size = child_entry['val3']

                            f.seek(data_offset)
                            file_data = f.read(compressed_size)

                            if compressed_size != uncompressed_size:
                                try:
                                    file_data = zlib.decompress(file_data, -15)
                                except zlib.error as e:
                                    self.log(f"    [-] Decompress failed for {entry_name}")
                                    continue

                            with open(target_path, 'wb') as out_file:
                                out_file.write(file_data)

                            if entry_name.lower().endswith('.rpf'):
                                nested_rpfs_found.append(target_path)

                if len(entries) > 0 and entries[0]['is_dir']:
                    os.makedirs(output_dir, exist_ok=True)
                    process_directory(0, output_dir)
                else:
                    self.log("[-] Invalid root directory TOC entry.")

        except Exception as e:
            self.log(f"[-] Critical Error processing {os.path.basename(rpf_path)}: {str(e)}")

        return nested_rpfs_found


if __name__ == "__main__":
    root = tk.Tk()
    app = RPFExtractorApp(root)
    root.mainloop()