# Authorized Base VRM Import

AutoVtuber 產品輸出必須使用你擁有權利，或已取得明確授權可供角色生成服務使用的 VRM 0.x base。`AvatarSample_A/B/C` 不可用作產品 base。

完整準備包見 [`BASE_VRM_PREP_PACKET.md`](./BASE_VRM_PREP_PACKET.md)。若還不知道 atlas index，先用 `scripts/inspect_vrm_atlas.py` 產生檢查報告。

## 匯入流程

1. 準備一份合法的 `.vrm` 檔案與可追溯的授權依據。
2. 依模型材質確認 `face_skin`、`hair`、`eye_iris` 與選用的 `eye_white` image index。
3. 若不確定 index，先從專案根目錄執行：

```bash
PYTHONPATH=src python scripts/inspect_vrm_atlas.py \
  --source /path/to/OwnedBase.vrm \
  --model-id OwnedBaseF \
  --out docs/evidence/OwnedBaseF_atlas_inspect.md
```

4. 確認 index 後註冊：

```bash
PYTHONPATH=src python scripts/register_authorized_base.py \
  --source /path/to/OwnedBase.vrm \
  --model-id OwnedBaseF \
  --display-name "Owned Base - Female" \
  --license-reference "docs/evidence/owned-base-license.pdf" \
  --face-skin-index 11 \
  --hair-index 20 \
  --eye-iris-index 9 \
  --eye-white-index 4 \
  --confirm-rights
```

工具會驗證檔案為 VRM 0.x、確認所填紋理索引可讀，將 VRM 複製到 `assets/base_models/`，並建立本機權利註冊表 `assets/base_models/approved_models.json`。兩者預設不提交至 Git。

註冊後，該底模才會出現在角色建立表單，並可通過 `VRMAssembler` 的資產政策檢查。授權證明是否適用於實際服務仍由專案所有者負責確認與保存。
