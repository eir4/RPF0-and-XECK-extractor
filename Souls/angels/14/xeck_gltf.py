"""
xeck_gltf.py - build ONE .glb per character: all meshes + skeleton + skin weights + both UV sets + materials/textures.
Blender: File > Import > glTF 2.0.   (glTF is Y-up like the game files; Blender converts on import.)

Rules used (checked against your RenderDoc data where noted):
  * skinned meshes (36/44-byte vertices): bytes +12..15 = 4 weights (sum 255), +16..19 = 4 bone indices = skeleton bone numbers
    (palette is identity).  Check: eyes -> Facial_root, lower legs -> knee, shoes -> ankle, ponytail -> ptail02/head.
  * UV0 = float32 pair at +24/+28 (+48/+52 for 96-byte cloth vertices)  [verified vs TEXCOORD0]
    UV1 = float32 pair at +32/+36 on 44-byte vertices.  Hair shaders (long_hair*.fxc) use UV1 for DiffuseTex (strand/scalp layout,
    visually verified), UV0 is a tiled noise-lookup coordinate.
  * glTF/D3D both have UV origin top-left, so UVs are written unchanged (the OBJ exporter flips V, this one does not).
Not included: normals (Blender recalculates), normal/spec/sweat maps, noise-shell alpha, cloth-sim data of 96-byte meshes
(those are exported static), blend shapes, animations.
"""
import json, struct, sys, csv, re
from pathlib import Path
import numpy as np
import xeck_mesh_scan as X

ALPHA_SHADERS = ('fins', 'long_hair', 'pong_lashes', 'pong_nodraw', 'pong_stubble', 'shells')   # materials whose diffuse alpha is coverage -> glTF alphaMode BLEND (Blender then wires alpha automatically)

def pad4(b, fill=b'\0'):
    return b + fill * ((4 - len(b) % 4) % 4)

class Buf:
    def __init__(self): self.data = bytearray(); self.views = []; self.acc = []
    def view(self, b, target=None):
        self.data += b'\0' * ((4 - len(self.data) % 4) % 4)
        v = {'buffer': 0, 'byteOffset': len(self.data), 'byteLength': len(b)}
        if target: v['target'] = target
        self.data += b; self.views.append(v); return len(self.views) - 1
    def accessor(self, arr, ctype, atype, target=None, minmax=False, normalized=False):
        vi = self.view(np.ascontiguousarray(arr).tobytes(), target)
        a = {'bufferView': vi, 'componentType': ctype, 'count': int(len(arr)), 'type': atype}
        if minmax: a['min'] = [float(x) for x in arr.min(0)]; a['max'] = [float(x) for x in arr.max(0)]
        if normalized: a['normalized'] = True
        self.acc.append(a); return len(self.acc) - 1

def s2l(c):
    c = np.asarray(c, float); return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def hex2lin(h):
    h = h.lstrip('#'); return [float(x) for x in s2l([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])]

# colours chosen by comparing Blender renders with the game (USA values supplied by the user): sRGB hex, multiplied with the diffuse map
CHAR_TINTS = {
    'char_usa': {'hair': '#CC9C73', 'fins': '#432A23', 'lashes': '#432A23'},
    'char_china': {'lashes': '#000000', 'stubble': '#D2B8BC'},
}
FIN_FACTOR = 0.41      # fins colour = average hair-texture colour x this (calibrated on USA: avg #937156 -> #432A23)

def role_of(shader):
    if shader.startswith('long_hair_shadow'): return None
    if shader.startswith('long_hair_fin') or shader.startswith('fins'): return 'fins'
    if shader.startswith(('long_hair', 'shells')): return 'hair'
    if shader.startswith('pong_lashes'): return 'lashes'
    if shader.startswith('pong_stubble'): return 'stubble'
    return None

def avg_hair_colour(rip, mats, binds):
    """alpha-weighted mean sRGB colour of the character's own hair shell textures"""
    from PIL import Image
    cols = []
    for m, b in zip(mats, binds):
        if role_of(m['shader']) == 'hair' and b['drow'] and b['drow']['png'].endswith('.png'):
            im = np.asarray(Image.open(Path(rip) / 'textures' / b['drow']['png']).convert('RGBA')).astype(float) / 255
            a = im[..., 3:4]
            if a.sum() > 0: cols.append((im[..., :3] * a).sum((0, 1)) / a.sum())
    return np.mean(cols, axis=0) if cols else None

def tint_for(m, stem, auto_hair, overrides):
    """linear baseColorFactor rgb for a hair-type material, or None"""
    role = role_of(m.get('shader', ''))
    if m['entity'] in overrides: return hex2lin(overrides[m['entity']])
    if role is None: return None
    for key, tab in CHAR_TINTS.items():
        if stem.startswith(key) and role in tab: return hex2lin(tab[role])
    p = m.get('params', {})
    if role == 'stubble':
        v = p.get('hairColor'); return [float(x) for x in s2l(v[:3])] if isinstance(v, list) else None
    if role in ('fins', 'lashes') and auto_hair is not None:
        return [float(x) for x in s2l(np.clip(auto_hair * FIN_FACTOR, 0, 1))]      # other characters: their own hair colour, darkened
    return None

def build(xeck_path, rip_dir, out_path, include_hidden=False):
    import xeck_skeleton
    xeck_path = Path(xeck_path); rip = Path(rip_dir)
    raw = xeck_path.read_bytes(); base = struct.unpack_from('>I', raw, 8)[0]
    bones = json.loads((rip / 'skeleton.json').read_text()) if (rip / 'skeleton.json').exists() else xeck_skeleton.read_skeleton(raw, base)
    mats = json.loads((rip / 'materials.json').read_text())
    import xeck_links
    _m, binds = xeck_links.material_bindings(rip, xeck_path.stem, xeck_path.parent)
    rows = list(csv.DictReader(open(rip / 'mesh_table.csv')))
    rowsT = list(csv.DictReader(open(rip / 'textures' / 'texture_table.csv')))
    auto_hair = avg_hair_colour(rip, mats, [b for b in binds])
    tint_over = json.loads((rip / 'material_tints.json').read_text()) if (rip / 'material_tints.json').exists() else {}
    if (xeck_path.parent / 'material_tints.json').exists(): tint_over.update(json.loads((xeck_path.parent / 'material_tints.json').read_text()))
    all_rows_for_donors = rows
    donors = X.find_uv_donors(xeck_path.read_bytes(), rows)
    arrays_cache = {}
    B = Buf(); nodes = []; images = []; textures = []; materials = []; meshes = []
    # skeleton nodes (0..N-1)
    kids = {}
    for b in bones: kids.setdefault(b['parent'], []).append(b['index'])
    for b in bones:
        n = {'name': b['name'], 'translation': b['local_t']}
        if b['index'] in kids: n['children'] = kids[b['index']]
        nodes.append(n)
    ibm = np.zeros((len(bones), 16), np.float32)
    for b in bones:
        m = np.eye(4, dtype=np.float32); m[:3, 3] = -np.array(b['model_pos'], np.float32); ibm[b['index']] = m.T.reshape(16)   # column-major
    ibm_acc = B.accessor(ibm, 5126, 'MAT4')
    skin = {'inverseBindMatrices': ibm_acc, 'joints': list(range(len(bones))), 'skeleton': 0}
    # materials
    img_idx = {}; mat_idx = {}
    def get_tex(row):
        if not row or not row['png'].endswith('.png'): return None
        name = row['name']
        if name not in img_idx:
            images.append({'bufferView': B.view((rip / 'textures' / row['png']).read_bytes()), 'mimeType': 'image/png', 'name': name})
            textures.append({'source': len(images) - 1, 'sampler': 0}); img_idx[name] = len(textures) - 1
        return img_idx[name]
    def get_mat(i, shader_hair=False):
        if i in mat_idx: return mat_idx[i]
        if i >= len(mats):
            g = {'name': f'material_{i}', 'pbrMetallicRoughness': {'metallicFactor': 0.0, 'roughnessFactor': 0.8},
                 'doubleSided': True}
            materials.append(g);
            mat_idx[i] = len(materials) - 1;
            return mat_idx[i]
        m = mats[i]; name = re.sub(r'\.sva$', '', m['entity']).replace('entity_', '')
        pbr = {'metallicFactor': 0.0, 'roughnessFactor': 0.8}
        t = get_tex(binds[i]['drow'])
        if t is not None: pbr['baseColorTexture'] = {'index': t, 'texCoord': 0}
        tint = tint_for(m, xeck_path.stem, auto_hair, tint_over)
        if tint: pbr['baseColorFactor'] = [*tint, 1.0]
        ex = {'shader': m['shader'], 'preset': m['sps'], 'role': role_of(m['shader']) or '', **{k: v for k, v in m.get('params', {}).items()}}
        for s_ in m.get('slot_records', []): ex['tex_' + (s_['slot'] or 'unnamed')] = s_['name'] or ''
        if binds[i]['drow']: ex['tex_diffuse_used'] = binds[i]['drow']['name']
        g = {'name': name, 'pbrMetallicRoughness': pbr, 'doubleSided': True, 'extras': ex}
        if role_of(m['shader']) == 'stubble':           # the stubble texture (tiled over the scalp) rides along as the occlusion map so Blender imports it; see xeck_blender_fix.py
            nrow = next((x for x in [r_ for r_ in rowsT if r_['name'] == ex.get('tex_NoiseTex')]), None)
            tt = get_tex(nrow)
            if tt is not None: g['occlusionTexture'] = {'index': tt, 'texCoord': 1}
        if any(m['shader'].startswith(s) for s in ALPHA_SHADERS): g['alphaMode'] = 'BLEND'
        if m['shader'].startswith('pong_nodraw'): pbr['baseColorFactor'] = [1, 1, 1, 0.0]
        materials.append(g); mat_idx[i] = len(materials) - 1; return mat_idx[i]

    skipped = [];
    hidden = []
    for r in rows:
        fn = r['file_or_error'].split()[0]
        # Skip if the mesh data is empty/invalid
        if not r.get('stride') or not r.get('vb_start') or not r.get('verts'):
            skipped.append(r['n'])
            continue
        if not r.get('material_index'): skipped.append(r['n']); continue

        mi = int(r['material_index'])
        if mi < len(mats):
            shader = mats[mi].get('shader', '')
            entity = mats[mi].get('entity', f'mat_{mi}')
            entity_name = entity.replace('entity_', '').replace('.sva', '') if entity else f'mat_{mi}'
        else:
            shader = ''
            entity_name = f'mat_{mi}'

        hair = shader.startswith('long_hair')
        if not include_hidden and shader.startswith(('pong_nodraw', 'long_hair_shadow')): hidden.append(
            r['n']); continue  # helper / shadow-only meshes (the invisible shapes around the head)
        nv, s, vb = int(r['verts']), int(r['stride']), int(r['vb_start'], 16)
        buf = np.frombuffer(raw, np.uint8, count=nv * s, offset=vb).reshape(nv, s)
        pos = buf[:, 0:12].copy().view('>f4').reshape(nv, 3).astype('<f4')
        off0 = int(r['uv0_offset']) if r.get('uv0_offset') else (48 if s >= 96 else 24)
        off1 = int(r['uv1_offset']) if r.get('uv1_offset') else None
        uv0 = buf[:, off0:off0 + 8].copy().view('>f4').reshape(nv, 2).astype('<f4')
        uv1 = buf[:, off1:off1 + 8].copy().view('>f4').reshape(nv, 2).astype('<f4') if off1 else None
        if not np.isfinite(uv0).all(): uv0 = np.zeros((nv, 2), '<f4')
        if uv1 is not None and not np.isfinite(uv1).all(): uv1 = None
        # indices
        k = int(r['n']);
        obj, off, cnt = next(o for o in X.find_index_objects(raw, base) if o[1] == int(r['index_data'], 16))
        idx = np.frombuffer(raw, '>u2', count=cnt, offset=off)
        tris = X.strip_to_list(idx) if r['topology'] == 'strip' else X.list_tris(idx)
        tri = np.array(tris, '<u4').reshape(-1, 3)
        attrs = {'POSITION': B.accessor(pos, 5126, 'VEC3', 34962, minmax=True)}
        if int(r['n']) in donors:  # LOD copy: take the UVs of the full-detail mesh with the same material
            dn, di = donors[int(r['n'])];
            drow = next(x for x in rows if int(x['n']) == dn)
            _, du0, du1 = X.mesh_arrays(raw, drow)
            uv0 = du0[di].astype('<f4');
            uv1 = du1[di].astype('<f4') if du1 is not None else None
        base_uv, other_uv = X.choose_base_uv(uv0, uv1, shader)         # TEXCOORD_0 is always the 0..1 layout map; materials always sample set 0
        attrs['TEXCOORD_0'] = B.accessor(base_uv.astype('<f4'), 5126, 'VEC2', 34962)
        if other_uv is not None: attrs['TEXCOORD_1'] = B.accessor(other_uv.astype('<f4'), 5126, 'VEC2', 34962)
        swapped = other_uv is not None and base_uv is uv1
        skinned = False
        t = list(raw[int(r['vertex_descriptor'], 16) + 0x20:int(r['vertex_descriptor'], 16) + 0x20 + 24])   # channel offset table: [1]=weights, [2]=bone indices
        wo, jo = t[1], t[2]
        wsz = jo - wo
        if wsz in (4, 16) and jo + 4 <= s:
            if wsz == 4: w = buf[:, wo:wo + 4].astype('<f4') / 255.0                                       # 36/44-byte vertices: 4 x uint8
            else: w = buf[:, wo:wo + 16].copy().view('>f4').reshape(nv, 4).astype('<f4')                    # 96-byte cloth vertices: 4 x float32
            j = buf[:, jo:jo + 4].astype('<u1')
            if (j < len(bones)).all() and np.allclose(w.sum(1), 1.0, atol=0.02) and np.isfinite(w).all():
                attrs['JOINTS_0'] = B.accessor(j, 5121, 'VEC4', 34962); attrs['WEIGHTS_0'] = B.accessor(w, 5126, 'VEC4', 34962); skinned = True
        # texCoord of hair material: material is shared, so key it by (material, hair flag)
        prim = {'attributes': attrs, 'indices': B.accessor(tri.reshape(-1), 5125, 'SCALAR', 34963), 'material': get_mat(mi), 'mode': 4}
        nm = f"mesh_{k:03d}_{entity_name}"
        meshes.append({'name': nm, 'primitives': [prim]})
        node = {'name': nm, 'mesh': len(meshes) - 1}
        if skinned: node['skin'] = 0
        nodes.append(node)
    mesh_nodes = [i for i, n in enumerate(nodes) if 'mesh' in n]
    gltf = {'asset': {'version': '2.0', 'generator': 'xeck_gltf.py'}, 'scene': 0, 'scenes': [{'nodes': [0] + mesh_nodes}],
            'nodes': nodes, 'meshes': meshes, 'skins': [skin], 'materials': materials, 'accessors': B.acc, 'bufferViews': B.views,
            'buffers': [{'byteLength': len(B.data)}]}
    if images: gltf['images'] = images; gltf['textures'] = textures; gltf['samplers'] = [{'magFilter': 9729, 'minFilter': 9987, 'wrapS': 10497, 'wrapT': 10497}]
    js = pad4(json.dumps(gltf, separators=(',', ':')).encode(), b' '); bn = pad4(bytes(B.data))
    Path(out_path).write_bytes(b'glTF' + struct.pack('<II', 2, 12 + 8 + len(js) + 8 + len(bn)) + struct.pack('<I4s', len(js), b'JSON') + js + struct.pack('<I4s', len(bn), b'BIN\0') + bn)
    print(f"{out_path}: {len(meshes)} meshes, {len(bones)} bones, {len(materials)} materials, {len(images)} textures, {len(B.data)/1e6:.1f} MB; skipped (no material): {skipped}; hidden helper meshes left out: {hidden}")

if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2], sys.argv[3])
