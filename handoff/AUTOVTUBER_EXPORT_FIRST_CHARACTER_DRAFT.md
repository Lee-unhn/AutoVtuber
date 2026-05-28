# AUTOVTUBER_EXPORT_FIRST_CHARACTER_DRAFT

> 狀態：draft / waiting for authorized base
> 來源專案：AutoVtuber
> 目標專案：VDrama
> 二進位資產另行傳遞，不提交 GitHub。

## 角色識別

| 欄位 | 內容 |
|---|---|
| Character ID | `first_character` |
| 顯示名稱 | `待命名` |
| 風格 | `semi_realistic / anime_modern pending` |
| 預期年齡形象 | `young adult` |
| 預期聲音形象 | `natural, calm, matching visual gender and age` |
| 角色定位 | `short video narrator / VDrama actor` |

## 交付檔案

| 類型 | 檔名或位置 | SHA-256 / 版本 | 備註 |
|---|---|---|---|
| VRM | `pending` | `pending` | 等合法 base 註冊後生成 |
| Persona | `pending` | `pending` | AutoVtuber 生成 |
| 概念圖 | `pending` | `pending` | AutoVtuber 生成 |
| 預覽圖 | `pending` | `pending` | 六視角與斜角 |

## VRM 契約

| 項目 | 目標 |
|---|---:|
| VRM 版本 | `0.x` |
| Humanoid bones | `>= 54` |
| Blendshape clips | `>= 67` |
| ARKit / Perfect Sync clips | `52` |
| Skinned meshes | `>= 1` |
| 必要嘴型 | `A / I / U / E / O` |
| 必要表情 | `blink / joy / angry / sorrow / fun` |

## 演出說明

- 人格：自然、可信、適合短影片旁白與劇情表演。
- 說話風格：與外觀年齡、性別氣質一致，不使用誇張卡通聲線。
- 適合情緒：中性敘事、輕微驚訝、溫和笑意、嚴肅說明。
- 不適合動作：過度誇張肢體、與角色外觀不一致的幼態表演。
- VDrama 導演注意事項：聲線選擇必須以角色外在形象為主，不只依文字稿情緒選聲音。

## 授權狀態

| 項目 | 狀態 |
|---|---|
| Base model | `pending authorized VRM 0.x` |
| License reference | `pending` |
| 商業交付 | `blocked until base license is confirmed` |
| 標示要求 | `pending` |

> 未填入合法 base 與授權依據前，本角色不得標示為可商業交付。

## AutoVtuber 驗證紀錄

| 檢查 | 結果 |
|---|---|
| VtuberQualityGate | `pending` |
| 測試日期 | `pending` |
| 測試環境 | `pending Windows / NVIDIA acceptance` |
| 已知限制 | `waiting for authorized base asset` |

## 給 VDrama 的回饋期待

請 VDrama 另一台電腦回傳：

```text
handoff/VDRAMA_FEEDBACK_first_character_<YYYYMMDD>.md
```

請特別確認：

- TTS 聲音是否符合角色外觀性別與年齡。
- 嘴型是否能自然對上中文稿。
- Mixamo / 自訂動作是否造成肩頸、手臂或臉部破面。
- 影片輸出時是否有材質、透明、光照或表情異常。
