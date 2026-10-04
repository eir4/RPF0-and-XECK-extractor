"""
xeck_materials.py - dump the material table embedded in a RAGE .xeck.

In these files materials are NOT separate .mtl files: each one is an embedded shader-preset record:
    <name>.sps   (shader preset)   ->  <...>/pong_xxx.fxc  (shader)  ->  entity_<...>_NNN.sva  (instance)
    followed by texture slots  (DiffuseTex, SpecularTex, DiffuseDetailMap, SweatMapTex, NoiseTex, ...) each with a .dds name
and then the float parameter names (no values decoded yet).  Records appear back to back in one block; their order
is the material index (the file also contains a pointer array to them).
Usage: python xeck_materials.py char_usa.xeck [out_dir]
"""
import re, sys, csv, json, struct
from pathlib import Path

TOKEN = re.compile(rb'[ -~]{4,}')

def clean(s, anchors):
    for a in anchors:                       # a length byte sometimes precedes the string and looks printable
        i = s.find(a)
        if i > 0 and s[i-1:i].isalnum() is not None: return s[i:]
    return s

def parse(raw):
    mats, cur, slot, last = [], None, None, None
    for m in TOKEN.finditer(raw):
        s = m.group().decode('ascii')
        if s.endswith('.sps') and 'character/' in s or s.endswith('.sps') and '/' in s:
            cur = dict(offset=m.start(), sps=clean(s, ('character/', 'pong_', 'effects/')), shader='', entity='', slots={}, params=[])
            mats.append(cur); slot = None
        elif cur is None: continue
        elif s.endswith('.fxc'): cur['shader'] = s.split('/')[-1]
        elif s.endswith('.sva'): cur['entity'] = clean(s, ('entity_',))
        elif s.endswith('.dds'):
            name = s
            if not name.startswith(('char', 'dummy', 'lowr', 'hair', 'detail', 'noise')):
                for a in ('char_', 'dummy', 'lowr', 'hair_', 'detail', 'noise'):
                    i = s.find(a)
                    if 0 < i < 3: name = s[i:]; break
            if slot: cur['slots'][slot] = name; last = slot; slot = None
            elif last and last + '.2nd' not in cur['slots']: cur['slots'][last + '.2nd'] = name   # unnamed second map bound to the slot (normal map)
        elif re.fullmatch(r'[A-Z][A-Za-z]*(Tex|Map|Map\d*)', s): slot = s
        elif re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,40}', s) and slot is None and cur['entity']:
            cur['params'].append(s)
        # a slot name that is directly followed by another slot name has no texture bound
        if not s.endswith('.dds') and slot and re.fullmatch(r'[A-Z][A-Za-z]*(Tex|Map|Map\d*)', s) and cur['slots'] is not None:
            cur['slots'].setdefault(s, '')
    # drop records whose .sps is outside the material block (stray matches)
    return [m for m in mats if m['entity']]

def run(path, out_dir):
    raw = Path(path).read_bytes(); out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    mats = parse(raw)
    for i, m in enumerate(mats): m['index'] = i
    (out / 'materials.json').write_text(json.dumps(mats, indent=1))
    with open(out / 'materials.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['index', 'offset', 'preset', 'shader', 'entity', 'textures'])
        for m in mats: w.writerow([m['index'], hex(m['offset']), m['sps'], m['shader'], m['entity'], '; '.join(f"{k}={v}" for k, v in m['slots'].items() if v)])
    print(f"{len(mats)} materials -> {out}")

if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'char_usa.xeck', sys.argv[2] if len(sys.argv) > 2 else './xeck_materials_out')
