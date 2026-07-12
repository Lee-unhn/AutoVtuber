# Windows VTuber Acceptance Checklist

> 更新日期：2026-05-28
> 目的：在目標 Windows / NVIDIA 電腦上驗證 AutoVtuber 真的能產出「人類意義上的 VTuber」，並可交給 VDrama 做短影片。

## 前置條件

- Windows 11
- NVIDIA GPU，建議 VRAM 10 GB 以上
- Python 3.12
- 已完成 `config.toml`
- 已註冊合法 VRM 0.x base
- 不使用 AvatarSample A/B/C 作產品輸出

## 1. 程式測試

```powershell
pytest
```

接受條件：

- 單元測試全通過，或只出現已知平台限制且有紀錄。
- `tests/test_asset_policy.py` 必須通過，確保未授權 base 不會被放行。
- `tests/test_vtuber_quality.py` 必須通過。

## 2. 合法 base 檢查

```powershell
python scripts\validate_vrm_base.py --source C:\path\to\OwnedBase.vrm --out docs\evidence\OwnedBase_base_validation.md
python scripts\inspect_vrm_atlas.py --source C:\path\to\OwnedBase.vrm --out docs\evidence\OwnedBase_atlas_inspect.md
python scripts\register_authorized_base.py --source C:\path\to\OwnedBase.vrm --model-id OwnedBase --display-name "Owned Base" --license-reference docs\evidence\OwnedBase_license.md --face-skin-index <index> --hair-index <index> --eye-iris-index <index> --confirm-rights
```

接受條件：

- `assets/base_models/OwnedBase.vrm` 存在。
- `assets/base_models/approved_models.json` 存在。
- AutoVtuber UI 下拉選單出現該 base。

## 3. 完整生成

在 GUI 填寫一個角色：

- 暱稱
- 髮色
- 眼色
- 風格
- 個性
- 角色描述
- 合法 base

接受條件：

- 產出 `.vrm`
- 產出 persona markdown
- 產出概念圖
- `VtuberQualityGate` pass
- 未觸發 HardwareGuard abort

## 4. 截圖留存

至少保存：

- 正面
- 背面
- 左側
- 右側
- 上方
- 下方
- 斜角
- 臉部近景

建議使用既有腳本：

```powershell
python scripts\render_vrm_six_views.py --input output\<character>.vrm --out docs\images\<character>_six_views.png
```

## 5. VSeeFace / Warudo 檢查

接受條件：

- VRM 可載入
- 模型站姿正常
- 材質沒有明顯錯貼
- 眨眼正常
- `A/I/U/E/O` 嘴型正常
- 基本情緒表情可觸發
- 頭部、肩膀、手臂動作沒有嚴重破面

## 6. VDrama 交接

填寫：

```text
handoff/AUTOVTUBER_EXPORT_<character_id>_<YYYYMMDD>.md
```

VDrama 回覆：

```text
handoff/VDRAMA_FEEDBACK_<character_id>_<YYYYMMDD>.md
```

第一個角色必須完成一次 AutoVtuber -> VDrama -> 回饋閉環，才可標記 v1 release-ready。
