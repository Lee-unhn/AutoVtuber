# 📦 Download Manifest

> Setup Wizard 從本檔案讀取「要下載什麼」。
> 格式必須維持為下方表格 — `manifest.py` 用 regex 解析。

---

## 必須下載的模型（總計 ~10–12 GB）

| key | url | sha256 | size_mb | dest_relative |
|---|---|---|---|---|
| sdxl_animagine_4_unet | https://huggingface.co/cagliostrolab/animagine-xl-4.0/resolve/main/animagine-xl-4.0.safetensors | TBD_FILL_ON_FIRST_DOWNLOAD_64HEX_PLACEHOLDER_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | 6776 | sdxl/animagine-xl-4.0/animagine-xl-4.0.safetensors |
| ip_adapter_plus_face | https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus-face_sdxl_vit-h.bin | TBD_FILL_ON_FIRST_DOWNLOAD_64HEX_PLACEHOLDER_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb | 1009 | ip_adapter/ip-adapter-plus-face_sdxl_vit-h.bin |
| ip_adapter_image_encoder | https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors | TBD_FILL_ON_FIRST_DOWNLOAD_64HEX_PLACEHOLDER_cccccccccccccccccccccccccccccccccccccccc | 2528 | ip_adapter/image_encoder/model.safetensors |

> **注意：**
> - 上述 sha256 是 placeholder（64 個 hex 字元）。D01 ticket 會以「實機下載 → 計算 SHA-256 → 填入」流程取代。
> - URL 都指向 HuggingFace 公開 release，無需 token。
> - sizeMB 是**約**值，下載時實際大小可能 ±5%。

---

## Base VRM 模型（D01 完成 2026-04-26）

> ⚠️ 這些檔案直接放在 `assets/base_models/` 並已隨 setup wizard 內建，**不必重複下載**。
> 只在離線封裝失效時才透過 wizard 下載。SHA-256 在實機下載後填入 `manifest.lock.json`。

| key | url | sha256 | size_mb | dest_relative |
|---|---|---|---|---|
| base_model_avatar_sample_a | https://github.com/madjin/vrm-samples/raw/master/vroid/stable/AvatarSample_A.vrm | b86b0b8a66d48911431d6f920a5211a974226f83aa672eca3f3dfade58ac346e | 15 | base_models/AvatarSample_A.vrm |
| base_model_avatar_sample_b | https://github.com/madjin/vrm-samples/raw/master/vroid/stable/AvatarSample_B.vrm | 4a271bd3b5a3d19e054fd113ee154635b72e7141f4a8ccbcdba3c7f9cea6ee8d | 15 | base_models/AvatarSample_B.vrm |
| base_model_avatar_sample_c | https://github.com/madjin/vrm-samples/raw/master/vroid/stable/AvatarSample_C.vrm | 395d5b04696e888f07bc856ae01bf72a974b7e773132c7443dc59d1688045b8a | 13 | base_models/AvatarSample_C.vrm |
| ~~base_model_seed_san~~ | ~~https://raw.githubusercontent.com/madjin/vrm-samples/master/Seed-san/vrm/Seed-san.vrm~~ | ~~d24a5473a53f5ab76228da7c49a3f6fc2e1a0561566123859311df1e40b26490~~ | ~~11~~ | ~~base_models/Seed-san.vrm~~ |

> **⚠️ 2026-04-26 實機驗證後發現：** Seed-san.vrm 是 **VRM 1.0** 格式（`VRMC_vrm` extension），且 image atlas 結構完全不同（hair / wear / faceparts 等 15 張，非 VRoid 風格）。**VSeeFace 不支援 VRM 1.0** → MVP1 不可用作為 base 模型。Seed-san 留作 MVP3 VRM 1.0 雙匯出時的研究素材。已從上方表格刪除。

> **特別注意：** dest_relative 對於 base 模型是 `base_models/` 相對於 `assets/` 的路徑（不是 `models/`）。
> Setup wizard 程式碼需相應處理 — manifest.py 解析時會帶這個 prefix。
>
> SHA-256 真實值在 `assets/base_models/manifest.lock.json` 寫入。第一次下載成功後 setup wizard 自動產生。
