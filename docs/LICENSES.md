# 📜 第三方授權清單

> AutoVtuber 玩票為主，未來不排除商業化。本檔案追蹤所有外部資產與模型的授權狀態。
> 預設模式與 **「商用模式」** 均不提供未放行的 base VRM，也不會由 Setup Wizard 自動下載；pipeline 亦會拒絕以其組裝產品輸出。僅有明確開啟的 legacy validation 設定可重現舊研究測試。

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
| AvatarSample_A.vrm | [madjin/vrm-samples/vroid/stable/](https://github.com/madjin/vrm-samples/tree/master/vroid/stable) (15.1 MB) | VRoid AvatarSample_A 條款 | ❌ 產品 base 不放行 | 官方條款禁止將 sample model 資料用於角色建立服務；僅保留既有本機結構驗證 |
| AvatarSample_B.vrm | madjin/vrm-samples 同上 (15.4 MB) | VRoid AvatarSample_B 條款 | ❌ 產品 base 不放行 | 同上 |
| AvatarSample_C.vrm | madjin/vrm-samples 同上 (13.1 MB) | VRoid AvatarSample_C 條款 | ❌ 產品 base 不放行 | 同上 |
| ~~Seed-san.vrm~~ | madjin/vrm-samples/Seed-san/vrm/ (10.7 MB) | **CC0 1.0** | N/A | **MVP1 不採用** — 實機驗證為 VRM 1.0 格式，VSeeFace 不支援。MVP3 雙格式匯出時再啟用 |

> ⚠️ **VRoid sample model 判定依據**：
> - 官方條款頁列出 AvatarSample_A/B/C 各自條款，並要求使用前確認模型條件：
>   [VRoid FAQ - Can I use VRoid Studio models or items for commercial purposes?](https://vroid.pixiv.help/hc/en-us/articles/4402394424089)
> - 官方 sample terms 將使用 sample model 資料開發角色建立服務列為禁止事項：
>   [AvatarSample_A Terms of Use](https://vroid.pixiv.help/hc/en-us/articles/360000227322)
> - 因此 AutoVtuber 發佈版本必須改用專案所有者自製或另行取得授權、且相容 VRM 0.x 的 base model。
>
> 目前沒有已內建且通過產品發佈審查的 base VRM。預設生成將保持阻擋，直到加入合規 base；既有研究測試可明確設定 `assets.allow_restricted_samples_for_validation=true` 後重現，且不得作產品輸出。
> 自有或另行獲准的 VRM 0.x 可使用 [`AUTHORIZED_BASE_IMPORT.md`](./AUTHORIZED_BASE_IMPORT.md) 的本機註冊流程加入；註冊表不代表法律審查替代品，授權證據仍須由所有者保存。

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

[assets]
allow_restricted_samples_for_validation = false  # 僅重現舊測試，不可作產品輸出
```

啟用後，UI：
- 隱藏未放行的 base model 選項
- Setup Wizard 跳過下載 AvatarSample A/B/C
- `VRMAssembler` 拒絕以未放行 base 組裝輸出

---

## 異動規則

每次新增/移除外部資產，必須同時更新：
1. 本檔案
2. `docs/DOWNLOAD_MANIFEST.md`（如果是要下載的）
3. `AUTOVTUBER.md` 異動紀錄
