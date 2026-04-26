"""VRMFile 測試 — 用 fixture 建一個最小 glTF 驗證 image 替換邏輯。

不依賴真實 .vrm 檔；用 pygltflib 程式建立 minimal binary glTF 含 1 張圖像。
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest


@pytest.fixture
def tiny_glb(tmp_path: Path) -> Path:
    """建立含 1 張 16x16 紅色 PNG 的最小 binary glTF 檔。"""
    pytest.importorskip("pygltflib")
    pytest.importorskip("PIL")
    from PIL import Image
    from pygltflib import (
        GLTF2,
        Asset,
        Buffer,
        BufferFormat,
        BufferView,
        Image as GLImage,
    )

    # 16x16 紅色 PNG bytes
    img = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    gltf = GLTF2(
        asset=Asset(version="2.0", generator="autovtuber-test"),
        buffers=[Buffer(byteLength=len(png_bytes))],
        bufferViews=[BufferView(buffer=0, byteOffset=0, byteLength=len(png_bytes))],
        images=[GLImage(name="test_img", mimeType="image/png", bufferView=0)],
    )
    gltf.set_binary_blob(png_bytes)
    gltf.convert_buffers(BufferFormat.BINARYBLOB)
    out = tmp_path / "tiny.glb"
    gltf.save_binary(str(out))
    return out


def test_vrm_load_and_list_images(tiny_glb: Path):
    from autovtuber.vrm.vrm_io import VRMFile

    vrm = VRMFile.load(tiny_glb)
    images = vrm.list_images()
    assert len(images) == 1
    assert images[0]["index"] == 0
    assert images[0]["name"] == "test_img"
    assert images[0]["mimeType"] == "image/png"


def test_vrm_get_image_pil(tiny_glb: Path):
    from autovtuber.vrm.vrm_io import VRMFile

    vrm = VRMFile.load(tiny_glb)
    img = vrm.get_image_pil(0)
    assert img.size == (16, 16)


def test_vrm_replace_image_same_size_round_trip(tiny_glb: Path, tmp_path: Path):
    """同尺寸替換：bufferView byteLength 不變，無 offset patch 需要。"""
    from PIL import Image
    from autovtuber.vrm.vrm_io import VRMFile

    vrm = VRMFile.load(tiny_glb)
    new_img = Image.new("RGBA", (16, 16), (0, 255, 0, 255))  # 綠色
    vrm.replace_image(0, new_img, mime_type="image/png")
    out = tmp_path / "out.glb"
    vrm.save(out)

    # 重新讀回，檢查確實是綠色
    vrm2 = VRMFile.load(out)
    img2 = vrm2.get_image_pil(0)
    assert img2.size == (16, 16)
    px = img2.getpixel((8, 8))
    # PNG 壓縮可能輕微失真，但綠色主導應明顯
    assert px[1] > 200 and px[0] < 50


def test_vrm_replace_image_larger_size_patches_offsets(tmp_path: Path):
    """新圖較大時，需要 patch 後續所有 bufferView 的 byteOffset。"""
    from PIL import Image
    from pygltflib import (
        GLTF2,
        Asset,
        Buffer,
        BufferFormat,
        BufferView,
        Image as GLImage,
    )
    from autovtuber.vrm.vrm_io import VRMFile

    # 兩張圖：第一張 16x16（會被替換放大），第二張 8x8（測 offset patch）
    img_a = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
    img_b = Image.new("RGBA", (8, 8), (0, 0, 255, 255))
    a_bytes = _png_bytes(img_a)
    b_bytes = _png_bytes(img_b)
    blob = a_bytes + b_bytes

    gltf = GLTF2(
        asset=Asset(version="2.0", generator="t"),
        buffers=[Buffer(byteLength=len(blob))],
        bufferViews=[
            BufferView(buffer=0, byteOffset=0, byteLength=len(a_bytes)),
            BufferView(buffer=0, byteOffset=len(a_bytes), byteLength=len(b_bytes)),
        ],
        images=[
            GLImage(name="a", mimeType="image/png", bufferView=0),
            GLImage(name="b", mimeType="image/png", bufferView=1),
        ],
    )
    gltf.set_binary_blob(blob)
    gltf.convert_buffers(BufferFormat.BINARYBLOB)
    src = tmp_path / "two.glb"
    gltf.save_binary(str(src))

    vrm = VRMFile.load(src)
    # 把 image[0] 換成 64x64（一定比 a_bytes 大）
    big = Image.new("RGBA", (64, 64), (0, 255, 0, 255))
    vrm.replace_image(0, big, mime_type="image/png")
    out = tmp_path / "out.glb"
    vrm.save(out)

    # 重新讀，第二張圖必須仍能正確讀到藍色
    vrm2 = VRMFile.load(out)
    assert len(vrm2.list_images()) == 2
    img_b2 = vrm2.get_image_pil(1)
    assert img_b2.size == (8, 8)
    px = img_b2.getpixel((4, 4))
    assert px[2] > 200 and px[0] < 50  # 仍是藍色


def _png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_vrm_version_unknown_for_plain_gltf(tiny_glb: Path):
    """普通 glTF（非 VRM）的 version 報為 unknown。"""
    from autovtuber.vrm.vrm_io import VRMFile

    vrm = VRMFile.load(tiny_glb)
    assert vrm.vrm_version == "unknown"
    assert vrm.vrm_meta is None
