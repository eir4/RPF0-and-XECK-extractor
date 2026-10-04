# RPF0 & XECK Extractor
<img width="3700" height="2600" alt="RPF0   XEC EXTRACTOR (3700 x 2600 px)" src="https://github.com/user-attachments/assets/b496151d-32d1-461c-8c8a-c9102ae090d7" />

[cite: 13]

This toolset allows for the extraction of both RPF v0 archives and XECK binary files, which are proprietary formats used in *Rockstar Games Presents Table Tennis* for the Xbox 360[cite: 13].

<img width="600" alt="image" src="https://github.com/user-attachments/assets/f2e1ab85-bb63-493d-aded-4122b8d8aae3" />
 
<img width="600" alt="image" src="https://github.com/user-attachments/assets/c8db5401-4602-4e35-a1ff-ba4a72ba8ecb" />

`[cite: 13]` (Now with themes, and simplified UI)

## Usage Guide

### Extracting RPF Files
If you only need to unpack standard .rpf archives, use the **rpf_extractor** module  `[cite: 13]`. 
<img width="600" alt="image" src="https://github.com/user-attachments/assets/49aa81ad-e3d0-441c-82a4-4b1b46876448" />
`[cite: 13]`

### Extracting XECK Files (Main GUI)
For character files, the toolkit provides a dedicated interface:
1. Launch RPF-XECK-Extractor_2.py to open the main GUI  `[cite: 13]`.
2. Select your target `.xeck` file and designate an output folder  `[cite: 13]`.
3. Navigate to the **XECK** interface tab to access specific extraction modules  `[cite: 13]`.

<img width="600" alt="image" src="https://github.com/user-attachments/assets/21cc9c99-447d-40c1-b469-00d6258193bf" />
`[cite: 13]`

### Mesh Extraction (Kaworu Module)
Use the **Kaworu** tab for automated extraction of 3D meshes `[cite: 13]`. Meshes are exported in standard .obj format and include their original UV maps automatically decoded from the vertex buffers `[cite: 12, 13]`. 
<img width="600" alt="image" src="https://github.com/user-attachments/assets/c6314ea0-e5ca-4197-8384-84fda214929d" />
`[cite: 13]`

*(Note: Bare meshes do not contain textures natively, but the material grouping is preserved in the output for easy mapping[cite: 11, 13].)*
<img width="600" alt="image" src="https://github.com/user-attachments/assets/d55cba70-8e55-423e-8716-e0738fe9e82c" />
`[cite: 13]`

### Texture Extraction (Misato Module)
1. Within the main GUI, switch to the **Misato** tab under the XECK side `[cite: 13]`.
2. This module bypasses the lack of standard headers by finding Xenos GPU fetch constants, untangling the tiled memory, and saving the files as standard DDS and PNG textures `[cite: 7, 9, 13]`.
<img width="600" alt="image" src="https://github.com/user-attachments/assets/cf461073-ffbb-426d-b587-5dbbf183d5c8" />
`[cite: 13]`

You can manually map these extracted textures onto your models in your preferred 3D software`[cite: 13]`. 
<img width="600" alt="image" src="https://github.com/user-attachments/assets/79f41d46-30da-4b79-96bc-fa7f18aa4c31" />
`[cite: 13]`

Materials are successfully extracted and linked, allowing for easy imports directly into Blender`[cite: 13]`. *(Note: Some complex layered shaders, like hair physics strips, may require manual tweaking as they can look slightly off by default`[cite: 13]`.)*
<img width="600" alt="image" src="https://github.com/user-attachments/assets/a4fd4b54-13c2-4822-b5d1-6eaf46b2731f" />
`[cite: 13]`

---

## Technical Documentation & Key Discoveries

During the reverse-engineering of the .xeck file structure, several key discoveries were made to enable this extraction:

* **File Architecture:** The `.xeck files` are not flat tables. They are big-endian serialized object graphs acting as a flat memory image with a single base pointer `[cite: 7]`. Pointers are calculated dynamically (e.g., file_offset = pointer - BASE)[cite: 7].
* **Mesh & UV Geometry:** Meshes store their vertex descriptors dynamically (sitting 0x18C or 0x19C bytes after the geometry record, depending on header versions like 0x414 or 0x417)[cite: 7, 10]. UV coordinates are not standalone maps; they are stored directly inside the vertex buffer as float32 pairs (e.g., at byte offsets 24/28 or 48/52 depending on the stride)[cite: 7, 10].
* **Cloth Physics Variants:** Dynamic cloth meshes (such as skirts and shirts) use a 96-byte stride and duplicate their geometry four times[cite: 7, 10]. While three copies wrap the static body, the third copy often features a flared "A-pose," which serves as the reference state for the game's cloth simulation[cite: 7]. 
* **Texture Decoding:** The files do not contain DDS signatures `[cite: 7]`. Instead, they utilize Xbox 360 Xenos GPU fetch constants[cite: 7, 9]. Textures are 16-bit word-swapped and 2D-tiled in 32x32 block macro tiles `[cite: 7, 9]`. The extractor manually untiles these blocks and places mip-tails (where smaller mip levels share a single 4 KB page) to rebuild standard DDS format `[cite: 7, 9]`. 
* **Material Linking:** Materials are embedded as .sps shader presets rather than standard .mtl files[cite: 7, 8]. The tool tracks group objects tagged with `0x8200B5E4`—which hold lists of material indices—to successfully link specific materials to their corresponding geometry[cite: 7, 11]. 
* **Current Limitations:** The current toolset focuses on character `.xeck` files `[cite: 7]`. Skeletons, model-space normals, skinning weights, and level/map `.xeck` files (which utilize newer headers like 0xed and 0xcb) are not yet fully decoded `[cite: 7, 12]`.
