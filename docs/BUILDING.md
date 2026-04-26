# 打包成 Windows 可執行檔

> 從 source 打包成 `dist/AutoVtuber/AutoVtuber.exe` — 使用者下載 zip 解壓後雙擊即可跑。

## 前置

```powershell
cd C:\avt  # 或你的專案路徑
venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
```

## 打包

```powershell
pyinstaller autovtuber.spec --clean --noconfirm
```

成品在 `dist/AutoVtuber/`，~2-3 GB。雙擊 `AutoVtuber.exe` 啟動。

> ⚠️ **重要**：dist/ 內**不含**大型 ML 權重（SDXL 6.5GB / IP-Adapter 3.3GB / TripoSR 1.7GB）。
> 使用者第一次啟動 → Setup Wizard 自動下載這些（總計 ~12 GB）到 `models/`。

## 為什麼選 --onedir 而不是 --onefile

- ML 套件（diffusers / mediapipe / pyrender）有大量 binary deps + 資源檔
- onefile 啟動時要解壓全部到 temp，開機冷啟動 30+ 秒
- onedir 啟動 < 5 秒，且能保留 setup wizard 下載的 models/ 跨啟動

## 已知打包陷阱

| 套件 | 陷阱 | 解法 (已在 spec 處理) |
|---|---|---|
| `mediapipe` | binary tflite 模型必須複製到 `_MEIPASS/mediapipe/modules/` | `collect_all("mediapipe")` |
| `cv2` (opencv-python-headless) | DLL 在 `cv2/.libs/` 必須帶 | `collect_dynamic_libs("cv2")` |
| `onnxruntime` | 同上 + provider 動態載入 | `collect_all("onnxruntime")` |
| `pyrender` | 預設用 PyOpenGL；plugin 抓不到 | `collect_all("pyrender")` + `collect_all("OpenGL")` |
| `PySide6` | Qt platforms plugin 找不到會 launch 後黑窗 | `collect_all("PySide6")` |
| `external/TripoSR` | 不在 site-packages，PyInstaller 不會自動帶 | spec 手動 datas 加 |
| `numba` LLVM 動態編譯 | runtime cache 會掉 | `collect_all("numba")` |

## Smoke 驗證

```powershell
cd dist\AutoVtuber
.\AutoVtuber.exe
```

期待行為：
1. 主視窗啟動 < 10 秒
2. 若 `setup_complete.flag` 不存在 → Setup Wizard 自動跳出
3. 點 **資源偵測** → 11 項全 missing（因為 models/ 空）
4. 點 **開始下載** → 開始抓 SDXL/IP-Adapter/TripoSR/Ollama 模型
5. 完成後關閉 wizard → 主介面可用

## 之後優化（不在 MVP3 範圍）

- `.ico` 自訂圖示
- 程式碼簽署（避 SmartScreen 警告）
- NSIS / Inno Setup 包成 installer.exe
- delta updater（只抓有變的檔）
