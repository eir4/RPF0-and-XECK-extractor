import struct
import csv
from pathlib import Path


class XeckOffsetCrossReferencer:
    """
    Child Module 1 (Rei): Handles RenderDoc CSV parsing and byte-scanning of XECK
    binary data to cross-reference Vertex/Index buffers. Now integrated with the
    RAGE Universal Key alignment model (0x400 / 1024-byte page boundary) and relative
    header pointer translation.
    """

    def __init__(self, csv_path: str, graphics_base_offset: int = 0x400):
        self.csv_path = Path(csv_path)
        self.indices = []
        self.positions = []
        self.graphics_base_offset = graphics_base_offset
        self._parse_renderdoc_csv()

    def _parse_renderdoc_csv(self):
        """Robust index-based CSV parser that ignores spacing quirks and detects delimiters."""
        with open(self.csv_path, mode="r", encoding="utf-8-sig") as f:
            first_line = f.readline()
            delimiter = ','
            if '\t' in first_line:
                delimiter = '\t'
            elif ';' in first_line:
                delimiter = ';'

            f.seek(0)
            reader = csv.reader(f, delimiter=delimiter)

            try:
                raw_headers = next(reader)
            except StopIteration:
                raise ValueError("CSV file is empty.")

            headers = [h.strip() for h in raw_headers]

            idx_col = next((i for i, h in enumerate(headers) if h.upper() in ["IDX", "VTX", "INDEX"]), None)
            pos_x_col = next((i for i, h in enumerate(headers) if "POSITION.X" in h.upper() or h.upper() == "POS.X"),
                             None)
            pos_y_col = next((i for i, h in enumerate(headers) if "POSITION.Y" in h.upper() or h.upper() == "POS.Y"),
                             None)
            pos_z_col = next((i for i, h in enumerate(headers) if "POSITION.Z" in h.upper() or h.upper() == "POS.Z"),
                             None)

            if pos_x_col is None or pos_y_col is None or pos_z_col is None:
                raise ValueError(f"Missing POSITION columns in {self.csv_path.name}. Found headers: {headers}")

            for row in reader:
                if not row or len(row) <= max(pos_x_col, pos_y_col, pos_z_col):
                    continue

                try:
                    if idx_col is not None and len(row) > idx_col and row[idx_col].strip():
                        self.indices.append(int(float(row[idx_col].strip())))

                    self.positions.append((
                        float(row[pos_x_col].strip()),
                        float(row[pos_y_col].strip()),
                        float(row[pos_z_col].strip())
                    ))
                except ValueError:
                    continue

    def detect_graphics_base_offset(self, xeck_bytes: bytes, default_alignment: int = 0x400) -> int:
        """
        Detects the RAGE Graphics Segment start by identifying the alignment boundary
        following system segment zero-padding (e.g. 0x400 / 1024 bytes).
        """
        if len(xeck_bytes) < default_alignment:
            return default_alignment

        # Search for non-zero GPU payload data aligned to page boundary
        for boundary in range(default_alignment, min(len(xeck_bytes), 0x2000), default_alignment):
            # Check if region prior to boundary contains alignment padding (all 0x00s)
            padding_region = xeck_bytes[boundary - 0x100:boundary]
            if padding_region and all(b == 0 for b in padding_region):
                # Verify that non-zero data begins at boundary
                if any(b != 0 for b in xeck_bytes[boundary:boundary + 0x40]):
                    return boundary

        return default_alignment

    def scan_header_for_pointer(self, xeck_bytes: bytes, target_offset: int, graphics_base: int,
                                endianness: str = ">") -> list:
        """
        Scans the System Segment metadata (0x00 to graphics_base) for 32-bit integer
        pointers matching either absolute file offsets or relative graphics segment offsets.
        """
        header_bytes = xeck_bytes[:graphics_base]
        matches = []

        relative_offset = target_offset - graphics_base if target_offset >= graphics_base else target_offset

        # Pack 32-bit uint pointer representations
        targets_to_check = [
            ("relative_graphics", relative_offset),
            ("absolute_file", target_offset)
        ]

        for ptr_type, val in targets_to_check:
            if val < 0:
                continue
            ptr_pattern = struct.pack(f"{endianness}I", val)
            pos = 0
            while True:
                idx = header_bytes.find(ptr_pattern, pos)
                if idx == -1:
                    break
                matches.append({
                    "header_offset": idx,
                    "header_hex": hex(idx),
                    "pointer_type": ptr_type,
                    "value_hex": hex(val)
                })
                pos = idx + 1

        return matches

    def locate_vertex_buffer(self, xeck_bytes: bytes, endianness: str = ">", start_offset: int = None):
        """
        Scans binary data for vertex coordinates and translates absolute file offsets
        to relative Graphics Segment offsets and System Segment header pointers.
        """
        if len(self.positions) < 3:
            return []

        base_offset = start_offset if start_offset is not None else self.detect_graphics_base_offset(xeck_bytes)
        v0, v1, v2 = self.positions[0], self.positions[1], self.positions[2]
        sig_v0 = struct.pack(f"{endianness}fff", *v0)

        matches = []
        search_pos = base_offset

        while True:
            offset = xeck_bytes.find(sig_v0, search_pos)
            if offset == -1:
                break

            sig_v1 = struct.pack(f"{endianness}fff", *v1)
            sig_v2 = struct.pack(f"{endianness}fff", *v2)

            for test_stride in [12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 64]:
                v1_pos = offset + test_stride
                v2_pos = offset + (test_stride * 2)

                if v2_pos + 12 <= len(xeck_bytes):
                    if (xeck_bytes[v1_pos:v1_pos + 12] == sig_v1 and
                            xeck_bytes[v2_pos:v2_pos + 12] == sig_v2):
                        rel_offset = offset - base_offset
                        header_pointers = self.scan_header_for_pointer(xeck_bytes, offset, base_offset, endianness)

                        matches.append({
                            "offset": offset,
                            "hex": hex(offset),
                            "graphics_base_hex": hex(base_offset),
                            "relative_graphics_offset": rel_offset,
                            "relative_graphics_hex": hex(rel_offset),
                            "stride": test_stride,
                            "endian": endianness,
                            "header_pointers": header_pointers
                        })
                        break
            search_pos = offset + 1
        return matches

    def locate_index_buffer(self, xeck_bytes: bytes, endianness: str = ">", start_offset: int = None):
        """
        Scans binary data for triangle indices and translates absolute file offsets
        to relative Graphics Segment offsets and System Segment header pointers.
        """
        if not self.indices or len(self.indices) < 6:
            return []

        base_offset = start_offset if start_offset is not None else self.detect_graphics_base_offset(xeck_bytes)
        idx_pattern = struct.pack(f"{endianness}6H", *[int(i) for i in self.indices[:6]])
        matches = []
        search_pos = base_offset

        while True:
            offset = xeck_bytes.find(idx_pattern, search_pos)
            if offset == -1:
                break

            rel_offset = offset - base_offset
            header_pointers = self.scan_header_for_pointer(xeck_bytes, offset, base_offset, endianness)

            matches.append({
                "offset": offset,
                "hex": hex(offset),
                "graphics_base_hex": hex(base_offset),
                "relative_graphics_offset": rel_offset,
                "relative_graphics_hex": hex(rel_offset),
                "count": len(self.indices),
                "endian": endianness,
                "header_pointers": header_pointers
            })
            search_pos = offset + 1
        return matches

    def get_geometry_data(self):
        """Returns the parsed positions and indices for external extraction usage."""
        return {
            "positions": self.positions,
            "indices": self.indices
        }
