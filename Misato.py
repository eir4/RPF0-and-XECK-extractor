import struct
import os
import csv
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
    """Untiles Xenos micro/macro block layout back to linear little-endian DDS order."""
    l2 = 3 if bs == 8 else 4
    wal = width_blocks or _pad32(bw)
    ys, xs = np.divmod(np.arange(bw * bh), bw)
    out = np.empty((bw * bh, bs), np.uint8)
    for i in range(bw * bh):
        o = start + tiled(int(xs[i]) + ox, int(ys[i]) + oy, wal, l2)
        out[i] = np.frombuffer(raw, np.uint8, bs, o)
    return out.reshape(-1, bs // 2, 2)[:, :, ::-1].reshape(-1).tobytes()

def find_fetch_constants(raw, base):
    """Locates 0x70-byte texture records based on GPU fetch constants."""
    a = np.frombuffer(raw[:len(raw) // 4 * 4], dtype='>u4')
    res = []
    for i in range(len(a) - 6):
        d0 = int(a[i])
        if (d0 & 0x80000003) != 0x80000002: continue
        d1 = int(a[i + 1])
        if not (base <= d1 < base + len(raw)) or (d1 & 0x3F) not in FMT or ((d1 >> 6) & 3) != 1: continue
        d2 = int(a[i + 2])
        w = (d2 & 0x1FFF) + 1
        h = ((d2 >> 13) & 0x1FFF) + 1
        if w < 4 or h < 4 or (w & (w - 1)) or (h & (h - 1)): continue
        res.append(dict(at=i * 4, d=[int(x) for x in a[i:i + 6]], w=w, h=h, fmt=d1 & 0x3F))
    return res

def guess_name(raw, at):
    for back in (0x30,):
        s = raw[at - back:at - back + 0x20].split(b'\0')[0]
        if 3 < len(s) < 0x20 and all(32 <= c < 127 for c in s): 
            return s.decode()
    return None

def level_plan(w, h, bs, base_off, mip_off, nlevels):
    """Calculates mipmap tail offsets and block sizes."""
    tail_at = 0 if min(w, h) <= 16 else (min(w, h).bit_length() - 1) - 4 + (0 if (min(w, h) & (min(w, h) - 1)) == 0 else 1)
    plan = []
    cur = mip_off
    for lv in range(nlevels):
        lw, lh = max(1, w >> lv), max(1, h >> lv)
        bw, bh = max(1, lw // 4), max(1, lh // 4)
        if lv == 0:
            plan.append((0, bw, bh, base_off, 0, 0, None))
            continue
        if lv >= tail_at:
            if lv == tail_at: tail_page = cur
            ox, oy = (0, bh) if w > h else (bw, 0)
            plan.append((lv, bw, bh, tail_page, ox, oy, 32))
            continue
        plan.append((lv, bw, bh, cur, 0, 0, None))
        cur += _pad32(bw) * _pad32(bh) * bs
    return plan

def rip_texture(raw, base, tex):
    w, h, d = tex['w'], tex['h'], tex['d']
    fourcc, bs = FMT[tex['fmt']]
    base_off = (d[1] & ~0xFFF) - base
    mip_ptr = d[5] & ~0xFFF
    mip_off = mip_ptr - base if base <= mip_ptr < base + len(raw) else None
    
    nlev = int(np.log2(min(w, h))) - 1
    if mip_off is None or (d[5] & 0xFFF) == 0 and mip_off is None: 
        nlev = 1
        
    blocks = []
    for lv, bw, bh, start, ox, oy, wb in level_plan(w, h, bs, base_off, mip_off or 0, nlev):
        blocks.append(untile_level(raw, start, bw, bh, bs, ox, oy, wb))
        
    hdr = bytearray(128)
    hdr[0:4] = b'DDS '
    struct.pack_into('<7I', hdr, 4, 124, 0xA1007 if nlev > 1 else 0x81007, h, w, len(blocks[0]), 0, nlev)
    struct.pack_into('<II', hdr, 76, 32, 4)
    hdr[84:88] = fourcc
    struct.pack_into('<I', hdr, 108, 0x401008 if nlev > 1 else 0x1000)
    
    return bytes(hdr) + b''.join(blocks), nlev

class MisatoExtractor:
    """Master Orchestrator for XECK Texture Extraction."""

    def __init__(self, xeck_path: str, *args, **kwargs):
        self.xeck_path = Path(xeck_path)
        self.raw = self.xeck_path.read_bytes()
        self.log_callback = kwargs.get("log_callback", print)

    def log(self, message: str):
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def run_pipeline(self, output_dir: str):
        self.log(f"[*] Initializing Misato Texture Extraction for {self.xeck_path.name}...")
        
        try:
            base = struct.unpack_from('>I', self.raw, 8)[0]
        except Exception as e:
            self.log(f"[!] Failed to read header base: {e}")
            return

        out = Path(output_dir) / "textures"
        out.mkdir(parents=True, exist_ok=True)
        
        try:
            from PIL import Image
            have_pil = True
            self.log("[+] PIL detected. PNG conversion active.")
        except Exception:
            have_pil = False
            self.log("[-] PIL not found. Skipping PNGs (DDS only).")

        table = []
        textures = find_fetch_constants(self.raw, base)
        self.log(f"[+] Discovered {len(textures)} texture GPU fetch records.")

        for n, tex in enumerate(textures):
            name = guess_name(self.raw, tex['at']) or f"tex_{n:03d}"
            stem = f"{n:03d}_{os.path.splitext(name)[0]}"
            
            try:
                data, nlev = rip_texture(self.raw, base, tex)
                (out / f"{stem}.dds").write_bytes(data)
                
                png_status = ''
                if have_pil:
                    try:
                        import io
                        Image.open(io.BytesIO(data)).convert('RGBA').save(out / f"{stem}.png")
                        png_status = f"{stem}.png"
                    except Exception as e:
                        png_status = f'failed: {e}'
                        
                format_str = FMT[tex['fmt']][0].decode()
                table.append((n, hex(tex['at']), name, tex['w'], tex['h'], format_str, nlev, hex((tex['d'][1] & ~0xFFF) - base), f"{stem}.dds", png_status))
                self.log(f"    - Ripped #{n:03d} | {name} | {tex['w']}x{tex['h']} | {format_str} | Mips: {nlev}")
                
            except Exception as e:
                self.log(f"    [!] Failed to rip texture {name} at {hex(tex['at'])}: {e}")

        csv_path = out / f"texture_table_{self.xeck_path.stem}.csv"
        with open(csv_path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['n', 'record_at', 'name', 'w', 'h', 'format', 'mips', 'data_offset', 'dds', 'png'])
            w.writerows(table)
            
        self.log(f"\n[+] Misato Pipeline Complete! Extracted {len(table)} textures.")