import contextlib
import io
import traceback
from pathlib import Path

import xeck_mesh_scan, xeck_textures, xeck_materials, xeck_matparams, xeck_links, xeck_skeleton, xeck_gltf

class _LogWriter(io.TextIOBase):
    def __init__(self, cb): self.cb = cb; self.buf = ''
    def write(self, s):
        self.buf += s
        while '\n' in self.buf:
            line, self.buf = self.buf.split('\n', 1)
            if line.strip(): self.cb('    ' + line)
        return len(s)

class AngelsGltfPipeline:
    """Strict glTF construction pipeline."""

    def __init__(self, xeck_path: str, log_callback=print):
        self.xeck_path = Path(xeck_path)
        self.log = log_callback or print

    def run_pipeline(self, output_dir: str, include_hidden_meshes: bool = False):
        xeck = self.xeck_path
        out = Path(output_dir) / xeck.stem
        out.mkdir(parents=True, exist_ok=True)
        self.log(f"[*] Angels: ripping {xeck.name} -> {out}")
        
        steps = [
            ('meshes + UVs', lambda: xeck_mesh_scan.run(str(xeck), str(out))),
            ('textures', lambda: xeck_textures.run(str(xeck), str(out / 'textures'))),
            ('materials', lambda: xeck_materials.run(str(xeck), str(out))),
            ('material parameters', lambda: xeck_matparams.run(str(xeck), str(out))),
            ('mesh -> material links (OBJ + .mtl)', lambda: xeck_links.link(str(xeck), str(out))),
            ('skeleton', lambda: xeck_skeleton.run(str(xeck), str(out))),
            ('glb (meshes + skeleton + weights + materials)',
             lambda: xeck_gltf.build(str(xeck), str(out), str(out / (xeck.stem + '.glb')), include_hidden=include_hidden_meshes)),
        ]
        
        report = []
        for label, fn in steps:
            self.log(f"[*] {label} ...")
            try:
                with contextlib.redirect_stdout(_LogWriter(self.log)):
                    fn()
                report.append(f"{label}: ok")
            except Exception as e:
                report.append(f"{label}: FAILED - {e!r}")
                self.log(f"[!] {label} failed: {e}")
                self.log(traceback.format_exc())
                
        (out / 'summary.txt').write_text('\n'.join([f"file: {xeck.name}"] + report))
        self.log(f"[+] Angels finished {xeck.name}: " + ('all steps ok' if all(r.endswith('ok') for r in report) else 'some steps failed, see log'))
        return out