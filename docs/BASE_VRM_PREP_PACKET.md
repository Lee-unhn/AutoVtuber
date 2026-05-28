# Base VRM Preparation Packet

> 更新日期：2026-05-28
> 目的：讓這台 AutoVtuber 電腦、另一台 VDrama 電腦、或人工製作端都知道要準備哪些東西，才能把一份合法 VRM 0.x base 變成可生成角色的產品底模。

## 能不能由 AutoVtuber 自己生成 VRM？

可以，但要精確理解「生成」的意思。

AutoVtuber 目前能做的是：

1. 讀取一份已經有 humanoid bones、skinning、blendshape、材質 atlas 的合法 VRM 0.x base。
2. 根據表單與 SDXL/TripoSR 結果，自動改髮色、眼色、膚色與人設文字。
3. 加上 ARKit / Perfect Sync clips，跑 `VtuberQualityGate`，輸出新的 `.vrm`。

AutoVtuber 目前不做的是：

1. 從零建一個商用品質 humanoid skeleton。
2. 從零 skinning 權重、拓撲、blendshape、材質 UV atlas。
3. 從零保證 VSeeFace / Warudo / VDrama 都可自然演出。

所以現階段正確產品路線是：**合法 base VRM -> AutoVtuber 自動生成新角色 VRM -> VDrama 演出短片**。

## 需要提供的輸入

| 項目 | 必填 | 說明 |
|---|---|---|
| VRM 0.x 檔案 | 是 | `.vrm`，需已可在 VSeeFace 或 Warudo 載入 |
| 授權依據 | 是 | 自製紀錄、委託合約、素材購買證明或內部授權紀錄 |
| 使用範圍 | 是 | 必須明確允許用於角色建立服務與產出角色交付 |
| 顯示名稱 | 是 | UI 下拉選單顯示 |
| model id | 是 | 英數底線或連字號，例如 `OwnedBaseF01` |
| atlas index | 是 | `face_skin_index`、`hair_index`、`eye_iris_index`，可選 `eye_white_index` |

## 準備流程

1. 將合法 `.vrm` 放在本機任一位置。
2. 先做技術可用性檢查：

```bash
PYTHONPATH=src python scripts/validate_vrm_base.py \
  --source /path/to/OwnedBase.vrm \
  --out docs/evidence/OwnedBaseF01_base_validation.md
```

3. 產生 atlas 檢查報告：

```bash
PYTHONPATH=src python scripts/inspect_vrm_atlas.py \
  --source /path/to/OwnedBase.vrm \
  --model-id OwnedBaseF01 \
  --out docs/evidence/OwnedBaseF01_atlas_inspect.md
```

4. 打開報告，確認哪幾個 image index 是臉、髮、虹膜、眼白。
5. 登錄合法 base：

```bash
PYTHONPATH=src python scripts/register_authorized_base.py \
  --source /path/to/OwnedBase.vrm \
  --model-id OwnedBaseF01 \
  --display-name "Owned Base F01" \
  --license-reference "docs/evidence/OwnedBaseF01_license.md" \
  --face-skin-index <index> \
  --hair-index <index> \
  --eye-iris-index <index> \
  --eye-white-index <index-or-omit> \
  --confirm-rights
```

6. 啟動 AutoVtuber，確認該 base 出現在表單下拉選單。
7. 跑第一個角色生成，產出 `.vrm`、persona、概念圖與預覽圖。
8. 填寫 `handoff/AUTOVTUBER_EXPORT_<character_id>_<YYYYMMDD>.md` 給 VDrama。

## 不可接受的 base

- 只知道「網路免費」但無授權依據。
- VRoid AvatarSample A/B/C 作為產品 base。
- VRM 1.0，除非先改 AutoVtuber pipeline 支援。
- 不能確認素材、衣服、髮型、配件是否允許再交付或商業使用。
- 沒有 blendshape 或 humanoid bones 的展示模型。

## 給另一台電腦

VDrama 不需要知道 atlas index，也不需要修改 base。VDrama 只需要等待 AutoVtuber 交付：

```text
handoff/AUTOVTUBER_EXPORT_<character_id>_<YYYYMMDD>.md
<character>.vrm
<character>_persona.md
<character>_concept.png
<character>_six_views.png
```

若 VDrama 發現嘴型、表情或動作問題，請回覆：

```text
handoff/VDRAMA_FEEDBACK_<character_id>_<YYYYMMDD>.md
```
