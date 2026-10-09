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
    # every group object: +0x04 ptr -> array of 0x28-byte sub-blocks, +0x0C ptr -> uint16 material indices, +0x16 = count
    slots = {}
    for g in (int(i) * 4 for i in np.nonzero(a == GROUP_TAG)[0]):
        sub, p = struct.unpack_from('>I', raw, g + 4)[0], struct.unpack_from('>I', raw, g + 0x0C)[0]
        n = struct.unpack_from('>H', raw, g + 0x16)[0]
        if not (base <= sub < base + len(raw) and base <= p < base + len(raw) and 0 < n < 512): continue
        for k in range(n): slots[sub - base + k * 0x28] = (p - base + 2 * k)
    res = {}
    for k in range(len(objs)):
        if k not in claimed: continue
        cur = claimed[k][0]
        for hop in range(6):
            idx = np.nonzero(a == base + cur)[0]
            if len(idx) != 1: break
            s_ = int(idx[0]) * 4
            if s_ in slots: res[k] = struct.unpack_from('>H', raw, slots[s_])[0]; break
            cur = s_
    # extra cloth copies: same vertex/index counts as a resolved mesh -> inherit
    first_by_key = {}
    for k in sorted(res): first_by_key.setdefault((nvs[k], objs[k][2]), k)
    inherited = []
    for k in range(len(objs)):
        if k not in res:
            f = first_by_key.get((nvs[k], objs[k][2]))
            if f is not None and f in res: res[k] = res[f]; inherited.append(k)
    return res, inherited, len(objs)

# Textures the file itself cannot supply (placeholders).  Supplied by you after comparing with the game; edit freely, or drop a
# texture_overrides.json ({"entity_name": "texture.dds"}) next to the xeck.
USER_OVERRIDES = {
    'char_sweden': {'entity_char_sweden_fins_003.sva': 'char_sweden_hair_fins3.dds',
                    'entity_char_sweden_fins_004.sva': 'char_sweden_hair_fins4.dds'},
}

def material_bindings(rip, stem, xeck_dir=None):
    """per material index -> dict(diffuse=(png,name), normal=(png,name), note=str).  Uses the exact pointer-based slot records."""
    mats = json.loads((Path(rip) / 'materials.json').read_text())
    rows = list(csv.DictReader(open(Path(rip) / 'textures' / 'texture_table.csv')))
    by_rec = {r['record']: r for r in rows}; by_name = {r['name']: r for r in rows}
    ov = dict(USER_OVERRIDES.get(stem, {}))
    if xeck_dir and (Path(xeck_dir) / 'texture_overrides.json').exists(): ov.update(json.loads((Path(xeck_dir) / 'texture_overrides.json').read_text()))
    out = []
    first_ok = {}
    for m in mats:
        sr = m.get('slot_records') or []
        d = next((s for s in sr if s['slot'] == 'DiffuseTex'), sr[0] if sr else None)
        n = next((s for s in sr if s['slot'] is None), None)
        drow = by_rec.get(d['record']) if d else None
        if drow and not drow['placeholder']: first_ok.setdefault(m['shader'], drow)
        out.append(dict(drow=drow, nrow=by_rec.get(n['record']) if n else None, note=''))
    for m, b in zip(mats, out):
        if m['entity'] in ov and ov[m['entity']] in by_name:
            b['note'] = f"texture set by override ({ov[m['entity']]})"; b['drow'] = by_name[ov[m['entity']]]
        elif b['drow'] and b['drow']['placeholder']:
            sub = first_ok.get(m['shader']); b['note'] = f"placeholder texture in file ({b['drow']['name']})" + (f"; substituted {sub['name']}" if sub else '')
            if sub: b['drow'] = sub
    return mats, out

def link(xeck_path, rip_dir):
    xeck_path = Path(xeck_path); rip = Path(rip_dir)
    raw = xeck_path.read_bytes(); base = struct.unpack_from('>I', raw, 8)[0]
    mat_idx, inherited, n = mesh_material_indices(raw, base)
    mats, binds = material_bindings(rip, xeck_path.stem, xeck_path.parent)
    def mname(i): return re.sub(r'\.sva$', '', mats[i]['entity']).replace('entity_', '') if 0 <= i < len(mats) else f'material_{i}'
    # materials.mtl
    with open(rip / 'materials.mtl', 'w') as f:
        for i, m in enumerate(mats):
            f.write(f"newmtl {mname(i)}\nKd 1 1 1\n")
            b = binds[i]
            if b['drow']: f.write(f"map_Kd textures/{b['drow']['png'] or b['drow']['dds']}\n")
            if b['nrow']: f.write(f"map_Bump textures/{b['nrow']['png'] or b['nrow']['dds']}\n")
            f.write("\n")
    # patch mesh table + OBJs
    rows = list(csv.DictReader(open(rip / 'mesh_table.csv')))
    for r_ in rows:
        r_['material_index'] = '' if mat_idx.get(int(r_['n'])) is None else mat_idx[int(r_['n'])]
    donors = X.find_uv_donors(raw, rows)      # LOD copies (USA mesh 56) take the UVs of the full-detail mesh with the same material
    for r in rows:
        k = int(r['n']); i = mat_idx.get(k)
        r['material_index'] = '' if i is None else i
        r['material'] = '' if i is None else mname(i)
        r['material_textures'] = '' if i is None or i >= len(mats) else '; '.join(f"{(s['slot'] or 'Unnamed(normal?)')}={s['name']}" for s in mats[i].get('slot_records', []))
        r['material_note'] = '' if i is None or i >= len(binds) else binds[i]['note']
        r['material_source'] = '' if i is None else ('inherited from original geometry' if k in inherited else 'read from file')
        fn = r['file_or_error'].split()[0]; p = rip / 'meshes' / fn
        if i is not None and p.exists():
            txt = p.read_text()
            if int(r['n']) in donors:
                dn, di = donors[int(r['n'])]; drow = next(x for x in rows if int(x['n']) == dn)
                _, du0, du1 = X.mesh_arrays(raw, drow); b_, _o = X.choose_base_uv(du0, du1, mats[i]['shader'] if i < len(mats) else '')
                lines = [ln for ln in txt.split('\n') if not ln.startswith('vt ')]
                at = next(j for j, ln in enumerate(lines) if ln.startswith('f '))
                lines[at:at] = [f"vt {u:.6f} {1.0 - v:.6f}" for u, v in b_[di]]
                txt = '\n'.join(lines); r['note'] = (r.get('note', '') + ' uv from mesh %d (LOD copy)' % dn).strip()
            elif r.get('uv1_offset'):
                nv_, vb_, st_ = int(r['verts']), int(r['vb_start'], 16), int(r['stride'])
                buf = np.frombuffer(raw, np.uint8, count=nv_ * st_, offset=vb_).reshape(nv_, st_)
                o0, o1 = int(r['uv0_offset']), int(r['uv1_offset'])
                u0 = buf[:, o0:o0 + 8].copy().view('>f4').reshape(nv_, 2).astype(float); u1 = buf[:, o1:o1 + 8].copy().view('>f4').reshape(nv_, 2).astype(float)
                if np.isfinite(u0).all() and np.isfinite(u1).all():
                    base_uv, _ = X.choose_base_uv(u0, u1, mats[i]['shader'] if i < len(mats) else '')
                    if base_uv is u1:        # uv0 is a tiled lookup set: write the layout set instead
                        lines = [ln for ln in txt.split('\n') if not ln.startswith('vt ')]
                        at = next(j for j, ln in enumerate(lines) if ln.startswith('f '))
                        lines[at:at] = [f"vt {u:.6f} {1.0 - v:.6f}" for u, v in u1]
                        txt = '\n'.join(lines)
            txt = re.sub(r'^(mtllib|usemtl) .*\n', '', txt, flags=re.M)
            p.write_text(f"mtllib ../materials.mtl\nusemtl {mname(i)}\n" + txt)
    with open(rip / 'mesh_table.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    unresolved = [r['n'] for r in rows if r['material_index'] == '']
    print(f"materials linked for {len(rows) - len(unresolved)}/{len(rows)} meshes ({len(inherited)} inherited); unresolved: {unresolved}")
    return mat_idx

if __name__ == '__main__':
    link(sys.argv[1], sys.argv[2])
