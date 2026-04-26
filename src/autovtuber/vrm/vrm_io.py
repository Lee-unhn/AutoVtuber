"""VRM 0.x 讀寫工具（基於 pygltflib + Pillow）。

VRM 是 glTF 2.0 的子集 + `VRM` extension JSON。pygltflib 不認得 VRM extension，
但會把它當不透明 JSON 保留 → 我們只動 image/bufferView 就能保留所有 VRM metadata。

關鍵不變式：
    - 替換 image bytes 後，必須 patch 後續所有 bufferView 的 byteOffset
    - 必須 patch buffer 的 byteLength
    - VRM extension 區塊 byte-perfect 保留
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from pygltflib import GLTF2, BufferFormat


class VRMFile:
    """包裝 pygltflib.GLTF2，提供 VRM 安全的圖像替換 API。"""

    def __init__(self, gltf: GLTF2):
        self._gltf = gltf

    # ---------------- 載入 / 儲存 ---------------- #

    @classmethod
    def load(cls, path: Path | str) -> "VRMFile":
        """讀取 .vrm 檔（其實就是 .glb 容器）。

        ⚠️ pygltflib.GLTF2.load() 會根據副檔名自動切 JSON/binary 路徑，但
        `.vrm` 不在它的 binary 副檔名清單，所以強制走 `load_binary()`。
        若副檔名是 .gltf 才走 load_json。
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        suffix = path.suffix.lower()
        if suffix == ".gltf":
            gltf = GLTF2.load(str(path))
        else:
            # .vrm / .glb / 其他都當 binary
            gltf = GLTF2.load_binary(str(path))
        gltf.convert_buffers(BufferFormat.BINARYBLOB)
        return cls(gltf)

    def save(self, path: Path | str) -> Path:
        """寫出 .vrm（強制 .glb 二進位格式）。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # VRM 一定要是 binary glTF
        self._gltf.convert_buffers(BufferFormat.BINARYBLOB)
        self._gltf.save_binary(str(path))
        return path

    # ---------------- 圖像查詢 ---------------- #

    def list_images(self) -> list[dict]:
        """列出所有 image 條目，含 (index, name, mimeType, byte_size) 摘要。"""
        out = []
        for i, img in enumerate(self._gltf.images or []):
            entry = {"index": i, "name": img.name or "", "mimeType": img.mimeType}
            if img.bufferView is not None:
                bv = self._gltf.bufferViews[img.bufferView]
                entry["byte_size"] = bv.byteLength
            out.append(entry)
        return out

    def get_image_bytes(self, image_index: int) -> bytes:
        """取出指定 image 的原始 bytes。"""
        img = self._gltf.images[image_index]
        if img.bufferView is None:
            raise ValueError(f"Image {image_index} has no bufferView (external uri not supported)")
        bv = self._gltf.bufferViews[img.bufferView]
        blob = self._gltf.binary_blob()
        return bytes(blob[bv.byteOffset: bv.byteOffset + bv.byteLength])

    def get_image_pil(self, image_index: int) -> Image.Image:
        """取出指定 image 為 PIL Image。"""
        return Image.open(io.BytesIO(self.get_image_bytes(image_index)))

    # ---------------- 圖像替換 ---------------- #

    def replace_image(
        self,
        image_index: int,
        new_image: Image.Image | bytes,
        mime_type: str = "image/png",
    ) -> None:
        """替換指定 index 的圖像。會自動 patch 後續所有 bufferView byteOffset。

        VRM extension 區塊不會被動到。

        Args:
            image_index: images[] 索引
            new_image: PIL Image 或已經是 bytes
            mime_type: 一般 "image/png" 或 "image/jpeg"
        """
        if isinstance(new_image, Image.Image):
            buf = io.BytesIO()
            fmt = "PNG" if mime_type.endswith("png") else "JPEG"
            new_image.save(buf, format=fmt)
            new_bytes = buf.getvalue()
        else:
            new_bytes = bytes(new_image)

        img = self._gltf.images[image_index]
        if img.bufferView is None:
            raise ValueError(f"Image {image_index} has no bufferView")
        bv_idx = img.bufferView
        old_bv = self._gltf.bufferViews[bv_idx]
        old_offset = old_bv.byteOffset
        old_length = old_bv.byteLength

        blob = bytearray(self._gltf.binary_blob())
        # 切下舊段，貼上新段
        blob = blob[:old_offset] + bytearray(new_bytes) + blob[old_offset + old_length:]
        delta = len(new_bytes) - old_length

        # 更新被改的 bufferView
        old_bv.byteLength = len(new_bytes)

        # 後續所有 bufferView 的 byteOffset 都要 +delta
        if delta != 0:
            for i, bv in enumerate(self._gltf.bufferViews):
                if i == bv_idx:
                    continue
                if bv.byteOffset is not None and bv.byteOffset > old_offset:
                    bv.byteOffset += delta
            # buffer.byteLength 也要更新
            for buf_obj in self._gltf.buffers:
                buf_obj.byteLength = len(blob)

        self._gltf.set_binary_blob(bytes(blob))
        # 更新 mimeType（可能從 jpeg 改 png 等）
        img.mimeType = mime_type

    # ---------------- 暴露原始 GLTF 給進階使用者 ---------------- #

    @property
    def raw(self) -> GLTF2:
        return self._gltf

    @property
    def vrm_meta(self) -> dict | None:
        """回傳 VRM extension 區塊（如果存在）。VRM 0.x 是 'VRM'，1.0 是 'VRMC_vrm'。"""
        ext = self._gltf.extensions or {}
        if "VRM" in ext:
            return ext["VRM"]
        if "VRMC_vrm" in ext:
            return ext["VRMC_vrm"]
        return None

    @property
    def vrm_version(self) -> str:
        if self._gltf.extensions and "VRMC_vrm" in self._gltf.extensions:
            return "1.0"
        if self._gltf.extensions and "VRM" in self._gltf.extensions:
            return "0.x"
        return "unknown"
