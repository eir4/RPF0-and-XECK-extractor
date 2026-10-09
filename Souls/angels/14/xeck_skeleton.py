"""
xeck_skeleton.py - read the character skeleton from a RAGE .xeck and write skeleton.json / skeleton.csv / build_armature.py

Bone record (verified on char_usa; big-endian, 0xC0 bytes each, bones stored back to back, depth-first order):
  +0x00 ptr  bone name (C string)        +0x04 u32 flags
  +0x08 ptr  next SIBLING bone (or 0)    +0x0C ptr  next bone in the array (i+1)
  +0x10 ptr  PARENT bone (0 for root)    +0x14 u32  bone id / hash
  +0x20 vec4 LOCAL translation (x,y,z)   +0x30 vec4 local rotation (euler radians, XYZ order assumed)
  +0x50 vec4 MODEL-SPACE position of the bone (= sum of the local translations along the parents; checked)
  +0xA0/+0xB0 vec4 rotation limits (-pi / +pi)
Not decoded: rotation order, scale (+0x40 is zero in every bone I looked at), the bone-id hashes.
"""
import struct, sys, json, csv
from pathlib import Path
import numpy as np

BONE = 0xC0

def cstr(raw, o):
    if not 0 <= o < len(raw): return None
    e = raw.find(b'\0', o, o + 64)
    s = raw[o:e if e != -1 else o + 64]
    return s.decode('ascii') if s and all(32 <= c < 127 for c in s) else None

def find_bones(raw, base):
    """Bones are stored depth-first, 0xC0 apart.  Find a root (parent == 0) whose next record has the root as parent, then
    extend while the record still looks like a bone (valid name pointer, parent pointer inside the array)."""
    a = np.frombuffer(raw[:len(raw) // 4 * 4], '>u4')
    # +0x10 slot holds the parent: look for any slot pointing at (p) from (p+BONE+0x10)
    for i in np.nonzero((a >= base) & (a < base + len(raw)))[0]:
        q = int(i) * 4                       # candidate parent slot of the SECOND bone
        p = int(a[i]) - base                 # candidate first bone
        if q - 0x10 != p + BONE: continue
        if struct.unpack_from('>I', raw, p + 0x10)[0] != 0: continue
        if cstr(raw, int(a[p // 4]) - base) is None: continue
        offs = [p]
        while True:
            o = offs[-1] + BONE
            if o + BONE > len(raw): break
            w = struct.unpack_from('>6I', raw, o)
            par = w[4] - base
            if cstr(raw, w[0] - base) is None or not (offs[0] <= par <= o and (par - offs[0]) % BONE == 0): break
            offs.append(o)
        if len(offs) > 8: return offs
    return []

def read_skeleton(raw, base):
    offs = find_bones(raw, base); idx = {o: i for i, o in enumerate(offs)}; bones = []
    for i, o in enumerate(offs):
        w = struct.unpack_from('>12I', raw, o); f = struct.unpack_from('>48f', raw, o)
        par = idx.get(w[4] - base, -1) if w[4] else -1
        bones.append(dict(index=i, name=cstr(raw, w[0] - base), parent=par, flags=hex(w[1]), bone_id=hex(w[5]),
                          local_t=[round(x, 6) for x in f[8:11]], local_rot_euler=[round(x, 6) for x in f[12:15]],
                          model_pos=[round(x, 6) for x in f[20:23]]))
    return bones

ARMATURE_PY = '''# Blender 4.x:  Scripting tab -> open this file -> Run.   Creates an armature from skeleton.json (same folder).
import bpy, json, os
from mathutils import Vector
path = os.path.join(os.path.dirname(bpy.data.filepath) or os.path.dirname(__file__), "skeleton.json")
bones = json.load(open(path))
arm = bpy.data.armatures.new("xeck_skeleton"); obj = bpy.data.objects.new("xeck_skeleton", arm)
bpy.context.collection.objects.link(obj); bpy.context.view_layer.objects.active = obj
bpy.ops.object.mode_set(mode="EDIT")
S = 1.0
def pos(b): x, y, z = b["model_pos"]; return Vector((x * S, -z * S, y * S))      # game Y-up -> Blender Z-up (matches the OBJ import rotation)
eb = {}
for b in bones:
    e = arm.edit_bones.new(b["name"]); e.head = pos(b); e.tail = pos(b) + Vector((0, 0, 0.02)); eb[b["index"]] = e
kids = {}
for b in bones: kids.setdefault(b["parent"], []).append(b["index"])
for b in bones:
    e = eb[b["index"]]
    if b["parent"] >= 0: e.parent = eb[b["parent"]]
    c = kids.get(b["index"])
    if c:   # point the bone at its first child
        e.tail = eb[c[0]].head
        if (e.tail - e.head).length < 1e-4: e.tail = e.head + Vector((0, 0, 0.02))
bpy.ops.object.mode_set(mode="OBJECT")
print("created", len(bones), "bones")
'''

def run(path, out_dir):
    raw = Path(path).read_bytes(); base = struct.unpack_from('>I', raw, 8)[0]
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    bones = read_skeleton(raw, base)
    (out / 'skeleton.json').write_text(json.dumps(bones, indent=1))
    with open(out / 'skeleton.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['index', 'name', 'parent', 'parent_name', 'local_x', 'local_y', 'local_z', 'model_x', 'model_y', 'model_z', 'rot_x', 'rot_y', 'rot_z'])
        for b in bones: w.writerow([b['index'], b['name'], b['parent'], bones[b['parent']]['name'] if b['parent'] >= 0 else '', *b['local_t'], *b['model_pos'], *b['local_rot_euler']])
    (out / 'build_armature.py').write_text(ARMATURE_PY)
    print(f"{len(bones)} bones -> {out}")
    return bones

if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'char_usa.xeck', sys.argv[2] if len(sys.argv) > 2 else './skeleton_out')
