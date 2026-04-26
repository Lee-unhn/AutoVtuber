# 📐 VRM 0.x Spec Notes

> AutoVtuber MVP1 輸出 **VRM 0.x** 格式（VSeeFace 唯一支援）。本檔案記錄相關規格細節與 pygltflib 操作筆記。

---

## VRM 0.x 與 1.0 主要差異

| 項目 | VRM 0.x | VRM 1.0 |
|---|---|---|
| 擴展名稱 | `VRM` | `VRMC_vrm` |
| BlendShape 控制 | `extensions.VRM.blendShapeMaster.blendShapeGroups` | `extensions.VRMC_vrm.expressions.preset/custom` |
| SpringBone | `extensions.VRM.secondaryAnimation` | `extensions.VRMC_springBone` |
| 標準表情名 | `Joy / Angry / Sorrow / Fun / A / I / U / E / O / Blink ...` | `happy / angry / sad / relaxed / surprised / aa / ih / ou / ee / oh / blink ...` |
| VSeeFace 支援 | ✅ | ❌（截至 2026-04） |
| VTube Studio 3D | ⚠️ 部分 | ✅ |

> **MVP1 結論：** 一律輸出 VRM 0.x。MVP3 才考慮加 VRM 1.0 雙匯出。

---

## glTF 2.0 容器結構（VRM 也是這個）

```
.vrm 檔（其實是 .glb binary glTF）
├── JSON chunk
│   ├── asset, buffers, bufferViews, accessors
│   ├── meshes, materials, nodes, scene
│   ├── images[]  ← 紋理我們會替換的地方
│   ├── extensions
│   │   ├── VRM { meta, humanoid, blendShapeMaster, secondaryAnimation, ...}
│   │   └── KHR_materials_unlit, etc.
│   └── ...
└── Binary chunk
    └── 連續的 bytes，包含所有 image bytes、mesh vertices、indices...
```

關鍵：所有 image bytes 都靠 `bufferView.byteOffset / byteLength` 來定位。

---

## pygltflib 替換 image 的「危險點」

**錯誤做法：** 直接修改 `image.uri`（VRoid VRM 內嵌 binary，沒有外部 uri）。

**正確做法：**
1. 從 `images[i].bufferView` 找到對應的 bufferView
2. 把新圖 bytes 蓋進 binary blob 對應位置
3. **更新 bufferView.byteLength** = 新圖 bytes 長度
4. **如果新圖 size != 舊 size：**
   - 計算 `delta = new_len - old_len`
   - 所有 `byteOffset > old_offset` 的 bufferView 都要 `byteOffset += delta`
   - `buffer.byteLength` 也要 += delta
5. 更新 `images[i].mimeType` 如果格式改變（jpeg → png 等）

vrm_io.py 的 `replace_image()` 已封裝以上邏輯。

---

## VRM extension 區塊保留策略

pygltflib 不認識 `VRM` 這個 extension key — 但會**完整保留**它在 `gltf.extensions["VRM"]` 中作為 dict。

只要我們不去動：
- `extensions.VRM.meta` (作者資訊)
- `extensions.VRM.humanoid.humanBones` (骨骼 mapping)
- `extensions.VRM.blendShapeMaster.blendShapeGroups` (表情)
- `extensions.VRM.secondaryAnimation.boneGroups` (SpringBone)

這些就會 byte-perfect 保留。MVP1 的所有操作都只動 images / bufferViews，不碰這些區塊。

---

## VRoid 標準 image 名稱

VRoid 匯出的 VRM 通常包含這些 image entries（順序視 VRoid 版本可能不同）：

| 可能名稱 | 對應部位 | 我們關心？ |
|---|---|---|
| `FaceMouth_(Instance)` 或 `FaceSkin` | 臉部主紋理 | ✅ Stage 3 替換 |
| `FaceEye` 或 `EyeIris` | 虹膜 | ✅ Stage 3 recolor |
| `FaceEyeline` 或 `EyeExtra_01_EyeLine` | 眼線 | ❌ 保留 |
| `FaceEyelash` | 睫毛 | ❌ 保留 |
| `FaceBrow` 或 `Eyebrow` | 眉毛 | ❌ 保留（之後可染色） |
| `Hair001`, `Hair_main`, `Hair_HairFace_(Instance)` | 頭髮 | ✅ Stage 3 recolor |
| `BodyA_(Instance)` 或 `Body` | 身體主紋理 | ❌ 保留 |
| `Tops`, `Bottoms`, `Shoes` | 服飾 | ❌ MVP1 保留；MVP3 換色 |

---

## texture_atlas.py 對應策略

每個 base 模型（AvatarSample_A/B/C/...）的 image 順序不同。我們維護一張 manual mapping：

```python
_ATLAS_MAPS = {
    "AvatarSample_A": AtlasMap(face_skin_index=0, hair_index=1, eye_iris_index=2),
    # 之後新增 base 模型時，跑 vrm.list_images() 確認 index
}
```

D01 ticket 完成後（實際下載 base VRM），才能填正確 index。
**fallback 機制：** `auto_detect_atlas()` 用 image.name 字串猜測。

---

## 同步建議

加新 base 模型 base_models/X.vrm 時必須：
1. 跑一次 `python -c "from autovtuber.vrm.vrm_io import VRMFile; v=VRMFile.load('X.vrm'); print(v.list_images())"`
2. 把對應 index 加進 `texture_atlas.py` 的 `_ATLAS_MAPS`
3. 用 Blender 或 GIMP 製作對應的 `face_uv_template_X.json`（5 個關鍵點 + alpha mask PNG）
4. 在 `LICENSES.md` 註明授權
5. 在 `DOWNLOAD_MANIFEST.md` 加 row（含 SHA-256）
