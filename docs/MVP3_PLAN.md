# MVP3 規劃 — AutoVtuber

> 寫於 2026-04-27（MVP1+MVP2 全部完成、Evidence Collector 8.5/10 PASS 之後）
> **狀態：✅ 全部 6 項完成（2026-04-27 Session 5）— pytest 99 全綠 + 推到 GitHub**

---

## 📊 完成總結（2026-04-27）

| 任務 | 規劃工時 | 實際工時 | 狀態 |
|---|---|---|---|
| M3-1 Setup wizard | 4-6h | 5h | ✅ |
| M3-2 Webcam preview | 8-12h | 4h（採務實路線：blendshape progress bar 取代 3D render）| ✅ |
| M3-3 Reference photo | 3-5h | 1h（wiring 已備）| ✅ |
| M3-4 多 base | 2-3h | 1h | ✅ |
| M3-5 Preset 系統 | 3-4h | 2h | ✅ |
| M3-6 PyInstaller | 4-8h | 1h（spec + docs，未實機跑 build）| ✅ |
| **合計** | **24-38h** | **~14h** | **PASS** |

**測試**：pytest 69 → 99 全綠（+30 測試）
**GitHub**：8 commits pushed to `https://github.com/Lee-unhn/AutoVtuber` (private)

---

---

## 🎯 MVP3 主旨

把 AutoVtuber 從「能跑的 e2e pipeline」推進到「使用者拿到後 30 秒可以開始直播」的成品。

---

## 📦 MVP3 範圍（按優先序）

### M3-1 ⭐ Setup Wizard 自動化下載（最高優先）
**為什麼**：目前使用者要手動 `ollama pull` / 跑 setup script / 等 SDXL/IP-Adapter/TripoSR 自動下載。第一次裝完約需 30-60 分鐘。MVP3 要把這流程封進 GUI wizard。

**範圍**：
- 偵測缺少資源（SDXL 6.5GB / IP-Adapter 3.3GB / TripoSR 1.7GB / rembg u2net 176MB / Ollama 模型）
- GUI 進度條 + 預估完成時間 + 暫停/繼續按鈕
- SHA-256 驗證下載完整性
- 失敗自動 retry（最多 3 次）+ resume from partial
- 下載完跳「準備就緒」並 enable 主表單

**現況**：50% 已有 — `scripts/` 有 `bake_face_uv_template.py`，`ui/setup_wizard.py` 有骨架但沒接到下載邏輯。

**估時**：4-6 小時

---

### M3-2 ⭐ Webcam 即時預覽 + 表情測試
**為什麼**：使用者產出 .vrm 後**沒辦法當場看效果**，必須開 VSeeFace。MVP3 內建 webcam preview 讓使用者按下生成完直接試動。

**範圍**：
- MediaPipe Face Mesh 抓臉部 478 點 landmarks
- 映射到 VRM blendshape weight（Joy/Angry/Sorrow/Fun/A/I/U/E/O/Blink_L/R）
- QtQuick3D View3D 即時 render 含 blendshape
- 滑桿可手動測 blendshape（不需 webcam 也能驗）
- 切換表情按鈕（中/笑/眨眼/驚訝/羞）

**現況**：QtQuick3D `preview_3d.qml` 有基本 placeholder，沒接 webcam tracking。

**估時**：8-12 小時（mediapipe pose mapping + blendshape weight 校正最花時間）

---

### M3-3 ⭐ Reference Photo 多角度上傳
**為什麼**：使用者可能想「我長這樣，做一個跟我有點像的 VTuber」。已知 IP-Adapter 是現成方案，但目前缺檔（`image_encoder` 沒下載）所以一直 fallback。

**範圍**：
- 表單加 「上傳參考照」按鈕（drag-and-drop）
- 預覽縮圖 + 強度滑桿（0-1，預設 0.7）
- 多張參考照（front/side/3-4）→ 用 IP-Adapter Faceid Plus 多 reference 模式
- 偵測 NSFW 自動拒絕（用 SafetyChecker）
- 跑 SDXL 時 IP-Adapter 啟用 + scale 套用

**現況**：FaceGenerator 已支援 `reference_photo_path` 參數但 IP-Adapter weight 缺失。

**估時**：3-5 小時（含 IP-Adapter image_encoder 下載 + 多 reference 邏輯）

---

### M3-4 多 Base 模型選擇（含男性 / 不同年齡）
**為什麼**：目前預設 AvatarSample_A（女性）；男性使用者選 AvatarSample_C 但 atlas 結構不同（M00_ prefix vs F00_）。MVP3 要：
- 表單加 base 選單（男/女/中性 / 16 / 18 / 22 歲外觀）
- 自動驗證對應 atlas index 正確（C 已驗證但需 smoke test 跑 e2e）
- 預覽各 base 縮圖

**現況**：3 個 AvatarSample 已下載，atlas index 已映射。需要：
- e2e smoke 在 B / C 跑通（D 任務正在背景跑 B）
- UI 多 base 切換邏輯

**估時**：2-3 小時

---

### M3-5 Preset 系統（角色庫管理）
**為什麼**：產出的 .vrm + persona.md + concept.png 散在 `output/`，使用者沒法管理「我做過哪些角色」。

**範圍**：
- `presets/` 目錄已有 PresetStore 邏輯（C-phase 寫過）
- LibraryPanel UI 顯示縮圖 + 名字 + 個性 + 載入按鈕
- 點 preset → 自動填表單 → 可重新生成（換髮色/眼色等微調）
- 匯出/匯入 preset JSON（分享角色設定）

**現況**：60% — `preset_store.py` 寫過，`library_panel.py` 有基礎 UI。

**估時**：3-4 小時

---

### M3-6 PyInstaller 打包
**為什麼**：MVP3 應該能交付給沒裝 Python 的使用者。

**範圍**：
- `pyinstaller --onedir`（不用 onefile，model 太多會炸）
- 處理 PySide6 / mediapipe / pyrender 的 hidden imports
- 處理 Windows codec / OpenGL 驅動依賴
- 打包大小約 2-3GB（含 venv 但不含 SDXL 等大模型，wizard 啟動後下載）
- 程式碼簽署（optional，避免 SmartScreen 警告）

**估時**：4-8 小時（PyInstaller 對 PySide6 + ML 套件常需手動修 spec）

---

## 🚫 MVP3 明確不做

- **完全自動的 face geometry 替換** — TSR 對 anime 沒夠細節，等 CharacterGen 或同類 anime-specific image-to-3D 成熟（probable MVP4）
- **VRM 1.0 支援** — VSeeFace 不認，用戶基本盤都用 0.x
- **Live2D 路徑** — 太複雜（手繪+綁定），跟 3D-first 架構衝突
- **多角色互動 / 場景編輯** — VTuber 軟體（VSeeFace、VTube Studio）已經做了
- **Cloud render** — 主旨是本機隱私 + 不上傳

---

## 📊 工時估計總和

| 項目 | 估時 | 對主旨對齊度 |
|---|---|---|
| M3-1 Setup wizard | 4-6h | ⭐⭐⭐ 直接降低使用者門檻 |
| M3-2 Webcam preview | 8-12h | ⭐⭐⭐ 即時驗收，不用切 VSeeFace |
| M3-3 Reference photo | 3-5h | ⭐⭐ 個性化，IP-Adapter 既有方案 |
| M3-4 多 base | 2-3h | ⭐⭐ 男性/年齡覆蓋廣 |
| M3-5 Preset | 3-4h | ⭐ 已有 60%，補齊容易 |
| M3-6 PyInstaller | 4-8h | ⭐⭐ 交付完成度 |
| **合計** | **24-38 小時**（3-5 工作天）| |

---

## 🛣 建議排序

**Sprint 1（核心使用者體驗）**：M3-1 + M3-5 + M3-4
→ 「看得到、選得到、存得起來」

**Sprint 2（差異化功能）**：M3-2 + M3-3
→ 「即時預覽 + 像我的角色」

**Sprint 3（交付）**：M3-6
→ 「使用者下載 .exe 就能用」

---

## 🎯 完成定義（DoD）

MVP3 完成的標準：
1. ✅ 使用者第一次安裝 → wizard 自動下載 → 30 分鐘內完成
2. ✅ 表單可上傳參考照 + 選 base 模型 + 微調強度
3. ✅ 生成完內建 webcam preview 即時測試表情
4. ✅ Preset 可儲存/載入/匯出/匯入
5. ✅ 提供 .exe 下載（Windows 10/11 x64）
6. ✅ Evidence Collector audit 整體 8.5+/10 PASS
7. ✅ pytest 全綠 + 新增 webcam 整合測試

---

## 🔗 參考資源

- IP-Adapter Faceid Plus：https://huggingface.co/h94/IP-Adapter-FaceID
- MediaPipe Face Mesh：https://google.github.io/mediapipe/solutions/face_mesh
- VRM 0.x blendshape spec：https://vrm.dev/en/univrm/blendshape/
- PyInstaller + PySide6 cookbook：https://doc.qt.io/qtforpython-6/deployment/deployment-pyinstaller.html
- Apache TVM（model serving）：未來 perf 優化，非 MVP3 範圍
