import os
import datetime
from collections import defaultdict
from pathlib import Path


class UniversalKeyAnalyzer:
    """
    Child Module 3 (Asuka): Analyzes offset findings across cross-examination runs
    to uncover XECK structural indexing patterns (header table locations, section offsets,
    and relative pointer structures) needed to achieve direct native extraction.
    """

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.base_result = self.output_dir / "results.txt"
        self.secondary_result = self.output_dir / "results-2.txt"
        self.master_result = self.output_dir / "Master-results.txt"

    def generate_report(self, offset_data: list):
        """
        Expects a list of dictionaries representing offset findings:
        [{'csv_name': str, 'xeck_name': str, 'v_matches': list, 'i_matches': list}, ...]
        """
        report_content = self._analyze_data(offset_data)
        self._save_results(report_content)

    def _analyze_data(self, offset_data: list) -> str:
        lines = [
            f"XECK Structural Indexing Pattern Analysis - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 70,
            ""
        ]

        if not offset_data:
            lines.append("No offset data provided for analysis.")
            return "\n".join(lines)

        # 1. Structural Offsets Summary
        lines.append("--- 1. Matched Buffer Locations ---")
        v_offset_counts = defaultdict(list)
        i_offset_counts = defaultdict(list)

        for entry in offset_data:
            mesh_id = entry.get('csv_name', 'Unknown')
            xeck_id = entry.get('xeck_name', 'Unknown')

            lines.append(f"Mesh: {mesh_id} -> File: {xeck_id}")

            v_matches = entry.get('v_matches', [])
            i_matches = entry.get('i_matches', [])

            for v in v_matches:
                v_offset_counts[v['offset']].append((mesh_id, xeck_id))
                lines.append(f"  [Vertex Buffer] Offset: {v['hex']} | Stride: {v['stride']}b | Endian: {v['endian']}")

            for i in i_matches:
                i_offset_counts[i['offset']].append((mesh_id, xeck_id))
                lines.append(f"  [Index Buffer ] Offset: {i['hex']} | Count: {i['count']} | Endian: {i['endian']}")
            lines.append("")

        # 2. Shared Buffers & Common Header Tables
        lines.append("--- 2. Shared Offset & Header Pointer Isolation ---")
        lines.append(
            "Offsets appearing across multiple meshes indicate internal header tables, shared pools, or sub-mesh structures:")

        shared_v = {off: entries for off, entries in v_offset_counts.items() if len(entries) > 1}
        shared_i = {off: entries for off, entries in i_offset_counts.items() if len(entries) > 1}

        if shared_v:
            lines.append("\n  [Shared Vertex Offsets Detected]:")
            for off, entries in shared_v.items():
                labels = [f"{m} ({x})" for m, x in entries]
                lines.append(f"    - {hex(off)} shared across: {', '.join(labels)}")
        else:
            lines.append("  [+] No overlapping Vertex Buffer offsets detected.")

        if shared_i:
            lines.append("\n  [Shared Index Offsets Detected]:")
            for off, entries in shared_i.items():
                labels = [f"{m} ({x})" for m, x in entries]
                lines.append(f"    - {hex(off)} shared across: {', '.join(labels)}")
        else:
            lines.append("  [+] No overlapping Index Buffer offsets detected.")

        # 3. Structural Pointer Relationships (Relative Distances)
        lines.append("\n--- 3. Relative Memory Spacing & Index Patterns ---")
        lines.append("Distance between Vertex and Index buffers (used to locate section pointers in header):")

        rel_distances = []
        for entry in offset_data:
            for v in entry.get('v_matches', []):
                for i in entry.get('i_matches', []):
                    dist = i['offset'] - v['offset']
                    rel_distances.append(dist)
                    direction = "I-Buffer after V-Buffer" if dist > 0 else "V-Buffer after I-Buffer"
                    lines.append(f"  - {entry['csv_name']}: Distance = {hex(abs(dist))} ({dist} bytes, {direction})")

        # 4. Universal Key Extraction Guidance
        lines.append("\n--- 4. Universal Key Reverse-Engineering Guidance ---")
        lines.append("To build a direct XECK parser (without RenderDoc CSV cross-referencing):")
        lines.append(
            "  1. Search the file header (0x00 - 0x800) for uint32 4-byte integers matching these absolute offsets.")
        lines.append("  2. Search for relative offsets matching the distance between V-Buffer and I-Buffer.")
        lines.append(
            "  3. Check standard align/padding boundaries (e.g., 0x10, 0x80, or 0x800) preceding these offsets.")

        lines.append("\n" + "=" * 70 + "\n")
        return "\n".join(lines)

    def _save_results(self, content: str):
        self.output_dir.mkdir(parents=True, exist_ok=True)

        if not self.base_result.exists():
            # First execution
            self.base_result.write_text(content, encoding='utf-8')
        else:
            # Subsequent execution: Save new report as results-2.txt and build Master-results.txt
            self.secondary_result.write_text(content, encoding='utf-8')

            master_content = ""
            if not self.master_result.exists():
                master_content += "=================================================================\n"
                master_content += ">>> MASTER LOG INITIALIZED <<<\n"
                master_content += "=================================================================\n\n"

            master_content += f"--- LOG MERGE EVENT: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n\n"
            master_content += "--- PREVIOUS RESULTS (results.txt) ---\n"
            master_content += self.base_result.read_text(encoding='utf-8') + "\n\n"
            master_content += "--- NEW RESULTS (results-2.txt) ---\n"
            master_content += self.secondary_result.read_text(encoding='utf-8') + "\n\n"
            master_content += "-" * 70 + "\n\n"

            with open(self.master_result, 'a', encoding='utf-8') as master_file:
                master_file.write(master_content)
