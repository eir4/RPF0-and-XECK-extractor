"""
xeck_mesh_scan.py  -  find and export every mesh in a RAGE .xeck WITHOUT RenderDoc.

Findings this relies on (all verified on char_usa.xeck):
  * header: 'csrr', 0x414, BASE (0xEE1D5000), size, size.  Pointers are  file_offset = ptr - BASE.
  * index object (big-endian):  u32 index_count | u32 2 (bytes/index) | ptr data | ptr | ptr data | 0
    with the uint16 BE index data starting 0x40 bytes after the object.
  * vertex buffer sits just before that object: float32 x,y,z at +0, stride 36 for the head mesh.
Usage:  python xeck_mesh_scan.py char_usa.xeck [out_dir]
"""
import struct, sys, csv
from pathlib import Path
import numpy as np

STRIDES = (16, 20, 24, 28, 32, 36, 40, 44, 48)

def find_index_objects(raw, base):
    objs = []
    n = len(raw)
    a = np.frombuffer(raw[:n // 4 * 4], dtype='>u4')
    # candidate words == 2 at position i, count at i-1, data ptr at i+1
    for i in np.nonzero(a == 2)[0]:
        if i < 1 or i + 5 >= len(a): continue
        cnt, ptr, ptr2, ptr3, zero = int(a[i-1]), int(a[i+1]), int(a[i+2]), int(a[i+3]), int(a[i+4])
        if not (6 <= cnt <= 200000) or ptr != ptr3 or zero != 0: continue
        off = ptr - base
        obj = (i - 1) * 4
        if off == obj + 0x40 and off + cnt * 2 <= n:
            objs.append((obj, off, cnt))
    return objs

def pos_ok(v):
    return np.isfinite(v).all() and np.abs(v).max() < 50

def locate_vertices(raw, obj_off, idx_off, cnt):
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
    tris = []
    for i in range(len(idx) - 2):
        a, b, c = int(idx[i]), int(idx[i+1]), int(idx[i+2])
        if a == b or b == c or a == c: continue
        tris.append((b, a, c) if i & 1 else (a, b, c))
    return tris

def pick_topology(v, idx):
    """list vs strip: whichever gives shorter average triangle edges"""
    def mean_edge(tris):
        if not tris: return 1e9
        t = np.array(tris[:3000]); p = v[t]
        return float(np.linalg.norm(p[:, 0] - p[:, 1], axis=1).mean())
    lst = [tuple(map(int, idx[i:i+3])) for i in range(0, len(idx) - 2, 3)]
    lst = [t for t in lst if t[0] != t[1] != t[2] != t[0]]
    st = strip_to_list(idx)
    return ('list', lst) if mean_edge(lst) <= mean_edge(st) else ('strip', st)

def export_obj(path, v, tris):
    with open(path, 'w') as f:
        for x, y, z in v: f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        for a, b, c in tris: f.write(f"f {a+1} {b+1} {c+1}\n")

def run(path, out_dir):
    raw = Path(path).read_bytes()
    magic, ver, base, s1, s2 = struct.unpack_from('>4sIIII', raw, 0)
    out = Path(out_dir); (out / 'meshes').mkdir(parents=True, exist_ok=True)
    objs = find_index_objects(raw, base)
    print(f"{len(objs)} index objects")
    rows = []
    for k, (obj, off, cnt) in enumerate(objs):
        loc = locate_vertices(raw, obj, off, cnt)
        if not loc: rows.append([k, hex(obj), hex(off), cnt, '', '', '', '', 'no vertex buffer found']); continue
        sm, s, start, nv, gap = loc
        v = np.frombuffer(raw, dtype='>f4', count=nv * s // 4, offset=start).reshape(nv, s // 4)[:, :3].astype(float)
        idx = np.frombuffer(raw, dtype='>u2', count=cnt, offset=off)
        topo, tris = pick_topology(v, idx)
        name = f"mesh_{k:03d}_idx{off:08x}.obj"
        export_obj(out / 'meshes' / name, v, tris)
        rows.append([k, hex(obj), hex(off), cnt, hex(start), s, nv, topo, name])
    with open(out / 'mesh_table.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['n', 'index_obj', 'index_data', 'index_count', 'vb_start', 'stride', 'verts', 'topology', 'file'])
        w.writerows(rows)
    print('wrote', out / 'mesh_table.csv')

if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'char_usa.xeck', sys.argv[2] if len(sys.argv) > 2 else './xeck_out')
