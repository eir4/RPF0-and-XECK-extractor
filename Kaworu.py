import struct
import csv
import bisect
from pathlib import Path
import numpy as np

from XeckTopologyHandler import XeckTopologyHandler
from XeckTOCScanner import XeckMaterialScanner
from Misato import MisatoExtractor

class XeckExtractorAutomator:
    """Master Orchestrator wrapped for GUI integration. Handles full mesh, UV, and link mapping."""

    def __init__(self, xeck_path: str, log_callback=print):
        self.xeck_path = Path(xeck_path)
        self.raw = self.xeck_path.read_bytes()
        self.log = log_callback
        self.base = struct.unpack_from('>I', self.raw, 8)[0]
        self.topo_handler = XeckTopologyHandler()
        self.material_scanner = XeckMaterialScanner(self.raw)

    def find_index_objects(self):
        a = np.frombuffer(self.raw[:len(self.raw) // 4 * 4], dtype='>u4')
        objs = []
        for i in np.nonzero(a == 2)[0]:
            if i < 1 or i + 5 >= len(a): continue
            cnt, ptr, ptr3, zero = int(a[i-1]), int(a[i+1]), int(a[i+3]), int(a[i+4])
            if 6 <= cnt <= 200000 and ptr == ptr3 and zero == 0:
                off = ptr - self.base
                obj = (i - 1) * 4
                if off == obj + 0x40 and off + cnt * 2 <= len(self.raw):
                    objs.append((obj, off, cnt))
        return sorted(objs)

    def pair_meshes(self, objs):
        starts = [o[0] for o in objs]
        nvs = [int(np.frombuffer(self.raw, '>u2', count=c, offset=f).max()) + 1 for o, f, c in objs]
        a = np.frombuffer(self.raw[:len(self.raw) // 4 * 4], '>u4')
        descs = []
        for i in np.nonzero(a[1:-5] == 0)[0] + 1:
            nv, A, C = int(a[i-1]), int(a[i+1]), int(a[i+3])
            if 3 <= nv <= 65535 and self.base <= A < self.base + len(self.raw) and C == A + 0x20:
                descs.append(((i - 1) * 4, nv, A - self.base))
        
        descs.sort()
        claimed = {}
        for d, nv, A in descs:
            j = bisect.bisect_right(starts, d)
            for k in range(j, min(j + 4, len(objs))):
                if k not in claimed and nvs[k] == nv:
                    claimed[k] = (d, A)
                    break
        return nvs, claimed

    def run_pipeline(self, output_dir: str):
        self.log(f"[*] Initializing mesh scanning for {self.xeck_path.name}...")
        out = Path(output_dir) / self.xeck_path.stem
        mesh_dir = out / "meshes"
        mesh_dir.mkdir(parents=True, exist_ok=True)

        # 1. Trigger Misato to extract physical .dds/.png textures
        self.log("[*] Extracting textures via Misato...")
        try:
            misato = MisatoExtractor(xeck_path=str(self.xeck_path), log_callback=self.log)
            misato.run_pipeline(str(out))
        except Exception as e:
            self.log(f"[!] Texture extraction failed: {e}")

        # 2. Load the texture table to map filenames for the .mtl
        tex = {}
        tex_csv = out / 'texture_table.csv'
        if tex_csv.exists():
            for r in csv.DictReader(open(tex_csv)):
                tex[r['name']] = r.get('png') or r.get('dds')

        objs = self.find_index_objects()
        nvs, claimed = self.pair_meshes(objs)

        # 3. Pull Materials and write JSON/CSV
        mats = self.material_scanner.parse_materials()
        self.material_scanner.export_materials(out, mats)
        self.log(f"[+] Exported {len(mats)} embedded materials.")

        # 4. Generate the physical materials.mtl file to link textures
        with open(out / 'materials.mtl', 'w') as f:
            for i, m in enumerate(mats):
                mat_name = m['entity'].replace('entity_', '').replace('.sva', '') if m['entity'] else f'material_{i}'
                f.write(f"newmtl {mat_name}\nKd 1 1 1\n")

                d = m['slots'].get('DiffuseTex') or m['slots'].get('NoiseTex')
                if d and d in tex:
                    f.write(f"map_Kd {tex[d]}\n")

                nm = m['slots'].get('DiffuseTex.2nd')
                if nm and nm in tex and 'normal' not in nm:
                    f.write(f"map_Bump {tex[nm]}\n")
                f.write("\n")

        # 5. Extract Meshes
        rows = []
        for k, (obj, off, cnt) in enumerate(objs):
            nv = nvs[k]
            idx = np.frombuffer(self.raw, dtype='>u2', count=cnt, offset=off)

            if k not in claimed:
                rows.append([k, hex(off), cnt, nv, '', '', '', 'no vertex descriptor paired'])
                continue

            d, A = claimed[k]
            vb = A + 0x40

            rstride, ptype = self.topo_handler.record_for(self.raw, self.base, d, nv, cnt) or (0, 0)
            stride, v = self.topo_handler.pick_stride(self.raw, vb, rstride, nv)

            if v is None:
                rows.append([k, hex(off), cnt, nv, hex(vb), stride, '', 'positions not decodable'])
                continue

            tris = self.topo_handler.resolve_indices(idx, ptype)
            uv = self.topo_handler.read_uv(self.raw, vb, stride, nv)

            mat_idx = self.topo_handler.link_material_to_mesh(self.raw, self.base, d, k)
            mat_name = mats[mat_idx]['entity'].replace('entity_', '').replace('.sva',
                                                                              '') if mat_idx is not None and mat_idx < len(
                mats) else f'material_{k}'

            name = f"mesh_{k:03d}_{'strip' if ptype == 6 else 'list'}.obj"
            self.topo_handler.export_obj(mesh_dir / name, v, tris, uv, mat_name)

            rows.append([k, hex(off), cnt, nv, hex(vb), stride, 'strip' if ptype == 6 else 'list', name])

        with open(out / 'mesh_table.csv', 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['n', 'index_data', 'index_count', 'verts', 'vb_start', 'stride', 'topology', 'file'])
            w.writerows(rows)

        self.log(f"[+] Mesh scanning complete for {self.xeck_path.name}")


        with open(out / 'mesh_table.csv', 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['n', 'index_data', 'index_count', 'verts', 'vb_start', 'stride', 'topology', 'file'])
            w.writerows(rows)

        self.log(f"[+] Mesh scanning complete for {self.xeck_path.name}")
