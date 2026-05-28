# AUTOVTUBER_EXPORT_<character_id>_<YYYYMMDD>

> 狀態：draft  
> 來源專案：AutoVtuber  
> 目標專案：VDrama  
> 二進位資產另行傳遞，不提交 GitHub。

## 角色識別

| 欄位 | 內容 |
|---|---|
| Character ID | `<character_id>` |
| 顯示名稱 | `<display_name>` |
| 風格 | `<style>` |
| 預期年齡形象 | `<young adult / adult / senior / other>` |
| 預期聲音形象 | `<female / male / neutral / young / mature / calm / energetic>` |
| 角色定位 | `<host / narrator / news reader / drama actor / other>` |

## 交付檔案

| 類型 | 檔名或位置 | SHA-256 / 版本 | 備註 |
|---|---|---|---|
| VRM | `<character>.vrm` | `<sha256>` | 另行傳遞 |
| Persona | `<character>_persona.md` | `<sha256>` | 可提交或另行傳遞 |
| 概念圖 | `<character>_concept.png` | `<sha256>` | 另行傳遞 |
| 預覽圖 | `<character>_six_views.png` | `<sha256>` | 正/背/左/右/上/下 |
| 額外圖 | `<character>_angle_views.png` | `<sha256>` | 斜角或臉部細節 |

## VRM 契約

| 項目 | 數值 |
|---|---:|
| VRM 版本 | `0.x` |
| Humanoid bones | `<count>` |
| Blendshape clips | `<count>` |
| ARKit / Perfect Sync clips | `<count>` |
| Skinned meshes | `<count>` |
| Morph targets | `<count>` |
| 必要嘴型 | `A / I / U / E / O` |
| 必要表情 | `blink / joy / angry / sorrow / fun` |

## 演出說明

- 人格：
- 說話風格：
- 適合情緒：
- 不適合動作：
- VDrama 導演注意事項：

## 授權狀態

| 項目 | 狀態 |
|---|---|
| Base model | `<owned / licensed / blocked>` |
| License reference | `<document / contract / receipt / internal record>` |
| 商業交付 | `<allowed / blocked / pending>` |
| 標示要求 | `<none / attribution text>` |

> 未填入合法 base 與授權依據前，本角色不得標示為可商業交付。

## AutoVtuber 驗證紀錄

| 檢查 | 結果 |
|---|---|
| VtuberQualityGate | `<pass / fail>` |
| 測試日期 | `<YYYY-MM-DD>` |
| 測試環境 | `<OS / GPU / Python>` |
| 已知限制 | `<none / details>` |

## VDrama 回饋期待

請 VDrama 另一台電腦回傳：

```text
handoff/VDRAMA_FEEDBACK_<character_id>_<YYYYMMDD>.md
```

回饋需包含匯入結果、視覺截圖、語音/TTS 聲線、viseme 覆蓋率、動作 retargeting 結果與核准狀態。
