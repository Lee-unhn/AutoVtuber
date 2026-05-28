# AutoVtuber Release Readiness

> 更新日期：2026-05-27  
> 目標：將已可生成的 VTuber Beta 收斂成可發佈、可驗收且不誤導授權狀態的版本。

## 目前判定

| 項目 | 狀態 | 證據 / 說明 |
|---|---|---|
| VRM 組裝與結構品質 | PASS | `VtuberQualityGate`；納入 2026-05-27 全測試重驗 |
| ARKit / Perfect Sync clips | PASS | 已驗證 52 clips，納入 quality gate |
| HardwareGuard 磁碟監控路徑 | FIXED | 不再硬寫 `G:\`，主程式與 smoke tests 改為監控實際 `output/` 路徑 |
| 本機單元測試重驗 | PASS WITH PLATFORM SKIP | 2026-05-27：`154 passed, 1 skipped`；skip 為 macOS headless MediaPipe OpenGL 初始化，留待 Windows GUI 實機驗收 |
| GUI / Setup Wizard / Preset / Webcam 程式碼 | IMPLEMENTED | 尚需在 Windows 目標機整合驗收 |
| Base VRM 發佈授權 | BLOCKED | AvatarSample A/B/C 官方條款禁止用於角色建立服務的產品 base |
| 程式碼授權標示 | BLOCKED | `pyproject.toml` 保留待定狀態；專案所有者需決定正式 LICENSE |
| PyInstaller Windows 成品 | PENDING | 目前僅有 `autovtuber.spec` 與打包文件，未保存實機 build 驗收紀錄 |
| Warudo / VSeeFace 最終動作驗收 | PENDING | 必須在目標 Windows 電腦載入最終合法 base 產物驗收 |
| VDrama Markdown 交接 | READY | 已建立 `docs/VDRAMA_MARKDOWN_HANDOFF.md` 與 `handoff/` 交付/回饋模板；另一台電腦只需讀寫 Markdown |
| Base 準備工具 | READY | 已建立 `scripts/validate_vrm_base.py`、`scripts/inspect_vrm_atlas.py`、`scripts/register_authorized_base.py` 與 `docs/BASE_VRM_PREP_PACKET.md` |

## 依重要性執行順序

### P0 - 發佈授權阻擋

- [x] 停止將 AvatarSample A/B/C 描述為 CC0 或可作商業產品 base。
- [x] 預設與 `commercial.mode=true` 時，UI、Setup Wizard 與 VRM assembly 阻擋未放行 sample base；舊研究重現必須明確開啟 validation 設定。
- [x] 提供 `scripts/register_authorized_base.py` 與本機 `approved_models.json` 權利註冊流程，合法底模註冊後可被 UI 與 pipeline 識別。
- [x] 提供 `scripts/validate_vrm_base.py` 檢查候選 VRM 是否具備 VTuber base 結構。
- [x] 提供 `scripts/inspect_vrm_atlas.py` 產生 atlas index 檢查報告。
- [ ] 建立或取得可用於角色建立產品的合法 VRM 0.x base model。
- [ ] 為新 base 建立 texture atlas mapping、預覽與 license record。
- [ ] 專案所有者決定程式碼正式授權並加入 LICENSE。

### P1 - 可重現品質驗證

- [x] 建立 VTuber structural quality gate。
- [x] 保存六視角與斜角幾何預覽。
- [x] 在目前可用的 macOS verifier 重跑全測試：`154 passed, 1 skipped`。
- [ ] 在目標 Windows + NVIDIA 環境重跑完整 test suite。
- [ ] 使用合法 base 跑一次完整 SDXL -> TripoSR -> VRM e2e 並保存成果。

### P2 - 桌面發佈

- [ ] 在 Windows 實際執行 PyInstaller build。
- [ ] 從乾淨目錄啟動 `.exe`，驗證 Setup Wizard、模型偵測與下載。
- [ ] 確認 GUI 預覽、preset import/export 與 webcam tracker。
- [ ] 依 `docs/WINDOWS_VTUBER_ACCEPTANCE.md` 保存驗收紀錄。

### P3 - 人類意義上的 VTuber 驗收

- [ ] 將合法 base 產出的 `.vrm` 載入 Warudo 或 VSeeFace。
- [ ] 檢查頭身、材質、眨眼、嘴型、表情與 Perfect Sync。
- [ ] 留存截圖、影片與問題回報，通過後才能標記 v1 release-ready。

### P4 - VDrama 跨電腦交接

- [x] 建立 AutoVtuber / VDrama Markdown 交接規格。
- [x] 建立 AutoVtuber 角色交付模板與 VDrama 回饋模板。
- [x] 寫下給另一台電腦的協作訊息。
- [ ] 第一個合法角色產出後，填寫 `handoff/AUTOVTUBER_EXPORT_<character_id>_<YYYYMMDD>.md`。
- [ ] VDrama 測試後回填 `handoff/VDRAMA_FEEDBACK_<character_id>_<YYYYMMDD>.md`。

## 當前最短路徑

合法底模的受控匯入機制已完成，操作見 [`AUTHORIZED_BASE_IMPORT.md`](./AUTHORIZED_BASE_IMPORT.md)。下一個必要輸入是**合法可發布的 base VRM 本體及其授權依據**；沒有它，即使 pipeline、`.exe` 與口型功能都完成，也不能把角色生成產品交付出去。

建議來源：

1. 由專案所有者使用 VRoid Studio 建立自有 base，確認所用衣物與素材允許預定用途。
2. 委託建立一份契約明確允許用於自動角色生成服務的 VRM 0.x base。
3. 取得書面授權後，將 license evidence 與模型雜湊記錄在 `docs/LICENSES.md`。

## 官方依據

- [VRoid commercial use FAQ](https://vroid.pixiv.help/hc/en-us/articles/4402394424089)
- [AvatarSample_A Terms of Use](https://vroid.pixiv.help/hc/en-us/articles/360000227322)
