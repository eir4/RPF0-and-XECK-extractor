"""
xeck_ripper.py - one command: rip meshes (+UVs), textures (DDS/PNG) and the material table out of RAGE .xeck files
(Rockstar Table Tennis, Xbox 360).  Works on char_usa, char_usa05, char_sweden, char_brazil, char_china (tested).

    python xeck_ripper.py char_usa.xeck [out_dir]          # one file
    python xeck_ripper.py ./xecks/ [out_dir]                # every *.xeck in a folder

Output per file:   <out>/<name>/meshes/*.obj  mesh_table.csv  textures/*.dds *.png  texture_table.csv
                   materials.csv materials.json  summary.txt
Keep xeck_mesh_scan.py, xeck_textures.py and xeck_materials.py in the same folder as this script.
Also writes materials.mtl and adds mtllib/usemtl + material columns to every mesh.
NOT done yet: skeleton, normals, skinning weights, non-character (map) XECKs.
"""
import sys, time, traceback
from pathlib import Path
import xeck_mesh_scan, xeck_textures, xeck_materials, xeck_links

def rip(xeck, out_root):
    xeck = Path(xeck); out = Path(out_root) / xeck.stem; out.mkdir(parents=True, exist_ok=True)
    log = [f"file: {xeck.name} ({xeck.stat().st_size:,} bytes)"]
    for label, fn in (('meshes', lambda: xeck_mesh_scan.run(str(xeck), str(out))),
                            ('textures', lambda: xeck_textures.run(str(xeck), str(out / 'textures'))),
                            ('materials', lambda: xeck_materials.run(str(xeck), str(out))),
                            ('mesh-material links', lambda: xeck_links.link(str(xeck), str(out)))):
        t = time.time()
        try: fn(); log.append(f"{label}: ok ({time.time() - t:.1f}s)")
        except Exception as e:
            log.append(f"{label}: FAILED - {e!r}"); traceback.print_exc()
    import csv
    try:
        rows = list(csv.DictReader(open(out / 'mesh_table.csv')))
        bad = [r for r in rows if '.obj' not in r['file_or_error']]
        nouv = [r for r in rows if '(no uv)' in r['file_or_error']]
        log.append(f"mesh table: {len(rows)} meshes, {len(bad)} not exported, {len(nouv)} without UVs")
        for r in bad: log.append(f"   mesh {r['n']} @ {r['index_data']}: {r['file_or_error']}")
    except Exception: pass
    (out / 'summary.txt').write_text('\n'.join(log))
    print('\n'.join(log)); return out

if __name__ == '__main__':
    if len(sys.argv) < 2: sys.exit(__doc__)
    src = Path(sys.argv[1]); dst = sys.argv[2] if len(sys.argv) > 2 else './xeck_rip'
    for f in (sorted(src.glob('*.xeck')) if src.is_dir() else [src]): rip(f, dst)
