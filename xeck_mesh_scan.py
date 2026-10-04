"""
xeck_mesh_scan.py (v2) - export every mesh from a RAGE .xeck (Table Tennis, Xbox 360) with no RenderDoc.

Verified structure (char_usa.xeck, big-endian):
  header   : 'csrr' | 0x414 | BASE | size | size        pointer -> file offset: ptr - BASE
  index obj: u32 count | u32 2 | ptr D | ptr | ptr D | 0   ; uint16 index data at D (= obj+0x40)
  geom rec : u16 nverts | u16 nindices | ptr palette | u16 stride | u16 183 | u16 primtype | u16 primcount
             primtype 6 = TRIANGLE STRIP (primcount = n-2), 4 = TRIANGLE LIST (primcount = n/3)
  vtx desc : 0x18C (v0x414) / 0x19C (v0x417) after the geom rec - searched, not hard-coded: u32 nverts | 0 | ptr A | ptr | ptr(A+0x20) ; vertex data = A + 0x40
  vertex   : float32 x,y,z first.  Strip meshes: stride from the record (36/44).
             List meshes (skirt, shirt): record says 36 but real stride is 96 (checked against your CSVs).
Usage: python xeck_mesh_scan.py char_usa.xeck [out_dir] [renderdoc_csv_dir]
"""
import struct, sys, csv, glob, os
from pathlib import Path
import numpy as np
import warnings; warnings.filterwarnings('ignore')

def find_index_objects(raw, base):
    a = np.frombuffer(raw[:len(raw) // 4 * 4], dtype='>u4'); objs = []
    for i in np.nonzero(a == 2)[0]:
        if i < 1 or i + 5 >= len(a): continue
        cnt, ptr, ptr3, zero = int(a[i-1]), int(a[i+1]), int(a[i+3]), int(a[i+4])
        if 6 <= cnt <= 200000 and ptr == ptr3 and zero == 0:
            off = ptr - base; obj = (i - 1) * 4
            if off == obj + 0x40 and off + cnt * 2 <= len(raw): objs.append((obj, off, cnt))
    return objs

def find_geom_record(raw, base, nv, cnt):
    pat = struct.pack('>HH', nv, cnt); p = 0
    while True:
        o = raw.find(pat, p)
        if o < 0: return None
        p = o + 1
        if o % 4: continue
        ptr, stride, _, ptype, pcount = struct.unpack_from('>IHHHH', raw, o + 4)
        if base <= ptr < base + len(raw) and ptype in (4, 6) and pcount in (cnt // 3, cnt - 2):
            return o, stride, ptype

def find_descriptor_near(raw, base, rec, nv, lo=0x100, hi=0x400):
    """vertex descriptor  u32 nv | 0 | ptr A | ptr | ptr C(=A+0x20)  after the geometry record.
    distance is +0x18C in version 0x414 files and +0x19C in 0x417 files, so search instead of hard-coding."""
    a = np.frombuffer(raw, dtype='>u4', count=hi // 4, offset=rec + lo)
    for i in np.nonzero(a == nv)[0]:
        o = rec + lo + int(i) * 4
        w = struct.unpack_from('>5I', raw, o)
        if w[1] == 0 and base <= w[2] < base + len(raw) and w[4] == w[2] + 0x20:
            return o, w[2] - base
    return None

def find_descriptors(raw, base, nv):
    """all vertex descriptors  u32 nv | 0 | ptr A ...  in file order -> vertex data offsets (A + 0x40)"""
    a = np.frombuffer(raw[:len(raw) // 4 * 4], dtype='>u4'); out = []
    for i in np.nonzero(a == nv)[0]:
        if i + 3 < len(a) and a[i+1] == 0 and base <= int(a[i+2]) < base + len(raw):
            out.append(int(a[i+2]) - base + 0x40)
    return out

def read_pos(raw, start, stride, nv):
    if start + nv * stride > len(raw): return None
    v = np.frombuffer(raw, dtype='>f4', count=nv * stride // 4, offset=start).reshape(nv, stride // 4)[:, :3].astype(float)
    return v if np.isfinite(v).all() and np.abs(v).max() < 100 else None

def smooth(v): return float(np.linalg.norm(np.diff(v, axis=0), axis=1).mean())

def pick_stride(raw, start, rec_stride, nv):
    v = read_pos(raw, start, rec_stride, nv)
    if v is not None and smooth(v) < 0.05: return rec_stride, v
    best = None
    for s in range(24, 132, 4):
        v = read_pos(raw, start, s, nv)
        if v is None: continue
        sm = smooth(v)
        if best is None or sm < best[0]: best = (sm, s, v)
    return (best[1], best[2]) if best else (rec_stride, None)

def read_uv(raw, start, stride, nv):
    """UV = float32 pair: +24/+28 for the 36/44-byte vertices, +48/+52 for the 96-byte cloth vertices
    (verified 100% against RenderDoc TEXCOORD0 for head, hands, torso, shirt).  Returns None if implausible."""
    o = 48 if stride >= 96 else 24
    if o + 8 > stride: return None
    b = np.frombuffer(raw, np.uint8, count=nv * stride, offset=start).reshape(nv, stride)
    uv = b[:, o:o + 8].copy().view('>f4').reshape(nv, 2).astype(float)
    if not np.isfinite(uv).all() or np.abs(uv).max() > 64: return None
    return uv

def strip_to_list(idx):
    t = []
    for i in range(len(idx) - 2):
        a, b, c = int(idx[i]), int(idx[i+1]), int(idx[i+2])
        if a == b or b == c or a == c: continue
        t.append((b, a, c) if i & 1 else (a, b, c))   # parity uses ORIGINAL position, even across degenerates
    return t

def list_tris(idx): return [tuple(int(x) for x in idx[i:i+3]) for i in range(0, len(idx) - 2, 3)]

def load_csv_names(csv_dir):
    names = {}
    for fn in glob.glob(os.path.join(csv_dir, '*.csv')):
        try:
            rows = list(csv.reader(open(fn)))
            if 'IDX' not in rows[0][1]: continue
            ids = [int(r[1]) for r in rows[1:]]
            sw = [((i & 255) << 8) | (i >> 8) for i in ids]
            names[(len(sw), max(sw) + 1)] = Path(fn).stem
        except Exception: pass
    return names

def pair_meshes(raw, base):
    """Pair every index object with its vertex descriptor.  Verified layout: for each mesh the file stores
    [geometry record][vertex descriptor] ... later [index object], in that order, so a descriptor belongs to the
    next index object (within 4) whose max index + 1 equals the descriptor's vertex count."""
    import bisect
    objs = sorted(find_index_objects(raw, base)); starts = [o[0] for o in objs]
    nvs = [int(np.frombuffer(raw, '>u2', count=c, offset=f).max()) + 1 for o, f, c in objs]
    a = np.frombuffer(raw[:len(raw) // 4 * 4], '>u4'); descs = []
    for i in np.nonzero(a[1:-5] == 0)[0] + 1:
        nv, A, C = int(a[i-1]), int(a[i+1]), int(a[i+3])
        if 3 <= nv <= 65535 and base <= A < base + len(raw) and C == A + 0x20: descs.append(((i - 1) * 4, nv, A - base))
    descs.sort(); claimed = {}
    for d, nv, A in descs:
        j = bisect.bisect_right(starts, d)
        for k in range(j, min(j + 4, len(objs))):
            if k not in claimed and nvs[k] == nv: claimed[k] = (d, A); break
    return objs, nvs, claimed

def record_for(raw, base, desc_off, nv, cnt):
    """geometry record sits 0x18C (v0x414) or 0x19C (v0x417) before the descriptor; None for extra copies"""
    for delta in (0x18C, 0x19C):
        r = desc_off - delta
        if r < 0: continue
        rn, rc, ptr, stride, _, pt, pc = struct.unpack_from('>HHIHHHH', raw, r)
        if rn == nv and rc == cnt and base <= ptr < base + len(raw) and pt in (4, 6) and pc in (cnt // 3, cnt - 2):
            return stride, pt
    return None

def run(path, out_dir, csv_dir=None):
    raw = Path(path).read_bytes(); base = struct.unpack_from('>I', raw, 8)[0]
    out = Path(out_dir); (out / 'meshes').mkdir(parents=True, exist_ok=True)
    known = load_csv_names(csv_dir) if csv_dir else {}
    objs, nvs, claimed = pair_meshes(raw, base)
    recs = {}                                        # (nv,cnt) -> (stride, ptype), inherited by extra copies
    for k, (obj, off, cnt) in enumerate(objs):
        if k in claimed:
            r = record_for(raw, base, claimed[k][0], nvs[k], cnt)
            if r: recs.setdefault((nvs[k], cnt), r)
    seen = {}; rows = []; groups = {}
    for k, (obj, off, cnt) in enumerate(objs):
        nv = nvs[k]; idx = np.frombuffer(raw, dtype='>u2', count=cnt, offset=off)
        if k not in claimed: rows.append([k, hex(off), cnt, nv, '', '', '', '', '', 'no vertex descriptor paired']); continue
        d, A = claimed[k]; vb = A + 0x40
        rs = recs.get((nv, cnt))
        if rs is None: rows.append([k, hex(off), cnt, nv, '', '', hex(vb), '', '', 'no geometry record (stride/topology unknown)']); continue
        rstride, ptype = rs
        stride, v = pick_stride(raw, vb, rstride, nv)
        if v is None: rows.append([k, hex(off), cnt, nv, '', rstride, hex(vb), '', '', 'positions not decodable']); continue
        tris = strip_to_list(idx) if ptype == 6 else list_tris(idx)
        n_used = seen.get((nv, cnt), 0); seen[(nv, cnt)] = n_used + 1
        label = known.get((cnt, nv), '')
        name = f"mesh_{k:03d}{'_' + label if label else ''}{'_copy%d' % (n_used + 1) if n_used else ''}_{'strip' if ptype == 6 else 'list'}.obj"
        uv = read_uv(raw, vb, stride, nv)
        with open(out / 'meshes' / name, 'w') as f:
            for x, y, z in v: f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
            if uv is not None:
                for u, w in uv: f.write(f"vt {u:.6f} {1.0 - w:.6f}\n")          # D3D v -> OBJ v (flip); values outside 0..1 wrap
                for a, b, c in tris: f.write(f"f {a+1}/{a+1} {b+1}/{b+1} {c+1}/{c+1}\n")
            else:
                for a, b, c in tris: f.write(f"f {a+1} {b+1} {c+1}\n")
        if stride >= 96: groups.setdefault((nv, cnt), []).append((len(rows), v))   # cloth only; other equal-count meshes are usually left/right pairs
        rows.append([k, hex(off), cnt, nv, hex(d), stride, hex(vb), 'strip' if ptype == 6 else 'list', label, name + ('' if uv is not None else '  (no uv)')])
    notes = {}
    for key, lst in groups.items():
        if len(lst) < 2: continue
        ref = lst[0][1]
        for n_i, (ri, v) in enumerate(lst):
            dmax = float(np.abs(v - ref).max())
            notes[ri] = (f"copy {n_i + 1} of {len(lst)}; " + ("reference copy" if n_i == 0 else
                         "identical to copy 1" if dmax < 1e-4 else f"DIFFERENT POSE: up to {dmax * 100:.1f} cm from copy 1"))
    with open(out / 'mesh_table.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['n', 'index_data', 'index_count', 'verts', 'vertex_descriptor', 'stride', 'vb_start', 'topology', 'renderdoc_name', 'file_or_error', 'note'])
        for i, r in enumerate(rows): w.writerow(r + [notes.get(i, '')] if len(r) == 10 else r)
    ok = sum(1 for r in rows if '.obj' in str(r[-1]))
    print(f"{len(rows)} index objects, {ok} meshes exported -> {out}")

if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'char_usa.xeck', sys.argv[2] if len(sys.argv) > 2 else './xeck_out', sys.argv[3] if len(sys.argv) > 3 else None)
