# 給另一台電腦的協作訊息 - 2026-05-28

AutoVtuber 這邊已經把跨電腦協作方式正式改成 Markdown 契約，不共享程式碼、不假設對方環境。

## 這邊已完成

1. `docs/VDRAMA_MARKDOWN_HANDOFF.md` 已加入 AutoVtuber 驗收分支，定義 AutoVtuber 與 VDrama 的邊界、交付欄位與回饋欄位。
2. `handoff/AUTOVTUBER_EXPORT_TEMPLATE.md` 已建立，未來每個角色送往 VDrama 前都照這份填。
3. `handoff/VDRAMA_FEEDBACK_TEMPLATE.md` 已建立，請 VDrama 測試後照這份回覆。
4. AutoVtuber 已修正舊文件中 AvatarSample / MIT 的授權誤導；現在以 `docs/LICENSES.md`、`docs/RELEASE_READINESS.md`、`docs/AUTHORIZED_BASE_IMPORT.md` 為準。
5. AutoVtuber 已有合法 VRM 0.x base 的本機註冊流程：`scripts/register_authorized_base.py`。
6. AutoVtuber 已新增 atlas 檢查工具：`scripts/inspect_vrm_atlas.py`，可把合法 base 的 texture image index 輸出成 Markdown。
7. AutoVtuber 目前是基於合法 VRM 0.x base 生成新角色，不是從零建立可動人形骨架、skinning 與 blendshape。

## 請另一台電腦注意

1. VDrama 不要 import、複製或依賴 AutoVtuber 的程式碼。
2. VDrama 只讀 AutoVtuber 提供的 Markdown 交付單與另行傳遞的 `.vrm` / 圖片 / persona。
3. 若 VDrama 匯入角色失敗，請不要直接修改角色檔；請填 `handoff/VDRAMA_FEEDBACK_<character_id>_<YYYYMMDD>.md` 回報。
4. 目前還沒有可商業交付的合法 base VRM 本體；AvatarSample A/B/C 只能作 legacy validation，不得作產品角色建立服務 base。
5. TTS 聲線、聲音授權、客戶聲音 consent 由 VDrama 那邊建立政策，並在回饋單中寫清楚。
6. 若 VDrama 需要指定角色外觀、聲音年齡感或短片用途，請先寫進 Markdown，不要用口頭需求飄在外面。

## 下一步

等 AutoVtuber 取得合法 VRM 0.x base 並完成第一個角色輸出後，會建立：

```text
handoff/AUTOVTUBER_EXPORT_<character_id>_<YYYYMMDD>.md
```

VDrama 測試後回覆：

```text
handoff/VDRAMA_FEEDBACK_<character_id>_<YYYYMMDD>.md
```

這兩份文件會成為第一輪跨電腦短影片流程驗收依據。
