# 🔄 接續筆記 — Session 6 結束（2026-04-27）

> 給下次 session 直接接續用。這份是最新狀態（2026-04-27 晚上）

---

## 🎯 一句話狀態

**MVP1 + 2 + 3 + MVP4-α 全部完成，pytest 139 全綠，GitHub 14 commits 推完，主旨完成度 9.5/10。等使用者實機驗收 Sprint MVP4-α 三項升級的效果。**

---

## 📊 完整進度

| Phase | 狀態 | 備註 |
|---|---|---|
| MVP1 表單→.vrm | ✅ 100% | persona + recolor + assemble |
| MVP2 image-to-3D + tint | ✅ 100% | Evidence Collector 8.5/10 PASS |
| MVP3 體驗精修（6 項）| ✅ 100% | Wizard / Webcam / Multi-base / Preset / RefPhoto / PyInstaller |
| MVP4-α 主旨對齊 ROI（3 項）| ✅ 100% | R2 預覽循環 / R3 色彩嚴守 / R1 ARKit Perfect Sync |

---

## 🚨 當前等待中：使用者實機驗收

**使用者要做**（路線 A — 最高優先）：

```powershell
# 1. 開另一個 terminal 跑 Ollama
ollama serve

# 2. 主 terminal
cd C:\avt
echo 1 > setup_complete.flag    # 跳過 wizard（環境已就緒）
.\venv\Scripts\activate
python -m autovtuber
```

GUI 開啟後，依序試：
1. **🎨 預覽概念圖**（R2 驗收）— 5 min 出概念圖，看髮色對不對（R3 驗收）
2. **✨ 完成 V皮**（用 cached concept，30 秒組裝）
3. **Warudo 載入 .vrm**（R1 驗收）→ 看 Perfect Sync 67 個 blendshape clips（15 VRoid + 52 ARKit）

驗收完告訴我結果，我再決定下一步。

---

## 📂 GitHub 狀態（最終版）

**Repo**: https://github.com/Lee-unhn/AutoVtuber (private)

**最新 14 個 commits**（最新在上）：
```
ef9ddec docs: Sprint MVP4-α 完成總結
91308ea R1: Perfect Sync 52 ARKit blendshape export
e3b7b9b R3: SDXL hair/eye HSV-based 嚴守度
56d3dba R2: SDXL 概念圖預覽 + 微調循環
c6dce80 docs: 同步 MVP3 完成狀態
810e2be docs: MVP3 全部完成總結
06967ec M3-6: PyInstaller spec
3cdd710 M3-2: Webcam 即時臉部追蹤
efafbc3 M3-3: Reference Photo wiring
bdeac87 M3-5: Preset 系統 import/export
8f053ea M3-4: 表單加 Base VRM 模型選單
6772c0d M3-1: Setup Wizard 自動化下載
5615220 AutoVtuber MVP1+MVP2 complete
```

---

## 🛠 環境設定（重要！下次 session 沿用）

### Always-allow（已設）
`C:\avt\.claude\settings.local.json` 已設 `permissions.defaultMode = "bypassPermissions"` — **下次 session 自動繼承**，所有工具不再 ask。

### Auto-advance 機制（已停）
- 5h cron `5d9b0212` — **CronDelete 已執行**
- 10min ScheduleWakeup — session-only，session 結束自動消失

### 環境就緒確認
- ✅ Ollama 模型：gemma4:e2b（SDXL prompt）/ qwen2.5:3b（persona）
- ✅ SDXL: `C:\avt\models\sdxl\animagine-xl-4.0\` 6.5GB
- ✅ TripoSR: `C:\avt\external\TripoSR\` + HF cache 1.7GB
- ✅ rembg u2net: `C:\Users\user\.u2net\u2net.onnx` 176MB
- ❌ IP-Adapter image_encoder（缺檔，已知問題，不擋 pipeline）

---

## 📜 下次 session 第一件事

**等使用者回報實機驗收結果**：

如果使用者已驗收：
- 順利 → 看路線 B（PyInstaller / 對外 release）或路線 C（O1/O3/O4 繼續優化）
- 不順 → 修反饋的具體問題

如果還沒驗收：
- 提醒使用者跑 GUI（指令在 WAKE_UP_NOTES.md 上方）
- 不要自動加新功能（避免跟反饋衝突）

---

## 🎯 三條備選路線（使用者決定）

### 路線 A — 先驗收（推薦中）
- 30 min 實機跑 + 30 min Warudo 試 Perfect Sync
- 我等反饋再決策

### 路線 B — 對外發佈（如果想分享）
- PyInstaller 實機 build (10-30 min)
- README 加截圖（VSeeFace + GUI 表單）
- repo 從 private 改 public + release notes
- ~1 天工時

### 路線 C — 繼續優化
| 任務 | 工時 | 對齊度 |
|---|---|---|
| R3 方案 C post-process redo | 1-2 天 | ⭐⭐ 安全網 |
| O3 subprocess 隔離 GUI / ML | 3-5 天 | ⭐⭐ 預防穩定度 |
| O4 CharacterGen 替換 TripoSR | 1 週 | ⭐⭐ 解 anime geometry |
| O1 MediaPipe Blendshape V2 | 1-2 天 | ⭐ webcam tracker |
| O5 UniRig 自動 rigging | 1-2 週 | ⭐ 主旨外 |
| 小債清理（face_baker 真刪 / Pillow 13）| 0.5 天 | – |

---

## 📁 關鍵路徑（給下次 session 快速定位）

```
C:\avt\
├── AUTOVTUBER.md                # 主規格 + 異動全紀錄
├── README.md                    # 對外文件（含 Sprint MVP4-α 章節）
├── WAKE_UP_NOTES.md             # ← 這份
├── docs\MVP3_PLAN.md            # MVP3 完成總結
├── docs\BUILDING.md             # PyInstaller 打包指南
├── docs\architecture.md         # 套件職責表（含 setup / face_tracker）
├── .claude\settings.local.json  # Always-allow（個人設定，不上 git）
├── output\character_*.vrm       # 3 個產出 .vrm 樣本
└── src\autovtuber\
    ├── pipeline\
    │   ├── orchestrator.py      # run_concept + run_full_from_concept + run
    │   ├── prompt_builder.py    # R3 HSV-based color tag
    │   ├── persona_generator.py # qwen2.5:3b override + force unload
    │   ├── image_to_3d.py       # TripoSR wrapper + rembg
    │   ├── mesh_fitter.py       # LAB tint mode (8.5/10 PASS)
    │   ├── face_tracker.py      # mediapipe → 12 VRM blendshape weight
    │   └── vrm_assembler.py     # 整合 + R1 ARKit clips
    ├── vrm\
    │   ├── vrm_io.py            # pygltflib wrapper
    │   ├── texture_atlas.py     # AvatarSample_A/B/C atlas index
    │   └── blendshape_writer.py # R1 52 ARKit Perfect Sync (新)
    ├── workers\
    │   ├── job_worker.py        # 完整 e2e
    │   ├── concept_worker.py    # R2 拆兩段（新）
    │   ├── face_tracker_worker.py
    │   └── setup_worker.py
    ├── ui\
    │   ├── form_panel.py        # R2 三按鈕（🎨/✨/💨）
    │   ├── main_window.py
    │   ├── face_tracker_dialog.py
    │   └── setup_wizard.py
    └── setup\
        ├── resource_check.py    # 11 項偵測
        └── downloader.py        # HF/git/Ollama 多來源
```

---

## 🧪 測試覆蓋

```
99 → 139 全綠（Sprint MVP4-α 加 +40）
- test_orchestrator_split.py     (4)  R2
- test_color_tag_hsv.py          (24) R3
- test_arkit_blendshape_writer.py (12) R1
+ 既有 99 個 (MVP1-3)
```

---

## ⚠️ 已知小問題（不阻塞，留給後續修）

1. **gemma4:e2b / qwen2.5:3b 偶爾掉 persona 章節** → template fallback 接住
2. **暗色 hex 邊界 case**（已用 HSV 修主要的，但極端值可能還是會落 brown）
3. **AvatarSample_B 的 face_skin atlas 較深，tint mask 較嚴**（5463 vs A 的 791578 pixels）
4. **IP-Adapter image_encoder 缺檔** → MVP3 setup wizard 可補下載
5. **Pillow 13 deprecation warning**（mode= 參數）→ 還沒到時間
6. **face_baker.py + face_aligner.py 標 deprecated 但還沒刪** → 偷懶債
7. **PyInstaller spec 沒實機 build 過** → user 想 ship 時要跑

---

## 💬 第一句指令範例（給下次 session）

> 「我已經實機跑過 GUI，發現 [X] 問題，幫我修」
> 或：「都順，幫我做路線 B 對外發佈」
> 或：「先優化 O3 subprocess 隔離」
> 或：「就這樣，可以收工」

讀完這份你應該完整接得上。歡迎回來 🌙
