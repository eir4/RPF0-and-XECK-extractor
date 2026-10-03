import struct
import csv
from pathlib import Path
import numpy as np

# Standard heuristic strides used in XECK buffers
STRIDES = (16, 20, 24, 28, 32, 36, 40, 44, 48)


def find_index_objects(raw, base):
    """Scan for index buffer object signatures in the file."""
    objs = []
    n = len(raw)
    a = np.frombuffer(raw[:n // 4 * 4], dtype='>u4')
    # candidate words == 2 at position i, count at i-1, data ptr at i+1
    for i in np.nonzero(a == 2)[0]:
        if i < 1 or i + 5 >= len(a): continue
        cnt, ptr, ptr2, ptr3, zero = int(a[i - 1]), int(a[i + 1]), int(a[i + 2]), int(a[i + 3]), int(a[i + 4])

        if not (6 <= cnt <= 200000) or ptr != ptr3 or zero != 0:
            continue

        off = ptr - base
        obj = (i - 1) * 4

        if off == obj + 0x40 and off + cnt * 2 <= n:
            objs.append((obj, off, cnt))

    return objs


def pos_ok(v):
    """Verify coordinate validity."""
    return np.isfinite(v).all() and np.abs(v).max() < 50


def locate_vertices(raw, obj_off, idx_off, cnt):
    """Walk backwards from the index object to locate vertex float data."""
    idx = np.frombuffer(raw, dtype='>u2', count=cnt, offset=idx_off)
    nv = int(idx.max()) + 1
    best = None

    for s in STRIDES:
        for gap in range(0, 0x41, 4):
            start = obj_off - gap - nv * s
            if start < 0: continue

            v = np.frombuffer(raw, dtype='>f4', count=nv * s // 4, offset=start).reshape(nv, s // 4)[:, :3]

            if pos_ok(v) and v.std(axis=0).min() > 1e-5:
                # smoothness = mean distance between consecutive vertices
                sm = float(np.linalg.norm(np.diff(v, axis=0), axis=1).mean())
                if best is None or sm < best[0]:
                    best = (sm, s, start, nv, gap)

    return best


def strip_to_list(idx):
    """Convert triangle strip to standard triangle list with parity."""
    tris = []
    for i in range(len(idx) - 2):
        a, b, c = int(idx[i]), int(idx[i + 1]), int(idx[i + 2])
        if a == b or b == c or a == c: continue
        tris.append((b, a, c) if i & 1 else (a, b, c))
    return tris


def pick_topology(v, idx):
    """Heuristically decide between List and Strip topology."""

    def mean_edge(tris):
        if not tris: return 1e9
        t = np.array(tris[:3000])
        p = v[t]
        return float(np.linalg.norm(p[:, 0] - p[:, 1], axis=1).mean())

    lst = [tuple(map(int, idx[i:i + 3])) for i in range(0, len(idx) - 2, 3)]
    lst = [t for t in lst if t[0] != t[1] != t[2] != t[0]]
    st = strip_to_list(idx)

    if mean_edge(lst) <= mean_edge(st):
        return ('list', lst)
    return ('strip', st)


def export_obj(path, v, tris):
    """Write geometry to a standard OBJ format."""
    with open(path, 'w') as f:
        for x, y, z in v:
            f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        for a, b, c in tris:
            f.write(f"f {a + 1} {b + 1} {c + 1}\n")


class XeckExtractorAutomator:
    """Master Orchestrator wrapped for GUI integration."""

    def __init__(self, xeck_path: str, *args, **kwargs):
        # *args and **kwargs safely absorb legacy parameters from the GUI
        self.xeck_path = Path(xeck_path)
        self.raw = self.xeck_path.read_bytes()
        self.log_callback = kwargs.get("log_callback", print)

    def log(self, message: str):
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def run_pipeline(self, output_dir: str):
        self.log(f"[*] Initializing Kaworu (Numpy Heuristic Scanner) for {self.xeck_path.name}...")

        # Unpack header directly as established by xeck_mesh_scan
        try:
            magic, ver, base, s1, s2 = struct.unpack_from('>4sIIII', self.raw, 0)
            self.log(f"[*] Detected Header Base Offset: 0x{base:08X}")
        except Exception as e:
            self.log(f"[!] Failed to parse header: {e}")
            return

        out_path = Path(output_dir)
        mesh_dir = out_path / "meshes"
        mesh_dir.mkdir(parents=True, exist_ok=True)

        objs = find_index_objects(self.raw, base)
        self.log(f"[+] Discovered {len(objs)} index objects.")

        rows = []
        extracted_count = 0

        for k, (obj, off, cnt) in enumerate(objs):
            loc = locate_vertices(self.raw, obj, off, cnt)
            if not loc:
                rows.append([k, hex(obj), hex(off), cnt, '', '', '', '', 'no vertex buffer found'])
                continue

            sm, s, start, nv, gap = loc

            v = np.frombuffer(self.raw, dtype='>f4', count=nv * s // 4, offset=start).reshape(nv, s // 4)[:, :3].astype(
                float)
            idx = np.frombuffer(self.raw, dtype='>u2', count=cnt, offset=off)

            topo, tris = pick_topology(v, idx)
            name = f"mesh_{k:03d}_idx{off:08x}.obj"

            export_obj(mesh_dir / name, v, tris)
            rows.append([k, hex(obj), hex(off), cnt, hex(start), s, nv, topo, name])

            self.log(f"    - Extracted #{k:03d} | ID: {hex(off)} | Vtx: {nv} | Topo: {topo}")
            extracted_count += 1

        csv_path = out_path / f"mesh_table_{self.xeck_path.stem}.csv"
        with open(csv_path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(
                ['n', 'index_obj', 'index_data', 'index_count', 'vb_start', 'stride', 'verts', 'topology', 'file'])
            w.writerows(rows)

        self.log(f"\n[+] Extraction complete! Wrote {extracted_count} meshes.")
        self.log(f"[+] Metadata map saved to {csv_path.name}")