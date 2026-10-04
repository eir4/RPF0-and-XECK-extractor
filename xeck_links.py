"""
xeck_links.py - link every mesh to its material (and therefore to its textures), write materials.mtl and patch the OBJs.

How the link is stored (verified on char_usa against your RenderDoc draw/texture bindings):
  * "geometry group" objects start with the type tag 0x8200B5E4.  Offset +0x16 = number of meshes (n) in the group,
    +0x0C = pointer to a uint16[n] array of MATERIAL INDICES (index into the material table = order of xeck_materials output).
    (for bigger groups the array sits inline at +0x20).
  * each mesh in the group has a 0x28-byte sub-block; its pointer slot is referenced (through 1-2 pointer hops) from the mesh's
    vertex descriptor, which tells us which sub-block (= which array entry) the mesh is.
  * extra cloth copies (the 4 shirts / 4 skirts) are further vertex buffers of the same geometry -> same material as the original.
Usage: called by xeck_ripper.py;  or  python xeck_links.py <xeck> <rip_dir>
"""
import struct, sys, json, csv, re
from pathlib import Path
import numpy as np
import xeck_mesh_scan as X

GROUP_TAG = 0x8200B5E4

def mesh_material_indices(raw, base):
    objs, nvs, claimed = X.pair_meshes(raw, base)
    a = np.frombuffer(raw[:len(raw) // 4 * 4], '>u4')
    groups = np.array(sorted(int(i) * 4 for i in np.nonzero(a == GROUP_TAG)[0]))
    res = {}
    for k in range(len(objs)):
        if k not in claimed: continue
        cur = claimed[k][0]
        for hop in range(5):
            idx = np.nonzero(a == base + cur)[0]
            if len(idx) != 1: break
            s = int(idx[0]) * 4
            j = np.searchsorted(groups, s, 'right') - 1
            if j >= 0:
                g = int(groups[j]); rel = s - g
                n = struct.unpack_from('>H', raw, g + 0x16)[0]; p = struct.unpack_from('>I', raw, g + 0x0C)[0]
                first = 0x24
                if p - base == g + 0x20: first = 0x20 + ((2 * n + 3) // 4) * 4 + 4
                if first <= rel < 0x800 and (rel - first) % 0x28 == 0:
                    sub = (rel - first) // 0x28
                    if sub < n and base <= p < base + len(raw):
                        res[k] = struct.unpack_from('>H', raw, p - base + 2 * sub)[0]
                    break
            cur = s
    # extra cloth copies: same vertex/index counts as a resolved mesh -> inherit
    first_by_key = {}
    for k in sorted(res): first_by_key.setdefault((nvs[k], objs[k][2]), k)
    inherited = []
    for k in range(len(objs)):
        if k not in res:
            f = first_by_key.get((nvs[k], objs[k][2]))
            if f is not None and f in res: res[k] = res[f]; inherited.append(k)
    return res, inherited, len(objs)

def link(xeck_path, rip_dir):
    xeck_path = Path(xeck_path); rip = Path(rip_dir)
    raw = xeck_path.read_bytes(); base = struct.unpack_from('>I', raw, 8)[0]
    mat_idx, inherited, n = mesh_material_indices(raw, base)
    mats = json.loads((rip / 'materials.json').read_text())
    tex = {}
    for r in csv.DictReader(open(rip / 'textures' / 'texture_table.csv')):
        tex.setdefault(r['name'], r['png'] or r['dds'])
    def mname(i): return re.sub(r'\.sva$', '', mats[i]['entity']).replace('entity_', '') if 0 <= i < len(mats) else f'material_{i}'
    # materials.mtl
    with open(rip / 'materials.mtl', 'w') as f:
        for i, m in enumerate(mats):
            f.write(f"newmtl {mname(i)}\nKd 1 1 1\n")
            d = m['slots'].get('DiffuseTex') or m['slots'].get('NoiseTex')
            if d and d in tex: f.write(f"map_Kd textures/{tex[d]}\n")
            nm = m['slots'].get('DiffuseTex.2nd')
            if nm and nm in tex and 'normal' not in nm: f.write(f"map_Bump textures/{tex[nm]}\n")
            f.write("\n")
    # patch mesh table + OBJs
    rows = list(csv.DictReader(open(rip / 'mesh_table.csv')))
    for r in rows:
        k = int(r['n']); i = mat_idx.get(k)
        r['material_index'] = '' if i is None else i
        r['material'] = '' if i is None else mname(i)
        r['material_textures'] = '' if i is None else '; '.join(f"{s}={t}" for s, t in mats[i]['slots'].items() if t) if i < len(mats) else ''
        r['material_source'] = '' if i is None else ('inherited from original geometry' if k in inherited else 'read from file')
        fn = r['file_or_error'].split()[0]; p = rip / 'meshes' / fn
        if i is not None and p.exists():
            txt = p.read_text()
            txt = re.sub(r'^(mtllib|usemtl) .*\n', '', txt, flags=re.M)
            p.write_text(f"mtllib ../materials.mtl\nusemtl {mname(i)}\n" + txt)
    with open(rip / 'mesh_table.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    unresolved = [r['n'] for r in rows if r['material_index'] == '']
    print(f"materials linked for {len(rows) - len(unresolved)}/{len(rows)} meshes ({len(inherited)} inherited); unresolved: {unresolved}")
    return mat_idx

if __name__ == '__main__':
    link(sys.argv[1], sys.argv[2])
