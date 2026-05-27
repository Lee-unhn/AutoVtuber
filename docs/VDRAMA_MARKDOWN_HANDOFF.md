# AutoVtuber 與 VDrama Markdown 交接規格

> 狀態：商業探索草案  
> 更新日期：2026-05-27  
> 目的：讓兩個在不同電腦上獨立開發的專案，以 Markdown 溝通角色交付要求與驗收回饋，不共享程式碼或執行環境。

## 專案邊界

AutoVtuber 與 VDrama 是兩個獨立產品。

| 專案 | 負責事項 | 不負責事項 |
|---|---|---|
| AutoVtuber | 角色生成、Persona 產生、VRM 匯出、角色品質檢驗、素材與授權狀態說明 | 腳本演出、TTS、場景導演、MP4 渲染 |
| VDrama | 腳本拆解、聲音表演、嘴型時間軸、動作與場景渲染、MP4 輸出 | 角色生成、base model 選擇、擅自變更核准後的角色外觀 |

硬性原則：

1. 兩邊的 repository 不 import、vendor 或假設對方的程式碼與環境存在。
2. Markdown 文件是溝通契約；二進位角色資產分開傳遞，並在文件中列出檔名與驗證資料。
3. VDrama 若發現下游問題，先用 Markdown 回報；AutoVtuber 僅在問題可重現或確認為新需求後變更輸出契約。
4. 角色資產授權狀態未確認前，不得標示為可商業交付。

## 交接流程

```text
AutoVtuber 電腦                         VDrama 電腦
----------------                         -------------
產生角色
驗證 VRM
撰寫 AUTOVTUBER_EXPORT_*.md  -------->  讀取交付文件
另行傳送 .vrm / 預覽圖                  載入角色並演出
                                 <-----  撰寫 VDRAMA_FEEDBACK_*.md
修正輸出或核准角色                      輸出影片
```

Markdown 是需求與驗收狀態的依據。`.vrm`、預覽圖片、Persona 與最終 `.mp4` 是交付物，不是共享原始碼。

## AutoVtuber 交付文件

每一個送往 VDrama 的角色，AutoVtuber 應建立：

```text
handoff/
  AUTOVTUBER_EXPORT_<character_id>_<YYYYMMDD>.md
```

文件必要欄位：

| 章節 | 必填內容 |
|---|---|
| 角色識別 | character id、顯示名稱、風格、預期年齡形象、預期聲音形象 |
| 交付檔案 | `.vrm`、`persona.md`、概念圖、預覽圖、SHA-256 或下載/版本參照 |
| VRM 契約 | VRM 版本、humanoid bone 數量、blendshape 數量、viseme 支援、ARKit/Perfect Sync 數量、mesh 與 skin 數量 |
| 演出說明 | 人格、說話風格、適合的情緒範圍、不適合的動作或表演 |
| 授權狀態 | base model/來源素材、標示要求、商業交付是否放行 |
| 驗證紀錄 | AutoVtuber quality gate 結果與測試日期 |

根據目前已驗證範例，初始驗收基準如下：

| 能力 | 最低接受值 |
|---|---:|
| 格式 | VRM 0.x |
| Humanoid bones | 54 |
| Blendshape clips | 67 |
| ARKit / Perfect Sync clips | 52 |
| Skinned meshes | 3 |
| Morph targets | 560 |
| 必要嘴型 | `A`、`I`、`U`、`E`、`O` |
| 必要表情 | blink 與基本情緒 clips |

## VDrama 回饋文件

VDrama 每次匯入一個角色，或遇到阻擋影片製作的要求時，應回傳：

```text
handoff/
  VDRAMA_FEEDBACK_<character_id>_<YYYYMMDD>.md
```

文件必要欄位：

| 章節 | 必填內容 |
|---|---|
| 匯入結果 | 成功/失敗、runtime 與 renderer 版本 |
| 視覺結果 | 正面、側面、動作與表情檢查的截圖或影片參照 |
| 語音結果 | 使用的 TTS 聲線、viseme 對應覆蓋率、嘴型問題 |
| 動作結果 | retargeting 結果、骨骼/clip 錯誤、需修正的動作 |
| 阻擋問題 | AutoVtuber 必須符合的精確要求、嚴重性、重現方式 |
| 核准狀態 | 核准進入影片製作，或退回待修 |

## 目前契約備註

- AutoVtuber 現階段輸出 VRM 0.x，因為現有管線以 VSeeFace 相容性為基礎。
- Quality gate 能證明角色在結構上適合下游動畫，不代表 VDrama 的語音、動作、燈光或最終影片自然度已通過。
- VDrama 可以提出新增表情或動作 metadata 的需求，但不得靜默修改 AutoVtuber 交付的核准角色檔。
- Persona 目前以 Markdown 交付，是 VDrama 設計台詞語氣與演出方向的主要依據。

## 商業交付阻擋項目

兩邊任何一方對外提供付費產出以前，必須處理：

1. 統一 base VRM 授權描述。`README.md` 曾將 AvatarSample 寫為 CC0，而 `docs/LICENSES.md` 紀錄為 VRoid 特定條件授權。
2. 決定二進位角色資產在兩台電腦間的傳遞方法，避免把受限制素材誤提交到公開 repository。
3. 定義商業聲音政策：合法授權的 TTS 聲線、客戶授權聲音，以及必要的 consent/attribution 紀錄。
4. 用一個真實 AutoVtuber 角色完成第一份 VDrama 匯入回饋文件並核准。

## 下一份要建立的文件

當第一個角色送往 VDrama 電腦測試時，應依本規格建立實際交付單：

```text
handoff/AUTOVTUBER_EXPORT_<character_id>_<YYYYMMDD>.md
```

填寫後的交付單會成為跨電腦商業工作流程的第一個驗證依據。
