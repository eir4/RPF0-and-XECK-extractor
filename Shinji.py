import os

class XeckObjExtractor:
    """
    Child Module 2: Handles the extraction and formatting of geometry data 
    into standard Wavefront OBJ files. Supports primitive topology conversion 
    (Triangle Strips to Triangle Lists).
    """

    @staticmethod
    def process_triangle_strip(indices: list) -> list:
        """
        Converts triangle strip indices into a standard triangle list format,
        preserving winding order and culling degenerate triangles.
        """
        triangle_list = []
        for i in range(len(indices) - 2):
            # Skip degenerate triangles (points collapsing into a line or dot)
            if indices[i] == indices[i + 1] or indices[i + 1] == indices[i + 2] or indices[i] == indices[i + 2]:
                continue

            # Alternate the winding order for every other triangle to prevent inside-out rendering
            if i % 2 == 0:
                triangle_list.extend([indices[i], indices[i + 1], indices[i + 2]])
            else:
                triangle_list.extend([indices[i], indices[i + 2], indices[i + 1]])

        return triangle_list

    @staticmethod
    def export_obj(output_path: str, positions: list, indices: list, is_triangle_strip: bool = False):
        """
        Writes decompressed vertex and index data to an OBJ file.
        
        :param output_path: Destination file path for the .obj file.
        :param positions: List of (x, y, z) vertex tuples.
        :param indices: List of integer indices defining faces.
        :param is_triangle_strip: Set to True if the geometry uses triangle strips (common in dense meshes).
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("# Extracted via XECK Cross-Examination\n")
            
            # Write uncompressed vertex positions
            for x, y, z in positions:
                f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
            
            if not indices:
                return

            f.write("\n# Faces\n")
            
            # Resolve topology
            export_indices = indices
            if is_triangle_strip:
                export_indices = XeckObjExtractor.process_triangle_strip(indices)

            # Write faces (OBJ format requires 1-based indexing)
            for i in range(0, len(export_indices) - 2, 3):
                idx1 = export_indices[i] + 1
                idx2 = export_indices[i + 1] + 1
                idx3 = export_indices[i + 2] + 1
                f.write(f"f {idx1} {idx2} {idx3}\n")