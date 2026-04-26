# 📜 第三方授權清單

> AutoVtuber 玩票為主，未來不排除商業化。本檔案追蹤所有外部資產與模型的授權狀態。
> **「商用模式」** UI 設定勾選後，凡是「商用 OK」欄位非 ✅ 的項目都會被自動隱藏。

---

## 🤖 AI 模型權重

| 名稱 | 來源 | 授權 | 商用 OK | 備註 |
|---|---|---|---|---|
| Stable Diffusion XL 1.0 base | Stability AI / HF | CreativeML Open RAIL++-M | ✅ | 需保留模型卡與授權連結 |
| AnimagineXL 4.0 | cagliostrolab/animagine-xl-4.0 | Fair AI Public License 1.0-SD | ⚠️ 條件 OK | 需保留 attribution；衍生模型需同樣授權 |
| IP-Adapter Plus Face SDXL | h94/IP-Adapter | Apache 2.0 | ✅ | |
| CLIP ViT-H/14 (image encoder for IP-Adapter) | LAION / OpenCLIP | MIT | ✅ | |
| ~~InsightFace buffalo_l~~ | DeepInsight | Non-commercial only | N/A | **MVP1 不採用** — 改用 MediaPipe（商用 OK 且無需 MSVC 編譯）|
| MediaPipe Face Mesh | Google | Apache 2.0 | ✅ | 取代 InsightFace，CPU 跑、478 點 mesh、商用乾淨 |

---

## 🧱 Base VRM 模型（D01 研究結果，2026-04-26）

| 名稱 | 來源 | 授權 | 商用 OK | 備註 |
|---|---|---|---|---|
| AvatarSample_A.vrm | [madjin/vrm-samples/vroid/stable/](https://github.com/madjin/vrm-samples/tree/master/vroid/stable) (15.1 MB) | VRoid 「特定條件」 — 允許修改、再分發 | ⚠️ 個人 OK / 企業需 attribution | 來自 VRoid Studio 內建範本，著作權保留給 Pixiv；非 CC0 |
| AvatarSample_B.vrm | madjin/vrm-samples 同上 (15.4 MB) | 同上 | 同上 | |
| AvatarSample_C.vrm | madjin/vrm-samples 同上 (13.1 MB) | 同上 | 同上 | |
| ~~Seed-san.vrm~~ | madjin/vrm-samples/Seed-san/vrm/ (10.7 MB) | **CC0 1.0** | N/A | **MVP1 不採用** — 實機驗證為 VRM 1.0 格式，VSeeFace 不支援。MVP3 雙格式匯出時再啟用 |

> ⚠️ **VRoid 「特定條件」摘要**（依 [VRoid 官方 FAQ](https://vroid.pixiv.help/hc/en-us/articles/4402394424089)）：
> - 允許：修改、衍生、redistribute（含商用，個人）
> - 禁止：將模型直接以「VRoid 範本」名義販售、NSFW 用途、誹謗用途
> - **企業商用建議：** 包裝後在 about 頁面標註「Based on VRoid sample by Pixiv」
>
> 商用模式預設使用 Seed-san；非商用模式三個 AvatarSample 都可選。

---

## 🛠️ Python 套件（runtime 依賴）

| 套件 | 授權 | 商用 OK |
|---|---|---|
| PyTorch | BSD 3-Clause | ✅ |
| diffusers | Apache 2.0 | ✅ |
| transformers | Apache 2.0 | ✅ |
| PySide6 | LGPL 3 | ✅ |
| trimesh | MIT | ✅ |
| pygltflib | MIT | ✅ |
| Pillow | HPND | ✅ |
| opencv-python-headless | Apache 2.0 | ✅ |
| numpy | BSD 3-Clause | ✅ |
| onnxruntime | MIT | ✅ |
| pynvml | BSD 3-Clause | ✅ |
| psutil | BSD 3-Clause | ✅ |
| loguru | MIT | ✅ |
| pydantic | MIT | ✅ |
| requests | Apache 2.0 | ✅ |

---

## 🎨 內建資產（icons / fonts）

| 名稱 | 來源 | 授權 | 商用 OK |
|---|---|---|---|
| Lucide icons | lucide.dev | ISC | ✅ |
| Noto Sans CJK | Google Fonts | SIL OFL 1.1 | ✅ |

---

## 🛑 商用切換邏輯

`config.toml` 中：
```toml
[commercial]
mode = false   # 預設關閉
```

啟用後，UI：
- 隱藏「商用 OK」≠ ✅ 的 base model 與模型選項
- Setup wizard 跳過下載這些模型
- About 頁面顯示「商用模式啟用」徽章

---

## 異動規則

每次新增/移除外部資產，必須同時更新：
1. 本檔案
2. `docs/DOWNLOAD_MANIFEST.md`（如果是要下載的）
3. `AUTOVTUBER.md` 異動紀錄
