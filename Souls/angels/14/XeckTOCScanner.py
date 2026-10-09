import re
import json
import csv
from pathlib import Path
from dataclasses import dataclass, asdict

TOKEN = re.compile(rb'[ -~]{4,}')

@dataclass
class MaterialMetadata:
    index: int
    offset: int
    sps: str
    shader: str
    entity: str
    slots: dict
    params: list

class XeckMaterialScanner:
    """
    Replaces TOC Scanner. Extracts embedded shader presets (.sps), instances (.sva), 
    and texture bindings (.dds) from the material table embedded in the RAGE .xeck.
    """
    def __init__(self, raw_bytes: bytes):
        self.raw = raw_bytes

    def _clean(self, s: str, anchors: tuple) -> str:
        for a in anchors:
            i = s.find(a)
            if i > 0 and s[i-1:i].isalnum() is not None:
                return s[i:]
        return s

    def parse_materials(self) -> list:
        mats = []
        cur = None
        slot = None
        last = None

        for m in TOKEN.finditer(self.raw):
            s = m.group().decode('ascii')
            
            if (s.endswith('.sps') and 'character/' in s) or (s.endswith('.sps') and '/' in s):
                cur = {
                    'index': len(mats), 'offset': m.start(), 
                    'sps': self._clean(s, ('character/', 'pong_', 'effects/')), 
                    'shader': '', 'entity': '', 'slots': {}, 'params': []
                }
                mats.append(cur)
                slot = None
            elif cur is None:
                continue
            elif s.endswith('.fxc'):
                cur['shader'] = s.split('/')[-1]
            elif s.endswith('.sva'):
                cur['entity'] = self._clean(s, ('entity_',)).replace('.sva', '')
            elif s.endswith('.dds'):
                name = s
                for a in ('char_', 'dummy', 'lowr', 'hair_', 'detail', 'noise'):
                    i = s.find(a)
                    if 0 < i < 3: 
                        name = s[i:]
                        break
                if slot:
                    cur['slots'][slot] = name
                    last = slot
                    slot = None
                elif last and last + '.2nd' not in cur['slots']:
                    cur['slots'][last + '.2nd'] = name
            elif re.fullmatch(r'[A-Z][A-Za-z]*(Tex|Map|Map\d*)', s):
                slot = s
            elif re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,40}', s) and slot is None and cur['entity']:
                cur['params'].append(s)
            
            if not s.endswith('.dds') and slot and re.fullmatch(r'[A-Z][A-Za-z]*(Tex|Map|Map\d*)', s):
                cur['slots'].setdefault(s, '')
                
        # Drop stray matches
        return [m for m in mats if m['entity']]

    def export_materials(self, out_dir: Path, mats: list):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / 'materials.json').write_text(json.dumps(mats, indent=1))
        
        with open(out_dir / 'materials.csv', 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['index', 'offset', 'preset', 'shader', 'entity', 'textures'])
            for m in mats:
                tex_str = '; '.join(f"{k}={v}" for k, v in m['slots'].items() if v)
                w.writerow([m['index'], hex(m['offset']), m['sps'], m['shader'], m['entity'], tex_str])