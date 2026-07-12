# AutoVtuber

> 自動化 VTuber 模型工作站：填一張表單 → 約 8 分鐘輸出可直接載入 VSeeFace 的 .vrm 模型。

**Author**: [@Lee-unhn](https://github.com/Lee-unhn) · a2264563@gmail.com

[![pytest](https://img.shields.io/badge/pytest-154%2F154_passing-brightgreen)](#測試)
[![python](https://img.shields.io/badge/python-3.12-blue)](#環境需求)
[![license](https://img.shields.io/badge/license-MIT-blue)](#授權)
[![status](https://img.shields.io/badge/MVP1--5-PASS_8.0%2F10-success)](#開發狀態)
[![audit](https://img.shields.io/badge/Reality_Checker-3_rounds_PASS-brightgreen)](AUTOVTUBER.md)

## 專案簡介 / Overview

AutoVtuber 把傳統 20–100 小時的 Live2D 繪製 + 綁定流程，壓縮成「填表單 → 5–10 分鐘出 `.vrm`」的全自動 pipeline。使用者透過 PySide6 GUI 輸入髮色/眼色/個性/風格/暱稱，系統依序執行 Ollama 提示生成、SDXL 1.0 + AnimagineXL 4.0 LoRA 出概念圖、TripoSR 建 3D 臉型 mesh、MeshFitter 貼合 VRoid base atlas，最後 VRMAssembler 輸出 VRM 0.x（含 hair/eye recolor + skin tone tint）+ 七章節 persona markdown + chat-ready runtime JSON。

實機跑時：RTX 3060 12GB / Ryzen 7 / 16GB RAM 約 5 分鐘（290s e2e，2026-07-12 SSD junction + retry session 修復後；先前 USB HDD 約 8-16 分鐘）。

> ⚠️ **發佈狀態（release asset policy）**：角色生成與 VRM quality gate 已完成 Beta 驗證；公開或商業發佈仍受 base VRM 授權、Windows 打包與實機驗收阻擋，進度見 [`docs/RELEASE_READINESS.md`](docs/RELEASE_READINESS.md)。
> 預設停用 AvatarSample A/B/C 作產品 base（僅驗證用，`assets.allow_restricted_samples_for_validation = true` 手動啟用）；自有或另行獲准的 VRM 0.x 底模依 [`docs/AUTHORIZED_BASE_IMPORT.md`](docs/AUTHORIZED_BASE_IMPORT.md) 註冊，準備流程見 [`docs/BASE_VRM_PREP_PACKET.md`](docs/BASE_VRM_PREP_PACKET.md)。
> 與 VDrama（下游 VRM 消費者）協作採 Markdown 契約：[`docs/VDRAMA_MARKDOWN_HANDOFF.md`](docs/VDRAMA_MARKDOWN_HANDOFF.md) + [`handoff/`](handoff/) 模板。

### 品質保證

無人類介入的「Reality Checker agent 三輪審計」對比 Hololive / Nijisanji EN / Vshojo 中段位 VTuber 標準：

| Round | 平均分 | 結果 | 關鍵改進 |
|---|---|---|---|
| v1 | 5.3/10 | 🔴 FAIL | iris bug、persona 套路、概念無記憶點 |
| v2 | 6.8/10 | 🟡 CONDITIONAL | iris assertion（3→8）+ 3/4 構圖 |
| **v3** | **8.0/10** | 🟢 **PASS** | 反套路 refactor + 簽名 Prop + regex validator |

所有 5 個 rubric（concept art / persona / VRM coherence / originality / production-readiness）均 ≥ 7.5。

## 架構 / Architecture

```mermaid
flowchart TD
  FORM(["PySide6 表單\nform_panel"])
  OLLAMA["Ollama gemma4:e2b\n(warm 1 次共用)"]
  PROMPT["prompt_builder\n3x repeat color tag\n+ priority-neg anti-drift"]
  PERSONA["persona_generator\n反套路 regex validator\n+ 簽名 Prop section"]
  SDXL["SDXL + AnimagineXL\nface_generator"]
  CONCEPT["1024×1024 概念圖"]
  ASSERT{{"concept_assertions\nBlazeFace ROI\niris hue ≤ 40° tol"}}
  RETRY["seed-shifted retry\n(若 iris assertion 失敗)"]
  TRIPO["TripoSR\n3D mesh + vertex_colors"]
  MESHFIT["MeshFitter LAB tint\nVRoid base atlas 膚色貼合"]
  RECOLOR["texture_recolor\nhair / eye HSV recolor"]
  ASM["VRMAssembler\nVRM 0.x + ARKit 52 blendshapes"]
  RUNTIME["persona_runtime\nto_llm_system_prompt ≤500 字\n+ emotion 觸發詞 → blendshape\n+ voice_profile (MVP6)"]
  VOICE["voice_generator (MVP5.5)\nVoxCPM-0.5B Voice Design\n5-10s WAV from persona"]
  OUT(["output/&lt;basename&gt;\n.vrm · _concept.png\n_persona.md · _persona_runtime.json\n_voice_sample.wav (MVP5.5)"])
  HW[/"HardwareGuard\nVRAM/溫度/RAM 1Hz 監控"/]
  ML[/"ModelLoader\nacquire(ModelKind) 序列化"/]

  FORM --> OLLAMA
  OLLAMA --> PROMPT
  OLLAMA --> PERSONA
  PERSONA --> RUNTIME
  PERSONA --> VOICE
  PROMPT --> SDXL --> CONCEPT
  CONCEPT --> ASSERT
  ASSERT -->|FAIL| RETRY --> SDXL
  ASSERT -->|PASS| TRIPO
  TRIPO --> MESHFIT --> RECOLOR --> ASM --> OUT
  RUNTIME --> OUT
  VOICE --> OUT
  HW -.監控.-> SDXL
  HW -.監控.-> TRIPO
  HW -.監控.-> VOICE
  ML -.單模型駐留.-> SDXL
  ML -.單模型駐留.-> TRIPO
  ML -.單模型駐留.-> VOICE
```

**設計原則**：
1. **3D-first**：捨棄無深度資訊的 2D-only 對齊路線
2. **One model on GPU at a time**：`ModelLoader.acquire(ModelKind)` 序列化所有重模型載入
3. **HardwareGuard 全程監控**：VRAM / GPU 溫度 / RAM / 磁碟 1Hz 輪詢，超閾值自動 abort + cleanup
4. **Fallback 不中斷 pipeline**：Ollama 不可用 → templated prompt；rembg 不可用 → 白色閾值；TripoSR 失敗 → MVP1 無 mesh tint 模式
5. **Auto-assertion + retry**：concept 與 form 眼色不符自動偵測 + 換 seed 重生一次（MVP5）
6. **反套路驗證**：persona LLM 輸出走 regex 黑名單；命中 5 個禁區 trope 之一即回 anti-trope template（MVP5）

## 技術棧 / Tech Stack

- Python 3.12，`pyproject.toml` + `requirements.txt`
- PySide6 + QtQuick3D（GUI）
- Ollama（`gemma4:e2b` 提示生成；`qwen2.5:3b` persona override）
- SDXL 1.0 + AnimagineXL 4.0 LoRA（概念圖）
- TripoSR（stabilityai 3D mesh）
- VRoid base atlas + 自製 MeshFitter（LAB tint）
- VRM 0.x 輸出，直接相容 VSeeFace / Warudo
- i18n：en_US / zh_CN / zh_TW（`assets/i18n/*.ts`）

## 主要檔案 / Key Files

- `AUTOVTUBER.md` — 完整專案規格與開發歷程（含 Reality Checker 三輪審計）
- `src/autovtuber/main.py` + `__main__.py` — 程式入口
- `src/autovtuber/pipeline/orchestrator.py` — 統籌四階段 pipeline，含 iris assertion 自動 retry
- `src/autovtuber/pipeline/prompt_builder.py` — SDXL prompt（3x tag repeat + priority-neg anti-drift）
- `src/autovtuber/pipeline/persona_generator.py` — 七章節 persona md 生成（反套路 regex validator）
- `src/autovtuber/pipeline/persona_runtime.py` — **MVP5**：persona → chat system prompt + emotion 觸發字典
- `src/autovtuber/pipeline/concept_assertions.py` — **MVP5**：BlazeFace ROI iris hue 自動斷言
- `src/autovtuber/pipeline/image_to_3d.py` — TripoSR 整合
- `src/autovtuber/pipeline/mesh_fitter.py` — VRoid base atlas LAB chroma tint
- `src/autovtuber/pipeline/vrm_assembler.py` — VRM 0.x 輸出（含 ARKit Perfect Sync 52 blendshapes）
- `src/autovtuber/safety/hardware_guard.py` / `model_loader.py` — 硬體護欄
- `scripts/smoke_test_e2e.py` / `smoke_test_e2e_avatarB.py` — 端到端 smoke test
- `scripts/render_vrm_six_views.py` — VRM 六視角驗收渲染
- `docs/architecture.md` / `docs/MVP3_PLAN.md` / `docs/HARDWARE_PROTOCOL.md` — 架構與硬體協議文件
- `assets/base_models/face_uv_template_*.json` — A/B/C 三種 VRoid base UV 模板
- `config.example.toml` — 設定範例

## 使用 / Usage

```bash
# 1. 環境（建議用 venv，pyproject.toml 會自動 bootstrap）
pip install -r requirements.txt

# 2. 複製設定
cp config.example.toml config.toml  # 編輯後填入模型路徑

# 3. 啟動 GUI
run.bat              # Windows
python -m autovtuber # 跨平台
```

輸入髮色/眼色/個性/風格/暱稱 → 按 ✨ → `output/` 目錄會出現：
- `character_<ts>_<hash>_<nickname>.vrm` — VSeeFace 可直接拖
- `_concept.png` — SDXL 概念圖
- `_persona.md` — 七章節中文人設（基本資料 / 個性 / 簽名 Prop / 背景 / 興趣 / 口頭禪 / 直播風格 / 互動方式）
- `_persona_runtime.json` — **MVP5** chat-ready 設定（≤500 字 system prompt + 中文→blendshape emotion 字典）
- `_voice_sample.wav` — **MVP5.5** VoxCPM 聲音預覽（10s 音檔，符合 persona 個性的合成聲音）

## License

MIT — 詳見 [`docs/LICENSES.md`](docs/LICENSES.md)。
