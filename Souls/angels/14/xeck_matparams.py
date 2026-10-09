"""
xeck_matparams.py - read the numeric shader parameters (floats / vectors) of every material in a RAGE .xeck.

Layout found in the material blocks (big-endian), per parameter, three consecutive 16-byte slots:
    [value slot]  float32 x4 (a float uses only the first, the rest is 0xCDCDCDCD padding)
    [header]      u32 ptr to next block | u32 TYPE (2 = float, 5 = Vector4) | u32 ptr to the following value slot | u32 flags
    [name]        0x10 bytes (or more) holding the C string - the header's first word points at it
i.e. the value sits right BEFORE its header, and the name right after it.  The numbers match the .sps preset files you extracted
(e.g. char_usa_hair1.sps: noiseScale 0.72, diffuseColor 0.32 0.199 0 0.113, specExp1 52 ...).
Usage: called by xeck_ripper.py;  or  python xeck_matparams.py <xeck> <rip_dir>   (adds "params" to materials.json, writes material_params.csv)
"""
import struct, sys, json, csv, re
from pathlib import Path

NAME = re.compile(rb'[A-Za-z][A-Za-z0-9_]{2,40}\x00')

def read_params(raw, base, start, end):
    out = {}
    for m in NAME.finditer(raw, start, end):
        a = m.start()
        if a < 0x30 or a % 16: continue
        hdr = a - 0x10
        p1, typ, p2, fl = struct.unpack_from('>4I', raw, hdr)
        if p1 != base + a or typ not in (2, 5): continue
        n = 4 if typ == 5 else 1
        vals = struct.unpack_from('>%df' % n, raw, hdr - 0x10)
        name = m.group()[:-1].decode()
        out[name] = [round(v, 6) for v in vals] if n > 1 else round(vals[0], 6)
    return out

def run(xeck_path, rip_dir):
    raw = Path(xeck_path).read_bytes(); base = struct.unpack_from('>I', raw, 8)[0]
    rip = Path(rip_dir); mats = json.loads((rip / 'materials.json').read_text())
    offs = [m['offset'] for m in mats] + [None]
    for i, m in enumerate(mats):
        end = offs[i + 1] if offs[i + 1] and offs[i + 1] > m['offset'] else m['offset'] + 0x1000
        m['params'] = read_params(raw, base, max(0, m['offset'] - 0x80), min(end, m['offset'] + 0x2000))
    (rip / 'materials.json').write_text(json.dumps(mats, indent=1))
    with open(rip / 'material_params.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['index', 'entity', 'shader', 'parameter', 'value'])
        for i, m in enumerate(mats):
            for k, v in m['params'].items(): w.writerow([i, m['entity'], m['shader'], k, v])
    print(f"parameters for {len(mats)} materials ({sum(len(m['params']) for m in mats)} values)")
    return mats

if __name__ == '__main__':
    run(sys.argv[1], sys.argv[2])
