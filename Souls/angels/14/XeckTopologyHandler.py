import struct
import numpy as np

class XeckTopologyHandler:
    """
    Handles Triangle Strips vs Lists, precise geometry record decoding, 
    UV texture coordinate extraction, and writing MTLLIB links for materials.
    """
    GROUP_TAG = 0x8200B5E4

    def record_for(self, raw, base, desc_off, nv, cnt):
        """Finds the geometry record sitting 0x18C or 0x19C before the descriptor."""
        for delta in (0x18C, 0x19C):
            r = desc_off - delta
            if r < 0: continue
            rn, rc, ptr, stride, _, pt, pc = struct.unpack_from('>HHIHHHH', raw, r)
            if rn == nv and rc == cnt and base <= ptr < base + len(raw) and pt in (4, 6) and pc in (cnt // 3, cnt - 2):
                return stride, pt
        return None

    def read_pos(self, raw, start, stride, nv):
        # Prevent zero-size array creation by explicitly checking nv > 0
        if nv == 0 or start + nv * stride > len(raw): return None

        v = np.frombuffer(raw, dtype='>f4', count=nv * stride // 4, offset=start).reshape(nv, stride // 4)[
            :, :3].astype(float)

        # Add a v.size > 0 check before running reduction operations like .max()
        return v if v.size > 0 and np.isfinite(v).all() and np.abs(v).max() < 100 else None

    def pick_stride(self, raw, start, rec_stride, nv):
        """Falls back on smoothness testing if the listed stride (e.g. 36 for 96-byte cloth) is deceptive."""
        def smooth(v): return float(np.linalg.norm(np.diff(v, axis=0), axis=1).mean())
        
        v = self.read_pos(raw, start, rec_stride, nv)
        if v is not None and smooth(v) < 0.05: 
            return rec_stride, v
            
        best = None
        for s in range(24, 132, 4):
            v = self.read_pos(raw, start, s, nv)
            if v is None: continue
            sm = smooth(v)
            if best is None or sm < best[0]: best = (sm, s, v)
        return (best[1], best[2]) if best else (rec_stride, None)

    def read_uv(self, raw, start, stride, nv):
        """Extracts the float32 pair handling the +24 / +48 offset based on stride."""
        o = 48 if stride >= 96 else 24
        if o + 8 > stride: return None
        b = np.frombuffer(raw, np.uint8, count=nv * stride, offset=start).reshape(nv, stride)
        uv = b[:, o:o + 8].copy().view('>f4').reshape(nv, 2).astype(float)
        if not np.isfinite(uv).all() or np.abs(uv).max() > 64: return None
        return uv

    def resolve_indices(self, idx, ptype):
        if ptype == 6:  # Triangle Strip
            t = []
            for i in range(len(idx) - 2):
                a, b, c = int(idx[i]), int(idx[i+1]), int(idx[i+2])
                if a == b or b == c or a == c: continue
                t.append((b, a, c) if i & 1 else (a, b, c))
            return t
        else:           # Triangle List
            return [tuple(int(x) for x in idx[i:i+3]) for i in range(0, len(idx) - 2, 3)]

    def link_material_to_mesh(self, raw, base, desc_off, mesh_idx):
        """Traces the mesh pointer group to resolve the bound material index."""
        a = np.frombuffer(raw[:len(raw) // 4 * 4], '>u4')
        groups = np.array(sorted(int(i) * 4 for i in np.nonzero(a == self.GROUP_TAG)[0]))
        
        cur = desc_off
        for hop in range(5):
            idx_matches = np.nonzero(a == base + cur)[0]
            if len(idx_matches) != 1: break
            s = int(idx_matches[0]) * 4
            j = np.searchsorted(groups, s, 'right') - 1
            if j >= 0:
                g = int(groups[j]); rel = s - g
                n = struct.unpack_from('>H', raw, g + 0x16)[0]
                p = struct.unpack_from('>I', raw, g + 0x0C)[0]
                first = 0x24 if p - base != g + 0x20 else 0x20 + ((2 * n + 3) // 4) * 4 + 4
                if first <= rel < 0x800 and (rel - first) % 0x28 == 0:
                    sub = (rel - first) // 0x28
                    if sub < n and base <= p < base + len(raw):
                        return struct.unpack_from('>H', raw, p - base + 2 * sub)[0]
                break
            cur = s
        return None

    def export_obj(self, path, v, tris, uv, material_name):
        """Writes OBJ geometry injected with UV map and MTLLIB reference."""
        with open(path, 'w') as f:
            f.write(f"mtllib ../materials.mtl\n")
            f.write(f"usemtl {material_name}\n")
            for x, y, z in v: 
                f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
            if uv is not None:
                for u, w in uv: 
                    f.write(f"vt {u:.6f} {1.0 - w:.6f}\n") # Flip V coordinate
                for a, b, c in tris: 
                    f.write(f"f {a+1}/{a+1} {b+1}/{b+1} {c+1}/{c+1}\n")
            else:
                for a, b, c in tris: 
                    f.write(f"f {a+1} {b+1} {c+1}\n")