# 🏗️ Architecture — AutoVtuber

> 本檔案描述**當前實作狀態**（不是原計畫）。
> 原始計畫見 `C:\Users\user\.claude\plans\serialized-scribbling-aurora.md`，與當前狀態之差異見章節「重大架構變動」。
> 最後更新：2026-04-26 MVP1 完成後

---

## 🎭 當前實際架構（2026-04-26 MVP1 完成版）

```mermaid
flowchart TB
    USER[👤 使用者表單<br/>髮色/眼色/個性/風格/暱稱]
    UI[🖥️ PySide6 MainWindow<br/>✅ 已完成]

    subgraph SAFETY["🛡️ 安全層 ✅"]
        HG[HardwareGuard<br/>1秒輪詢 VRAM/GPU溫度/RAM/磁碟<br/>+ 強制 snapshot 刷新<br/>+ 可恢復 abort]
        ML[ModelLoader<br/>強制單一重模型於 GPU]
        HEALTH[HealthLog JSONL]
    end

    subgraph PIPELINE["🤖 生成 Pipeline ✅"]
        PB[PromptBuilder<br/>Ollama → fallback templated]
        FG[FaceGenerator<br/>SDXL+AnimagineXL 純 GPU mode<br/>20 steps 1024x1024]
        FA[FaceAligner<br/>BlazeFace 4 點偵測<br/>+ warpAffine + alpha mask blend]
        VA[VRMAssembler<br/>load base.vrm → 換臉 → HSV染色 → save]
    end

    subgraph WORKERS["⚙️ Qt Workers ✅"]
        JW[JobWorker QThread]
        MW[MonitorWorker QThread]
    end

    subgraph DATA["📦 資料 / 模型"]
        BASE_VRM[(assets/base_models/<br/>AvatarSample_A/B/C.vrm<br/>+ face_uv_template_*.json<br/>+ face_uv_mask_*.png)]
        SDXL_W[(models/sdxl/<br/>animagine-xl-4.0/ 6.5GB)]
        IPA_W[(models/ip_adapter/<br/>3.3GB ⚠️ 載入失敗 fallback OK)]
        OLLAMA[(Ollama 服務<br/>gemma4:e4b 9.6GB<br/>⚠️ 太大 abort → fallback)]
    end

    subgraph PRESETS["📚 角色庫 ✅"]
        PS[PresetStore JSON]
        OUT[(output/character_*.vrm)]
    end

    subgraph PATH["🔧 Windows 修復"]
        JCT[ASCII junction C:\\avt<br/>解 MediaPipe / cv2 中文路徑]
    end

    USER --> UI
    UI --> JW
    UI -->|🛑 STOP| HG
    JW --> PB
    JW --> FG
    JW --> FA
    JW --> VA

    HG -.threading.Event.-> ML
    HG -.threading.Event.-> PB
    HG -.threading.Event.-> FG
    ML --> PB
    ML --> FG
    HG --> MW
    MW --> UI

    PB --> OLLAMA
    FG --> SDXL_W
    FG -.optional.-> IPA_W
    FA --> BASE_VRM
    VA --> BASE_VRM
    VA --> OUT
    OUT --> PS

    JCT -.runtime.-> FA
    JCT -.runtime.-> VA

    HG --> HEALTH

    style SAFETY fill:#ffe0e0
    style PIPELINE fill:#e0f0ff
    style WORKERS fill:#e0ffe0
    style DATA fill:#fffde0
    style PRESETS fill:#f0e0ff
    style PATH fill:#ffe0d0
```

---

## ⚠️ 重大架構變動（離開原計畫的決定）

| 變動 | 原計畫 | 實際 | 為什麼 |
|---|---|---|---|
| **SDXL VRAM 策略** | `enable_sequential_cpu_offload()` | `pipe.to("cuda")` 純 GPU | sequential 在 16GB RAM 系統撐爆（spike 96%）；純 GPU 12GB VRAM 剛好夠 |
| **face_aligner 引擎** | MediaPipe Face Mesh (478 點) | MediaPipe BlazeFace (4 點) | Face Mesh 對 anime 完全偵測失敗；BlazeFace short-range 對 anime 穩定 |
| **face_uv_template 來源** | MediaPipe 自動偵測 base atlas | hardcoded VRoid 標準佈局 | VRoid base atlas 太 schematic，BlazeFace 偵測語意不準 |
| **InsightFace** | 用 InsightFace buffalo_l | 整個換 MediaPipe | InsightFace 需 MSVC Build Tools 編譯失敗，且非商用授權 |
| **Ollama 必要性** | 必要 | 可失敗（templated fallback） | gemma4:e4b 9.6GB 在 16GB 系統會爆 RAM |
| **HardwareGuard 行為** | 一次 abort 永遠 abort | 加 `try_clear_abort_if_recovered` 可恢復 | 不然短暫 spike 後永遠擋住下游 stage |
| **Windows Unicode 路徑** | 無處理 | 自動建立 `C:\\avt` junction + re-exec | mediapipe / cv2.imread 對中文路徑會 silently fail |
| **CPU offload** | sequential or model offload | 完全不用 | 16 GB RAM 太緊；純 GPU mode 跑得動 |
| **MainWindow 預覽器** | 後期再補 | 立即 wire QML | 沒 VSeeFace 仍可內建驗證 .vrm 結構 |
| **預設 Ollama 模型** | gemma4:e4b | gemma4:e2b | e4b 9.6GB 在 16GB 系統會 OOM |
| **臉部紋理替換** | SDXL warpAffine 貼到 face atlas | **取消** — VSeeFace 驗證破圖 | VRoid face atlas 是 3D mesh UV 攤開，2D 對齊在 3D 錯位。MVP2 用 Blender UV |
| **3D-first 架構（2026-04-26 大改）** | 2D-only 對齊 face atlas | **加 image-to-3D（TripoSR）+ mesh fitting + persona LLM** | 2D 沒深度資訊，無解；改 3D 路線從根本解決臉部對齊不準 |
| **Persona Generator** | （無）| Stage 1 與 prompt **共享一次 Ollama 載入**生成中文人設 markdown | 使用者 Q：人設文件需要與外觀一致 + 省 Ollama warm/unload 開銷 |
| **TripoSR torchmcubes 替換** | 用官方 torchmcubes（CUDA 編譯）| **PyMCubes shim**（CPU only） | 沒 nvcc + 沒 MSVC，原版 build 失敗；單一函式呼叫，包一層即可 |
| **TripoSR rembg 依賴** | 硬版 import | **lazy-load + patch tsr/utils.py** | rembg 升 numpy→2.x 破壞 mediapipe；SDXL 已是白底不需要去背 |

---

## 套件依賴方向（topological）

```
utils → config → safety → vrm → pipeline → workers → ui → main
                  └──────────────────────────────┘
                            （所有層都用 utils 與 config）
```

---

## 套件依賴方向（topological）

```
utils → config → safety → vrm → pipeline → workers → ui → main
                  └──────────────────────────────┘
                            （所有層都用 utils 與 config）
```

依賴**單向**：底層不認識上層。例如 `safety` 不 import `pipeline`、`vrm` 不 import `ui`。
這保證可以單獨測試任何一層而不需要拉整個 app 起來。

---

## 各套件職責

| 套件 | 職責 | 對外提供 |
|---|---|---|
| `utils` | 純工具：日誌、SHA-256、計時、HTTP 重試 | get_logger / sha256_file / StageTimer / make_session |
| `config` | 路徑解析 + TOML 載入 + pydantic 驗證 + 下載清單解析 | Settings / Paths / load_settings / load_manifest |
| `safety` | 硬體護欄三件組 + 例外定義 + 健康日誌 | HardwareGuard / ModelLoader / HealthLog / Thresholds / SafetyAbort |
| `vrm` | VRM 0.x 讀寫 + 紋理 atlas 對應 | VRMFile / AtlasMap |
| `pipeline` | 生成管線：JobSpec / PromptBuilder / FaceGenerator / FaceAligner / VRMAssembler / Orchestrator | Orchestrator.run(JobSpec) → JobResult |
| `presets` | 角色 preset JSON CRUD（MVP1 後補） | PresetStore |
| `workers` | QThread 封裝（讓 pipeline 不阻塞 UI） | JobWorker / MonitorWorker / DownloadWorker |
| `ui` | PySide6 視窗、表單、3D 預覽器、設定精靈 | MainWindow / SetupWizard |
| `i18n` | Qt Linguist 三語切換 | install_translator / set_language |
| `main` | QApplication bootstrap + 硬體 precheck | main() |

---

## 執行緒模型

```mermaid
flowchart LR
    subgraph MainThread["Main Thread (Qt event loop)"]
        UI[MainWindow]
        SAFE_BANNER[SafetyBanner]
    end

    subgraph MonitorThread["Monitor QThread"]
        MW[MonitorWorker]
        MW -->|HardwareSnapshot signals每 1s| SAFE_BANNER
    end

    subgraph JobThread["Job QThread (per-task)"]
        JW[JobWorker]
        JW --> ORCH[Orchestrator.run]
        ORCH --> PB[PromptBuilder]
        ORCH --> FG[FaceGenerator]
        ORCH --> VA[VRMAssembler]
    end

    UI -->|user clicks Generate| JW
    UI -->|user clicks STOP| HG[HardwareGuard.trigger_emergency_stop]
    HG -->|set abort_event| ORCH

    HG -.threading.Event.-> ORCH
    HG -.threading.Event.-> MW

    JW -->|Qt signals| UI
```

- **Qt 主執行緒**只負責 UI 事件
- **MonitorWorker QThread** 包覆 HardwareGuard 的 daemon thread，把 snapshot 透過 Qt signal 推給 UI
- **JobWorker QThread** 跑 Orchestrator；多個 job 用 QThreadPool 序列化（不允許並發）
- HardwareGuard 內部 `threading.Event` 是跨執行緒中止訊號：UI 的 STOP 按鈕、monitor 的閾值觸發、pipeline 的 check_or_raise 全部透過它通訊

---

## Pipeline 資料流（一次完整生成）

```mermaid
sequenceDiagram
    participant U as UI
    participant J as JobWorker
    participant O as Orchestrator
    participant G as HardwareGuard
    participant L as ModelLoader
    participant Ol as Ollama
    participant SD as SDXL
    participant V as VRM I/O

    U->>J: spec = JobSpec(form)
    J->>O: run(spec)

    O->>G: check_or_raise()
    Note over G,L: Stage 1: Prompt
    O->>L: acquire(OLLAMA, ...)
    L->>L: evict_current() (NONE → no-op)
    L->>Ol: warm via /api/generate
    O->>Ol: chat /api/chat
    Ol-->>O: positive + negative tags
    O->>L: (exit ctx) → unloader_fn calls /api/generate keep_alive=0
    L->>Ol: poll /api/ps until empty
    L->>L: empty_cache + gc

    O->>G: check_or_raise()
    Note over G,L: Stage 2: Face image
    O->>L: acquire(SDXL, build_pipeline)
    L->>SD: from_pretrained + cpu_offload + vae_slicing
    O->>SD: pipe(prompt, ...) with step callback → guard.check
    SD-->>O: PIL Image
    O->>L: (exit ctx) → del pipe + empty_cache

    O->>G: check_or_raise()
    Note over G,V: Stage 3: VRM assembly (CPU only)
    O->>V: VRMFile.load(base.vrm)
    O->>V: replace_image(face, hair, eye)
    O->>V: save(output.vrm)

    O-->>J: JobResult
    J-->>U: emit finished signal
```

關鍵不變式：
1. 任何時刻 GPU 上只能有 ONE 個重模型（由 `ModelLoader._CLASS_LOCK` 強制）
2. 每個 stage 之間 `guard.check_or_raise()`（含 SDXL 內每個 inference step）
3. 即使 stage 失敗，最終結果與 health record 仍會寫入 `presets/` + `logs/health_*.jsonl`

---

## 設定檔層級

| 來源 | 範圍 | 修改後生效 |
|---|---|---|
| `config.example.toml` | 範本（Git 追蹤） | 不會被讀取，只是範本 |
| `config.toml` | 使用者設定（gitignored） | 重啟 app |
| `config.toml [safety]` | 護欄閾值 | 重啟 + 受 pydantic 限制不可超出安全範圍 |
| 程式碼常數（`thresholds.py` `MIN_VRAM_GB`） | 啟動拒絕門檻 | 改程式碼 + 重啟 |

---

## 套件加新模組時的決策樹

1. **這個檔案需要 GPU/torch 嗎？**
   - 是 → 放 `pipeline/` 或 `safety/`
   - 否 → 放 `vrm/` `utils/` `config/`
2. **這個檔案會讀寫使用者檔案嗎？**
   - 是 → 必須走 `Paths` 物件，不可硬編路徑
3. **這個檔案會被 UI 直接呼叫嗎？**
   - 是 → 必須包裝成 QThread worker，不可在主執行緒做 I/O
4. **這個檔案會載入 ML 模型嗎？**
   - 是 → 必須走 `ModelLoader.acquire()`，不可裸 `from_pretrained`

---

## Phase 對應的程式碼增量

| Phase | 主要新增 | 對應 ticket |
|---|---|---|
| A — Foundations | utils + config + safety 三件組 | A01–A09 |
| B — Pipeline | pipeline + vrm | B01–B15 |
| C — UI | ui + workers + i18n | C01–C12 |
| D — Setup wizard + docs | setup_wizard + DOWNLOAD_MANIFEST 實機填值 | D01–D07 |
| E — Reality check | bug fix + VSeeFace 驗收 | E01–E05 |

---

## 每次更新需同步維護

- `AUTOVTUBER.md` 異動紀錄
- `專案總覽.md` 異動紀錄
- 本檔案（若架構變動）
- `docs/HARDWARE_PROTOCOL.md`（若護欄調整）
- `docs/LICENSES.md`（若新增第三方資產）
