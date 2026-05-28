# VDRAMA_FEEDBACK_<character_id>_<YYYYMMDD>

> 狀態：draft  
> 來源專案：VDrama  
> 回覆對象：AutoVtuber  
> 請只用 Markdown 描述需求與驗收結果，不要求 AutoVtuber import VDrama 程式碼。

## 匯入結果

| 欄位 | 內容 |
|---|---|
| Character ID | `<character_id>` |
| VRM 檔名 | `<character>.vrm` |
| 匯入狀態 | `<success / failed>` |
| Runtime / renderer | `<Three.js / @pixiv/three-vrm / app version>` |
| 錯誤訊息 | `<none / exact error>` |

## 視覺結果

| 檢查 | 結果 | 截圖或影片參照 |
|---|---|---|
| 正面站姿 | `<pass / fail>` | `<path or link>` |
| 側面站姿 | `<pass / fail>` | `<path or link>` |
| 表情切換 | `<pass / fail>` | `<path or link>` |
| 口型同步 | `<pass / fail>` | `<path or link>` |
| 動作播放 | `<pass / fail>` | `<path or link>` |

## 語音結果

| 欄位 | 內容 |
|---|---|
| TTS provider / voice | `<provider / voice id>` |
| 聲音性別與年齡感 | `<符合 / 不符合 / 說明>` |
| Viseme 覆蓋率 | `<A/I/U/E/O or ARKit names>` |
| 嘴型問題 | `<none / details>` |

## 動作結果

- Retargeting 結果：
- 骨骼錯誤：
- 表情權重錯誤：
- 需要 AutoVtuber 補充的 metadata：

## 阻擋問題

| 嚴重性 | 問題 | 重現方式 | AutoVtuber 需要修正 |
|---|---|---|---|
| `<P0/P1/P2>` | `<issue>` | `<steps>` | `<requested output contract change>` |

## 核准狀態

| 欄位 | 內容 |
|---|---|
| 是否核准進入影片製作 | `<approved / rejected / pending>` |
| 退回原因 | `<none / details>` |
| 下一步 | `<action>` |
