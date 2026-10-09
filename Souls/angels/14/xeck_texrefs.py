"""
xeck_texrefs.py - pointer-based material -> texture links (replaces string guessing).

Every texture slot of a material is an object tagged 0x8202CEDC (big-endian):
   +0x00 tag | +0x04 0x02000001 | +0x08 0 | +0x0C ptr -> file-name string | +0x10 ptr -> TEXTURE RECORD (tag 0x8202CC84) | +0x14 ptr (shared)
and the slot name ("DiffuseTex", "SpecularTex", ...) is the 16-byte block just before it.
The texture record contains the fetch constant (+0x50) the texture ripper uses, so slot -> record -> pixels is exact.
"""
import struct, re
import numpy as np

SLOT_TAG, TEX_TAG = 0x8202CEDC, 0x8202CC84

def all_refs(raw, base):
    """every texture-slot object in the file: list of dict(obj, slot, name, record)"""
    a = np.frombuffer(raw[:len(raw) // 4 * 4], '>u4'); out = []
    for i in np.nonzero(a == SLOT_TAG)[0]:
        o = int(i) * 4
        if o < 0x10 or o + 0x18 > len(raw): continue
        if struct.unpack_from('>I', raw, o + 4)[0] != 0x02000001: continue
        pn, pr = struct.unpack_from('>II', raw, o + 0x0C)[0], struct.unpack_from('>I', raw, o + 0x10)[0]
        rec = pr - base if base <= pr < base + len(raw) else None
        if rec is None or struct.unpack_from('>I', raw, rec)[0] != TEX_TAG: continue
        nm = None
        if base <= pn < base + len(raw):
            e = raw.find(b'\0', pn - base, pn - base + 80); s = raw[pn - base:e]
            nm = s.decode('ascii') if s and all(32 <= c < 127 for c in s) else None
        sb = raw[o - 0x10:o]; sl = sb.split(b'\0')[0]
        slot = sl.decode('ascii') if sl and re.fullmatch(rb'[A-Za-z][A-Za-z0-9_]*', sl) else None
        out.append(dict(obj=o, slot=slot, name=nm, record=rec))
    return out

def record_names(raw, base):
    """texture record offset -> file name, from the slot objects that reference it (works even if the record's own name field is odd)"""
    d = {}
    for r in all_refs(raw, base):
        if r['name']: d.setdefault(r['record'], r['name'])
    return d

def material_slots(raw, base, mat_offsets):
    """per material (by index): ordered list of (slot, name, record) for slot objects located inside that material block"""
    refs = sorted(all_refs(raw, base), key=lambda r: r['obj'])
    starts = list(mat_offsets); res = [[] for _ in starts]
    import bisect
    order = sorted(range(len(starts)), key=lambda i: starts[i]); sp = [starts[i] for i in order]
    for r in refs:
        j = bisect.bisect_right(sp, r['obj'] + 0x40) - 1       # the slot name block can sit slightly before the next record's recorded offset
        if j >= 0 and r['obj'] - starts[order[j]] < 0x3000: res[order[j]].append((r['slot'], r['name'], r['record']))
    return res
