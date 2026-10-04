"""
xeck_textures.py - rip every texture out of a RAGE .xeck (Xbox 360) as standard DDS (+PNG if Pillow is present).

Verified on char_usa.xeck by byte-comparing against DDS files exported from RenderDoc:
  * texture record: 0x70-byte objects.  Their Xenos GPU *fetch constant* (6 big-endian dwords) holds everything:
      d0 : 0x80000002 bit31 = tiled, bits 22-30 = pitch/32 (texels)
      d1 : bits 12-31 = base address (pointer; file_off = ptr - BASE), bits 6-7 = endian (1 = swap 16-bit), bits 0-5 = format
           format 0x12 = DXT1 (BC1), 0x14 = DXT4/5 (BC3)   (0x13 = DXT2/3 assumed)
      d2 : (width-1) | (height-1) << 13
      d5 : bits 12-31 = address of mip level 1
  * data is 2D-tiled in 32x32-block macro tiles (formula in tiled()), 16-bit word swapped
  * levels >=1: consecutive, each padded to 32x32 blocks, from the d5 address
  * mip tail (first level whose smaller side is 16 px): all remaining levels share ONE 4 KB page,
    level placed at block-x offset = its own width in blocks (square textures); for wide textures at block-y offset = its height
Usage: python xeck_textures.py char_usa.xeck [out_dir]
"""
import struct, sys, os
from pathlib import Path
import numpy as np

FMT = {0x12: (b'DXT1', 8), 0x13: (b'DXT3', 16), 0x14: (b'DXT5', 16)}

def _outer(y, width, l2):
    macro = ((y >> 5) * (width >> 5)) << (l2 + 7)
    micro = ((y & 6) << 2) << l2
    return macro + ((micro & ~0xF) << 1) + (micro & 0xF) + ((y & 8) << (3 + l2)) + ((y & 1) << 4)

def tiled(x, y, width, l2):
    base = _outer(y, width, l2)
    macro = (x >> 5) << (l2 + 7)
    micro = (x & 7) << l2
    off = base + macro + ((micro & ~0xF) << 1) + (micro & 0xF)
    return ((off & ~0x1FF) << 3) + ((y & 16) << 7) + ((off & 0x1C0) << 2) + (((((y & 8) >> 2) + (x >> 3)) & 3) << 6) + (off & 0x3F)

def _pad32(n): return (n + 31) // 32 * 32

def untile_level(raw, start, bw, bh, bs, ox=0, oy=0, width_blocks=None):
    """-> linear bytes (bw*bh*bs) with 16-bit words swapped back to little-endian DDS order"""
    l2 = 3 if bs == 8 else 4
    wal = width_blocks or _pad32(bw)
    ys, xs = np.divmod(np.arange(bw * bh), bw)
    out = np.empty((bw * bh, bs), np.uint8)
    for i in range(bw * bh):
        o = start + tiled(int(xs[i]) + ox, int(ys[i]) + oy, wal, l2)
        out[i] = np.frombuffer(raw, np.uint8, bs, o)
    return out.reshape(-1, bs // 2, 2)[:, :, ::-1].reshape(-1).tobytes()

def find_fetch_constants(raw, base):
    a = np.frombuffer(raw[:len(raw) // 4 * 4], dtype='>u4'); res = []
    for i in range(len(a) - 6):
        d0 = int(a[i])
        if (d0 & 0x80000003) != 0x80000002 or (d0 >> 3) & 0x7FFFFFF and False: continue
        d1 = int(a[i + 1])
        if not (base <= d1 < base + len(raw)) or (d1 & 0x3F) not in FMT or ((d1 >> 6) & 3) != 1: continue
        d2 = int(a[i + 2]); w = (d2 & 0x1FFF) + 1; h = ((d2 >> 13) & 0x1FFF) + 1
        if w < 4 or h < 4 or w > 4096 or h > 4096 or (w & (w - 1)) or (h & (h - 1)): continue
        if raw[i * 4 - 16:i * 4] != SIG: continue              # every real fetch constant is preceded by this 16-byte signature
        if (d1 & ~0xFFF) - base + w * h // 2 > len(raw): continue
        res.append(dict(at=i * 4, d=[int(x) for x in a[i:i + 6]], w=w, h=h, fmt=d1 & 0x3F))
    return res

SIG = bytes.fromhex('40030001' '00000000' 'ffff0000' 'ffff0000')
TEX_TAG = b'\x82\x02\xcc\x84'      # type tag at the start of every texture record

def record_start(raw, at):
    r = raw.rfind(TEX_TAG, max(0, at - 0x80), at)
    return r if r >= 0 else None

def guess_name(raw, at):
    r = record_start(raw, at)
    if r is None: return None
    s = raw[r + 0x20:r + 0x50].split(b'\0')[0]       # name field starts 0x20 into the record (up to 0x30 long)
    return s.decode() if 3 < len(s) and all(32 <= c < 127 for c in s) else None

def level_plan(w, h, bs, base_off, mip_off, nlevels):
    """-> list of (level, bw, bh, start, ox, oy, width_blocks)"""
    tail_at = 0 if min(w, h) <= 16 else (min(w, h).bit_length() - 1) - 4 + (0 if (min(w, h) & (min(w, h) - 1)) == 0 else 1)
    plan = []; cur = mip_off
    for lv in range(nlevels):
        lw, lh = max(1, w >> lv), max(1, h >> lv); bw, bh = max(1, lw // 4), max(1, lh // 4)
        if lv == 0:
            plan.append((0, bw, bh, base_off, 0, 0, None)); continue
        if lv >= tail_at:
            if lv == tail_at: tail_page = cur
            # tail packing: square/tall -> shifted along x by its own block width (verified on 1024/512 squares);
            #               wide      -> shifted along y by its own block height (verified by image similarity on 512x256, 128x64)
            ox, oy = (0, bh) if w > h else (bw, 0)
            plan.append((lv, bw, bh, tail_page, ox, oy, 32)); continue
        plan.append((lv, bw, bh, cur, 0, 0, None))
        cur += _pad32(bw) * _pad32(bh) * bs
    return plan

def rip_texture(raw, base, tex):
    w, h, d = tex['w'], tex['h'], tex['d']; fourcc, bs = FMT[tex['fmt']]
    base_off = (d[1] & ~0xFFF) - base
    mip_ptr = d[5] & ~0xFFF
    mip_off = mip_ptr - base if base <= mip_ptr < base + len(raw) else None
    nlev = int(np.log2(min(w, h))) - 1                       # down to 4x4
    if mip_off is None or (d[5] & 0xFFF) == 0 and mip_off is None: nlev = 1
    blocks = []
    for lv, bw, bh, start, ox, oy, wb in level_plan(w, h, bs, base_off, mip_off or 0, nlev):
        blocks.append(untile_level(raw, start, bw, bh, bs, ox, oy, wb))
    hdr = bytearray(128)
    hdr[0:4] = b'DDS '; struct.pack_into('<7I', hdr, 4, 124, 0xA1007 if nlev > 1 else 0x81007, h, w, len(blocks[0]), 0, nlev)
    struct.pack_into('<II', hdr, 76, 32, 4); hdr[84:88] = fourcc
    struct.pack_into('<I', hdr, 108, 0x401008 if nlev > 1 else 0x1000)
    return bytes(hdr) + b''.join(blocks), nlev

def run(path, out_dir):
    raw = Path(path).read_bytes(); base = struct.unpack_from('>I', raw, 8)[0]
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image; have_pil = True
    except Exception: have_pil = False
    table = []
    for n, tex in enumerate(find_fetch_constants(raw, base)):
        name = guess_name(raw, tex['at']) or f"tex_{n:03d}"
        stem = f"{n:03d}_{os.path.splitext(name)[0]}"
        data, nlev = rip_texture(raw, base, tex)
        (out / f"{stem}.dds").write_bytes(data)
        png = ''
        if have_pil:
            try:
                import io
                Image.open(io.BytesIO(data)).convert('RGBA').save(out / f"{stem}.png"); png = f"{stem}.png"
            except Exception as e: png = f'png failed: {e}'
        table.append((n, hex(tex['at']), name, tex['w'], tex['h'], FMT[tex['fmt']][0].decode(), nlev, hex((tex['d'][1] & ~0xFFF) - base), f"{stem}.dds", png))
    import csv
    with open(out / 'texture_table.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['n', 'record_at', 'name', 'w', 'h', 'format', 'mips', 'data_offset', 'dds', 'png']); w.writerows(table)
    print(f"{len(table)} textures -> {out}")

if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'char_usa.xeck', sys.argv[2] if len(sys.argv) > 2 else './xeck_textures_out')
