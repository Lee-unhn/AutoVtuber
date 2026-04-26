# 🛡️ Hardware Protection Protocol

> **這是「不弄壞電腦」的硬性合約，不是建議值。**
> 修改 `safety/thresholds.py` 或 `config.toml` 的 `[safety]` 區塊前請確認您理解每個閾值的意義。

---

## 即時監控閾值

| 指標 | WARN（黃燈） | ABORT（紅燈） | 行動 |
|---|---|---|---|
| GPU VRAM 使用 | 11.0 GB | 11.5 GB | 立即 `set abort_event`，pipeline 下個 check_or_raise() 會丟 `VRAMExceeded` |
| GPU 溫度 | 78 °C | 83 °C | 進入 60 秒 cooldown（`cooldown_event` set），check_or_raise 阻塞而非中止 |
| 持續 100% GPU 負載 | 5 分鐘 | 8 分鐘 | 強制 30 秒 cooldown |
| 系統 RAM | 80% | 92% | 立即 abort（不可中斷的 OOM 風險） |
| 磁碟剩餘 (G:\) | 5 GB | 1 GB | 立即 abort（避免寫到一半 disk full） |

輪詢頻率：**1 秒/次**（`poll_interval_seconds`）。

---

## 啟動拒絕條件

`precheck_hardware_or_exit()` 在 `QApplication` 啟動前呼叫，下列任一成立則 `sys.exit(1)`：

- 找不到 NVIDIA GPU 或 nvml 初始化失敗
- VRAM 總量 < 10 GB
- NVIDIA 驅動版本 < 550

對應例外：`HardwareUnsupported`

---

## 設計層保護（程式碼強制）

### 1. 「同時間 GPU 上只有一個重模型」不變式
所有 ≥1 GB 的模型必須透過 `ModelLoader.acquire(kind, loader_fn, unloader_fn)` 取得。Loader 內部用 `_CLASS_LOCK` 序列化，並在 acquire/退出時：
- 卸載前一個模型
- `gc.collect()` + `torch.cuda.empty_cache()` + `torch.cuda.synchronize()`
- 套用 `torch.cuda.set_per_process_memory_fraction(0.92)`（保留 8% buffer）

### 2. SDXL 強制保守參數
- `enable_sequential_cpu_offload()` — 慢但 12 GB 安全
- `enable_vae_slicing()` + `enable_vae_tiling()` — 防 VAE 解碼爆 VRAM
- `num_inference_steps = 20`（不可低於 4，不可高於 50）
- `width / height ∈ [512, 1536]`（pydantic 強制）
- `batch_size = 1`（不暴露 UI）

### 3. Ollama VRAM swap 強制協議
PromptBuilder 用完 Ollama 模型一定走：
1. `POST /api/generate {"model": M, "keep_alive": 0}` 強制卸載
2. 輪詢 `GET /api/ps` 直到 `models[]` 不含本模型，timeout 10 s
3. timeout 視為 `SafetyAbort`

### 4. 每個 inference step 檢查 guard
SDXL pipeline 透過 `callback_on_step_end` 在每步呼叫 `guard.check_or_raise()`。一旦 abort 立即拋例外停止生成。

### 5. `try/finally` 永遠釋放
所有 `acquire()` 退出時 — 無論成功 / 例外 / SafetyAbort — 都會 `_evict_current()`。

---

## 使用者緊急停止鈕

UI 主視窗永遠顯示紅色「STOP」按鈕。點擊呼叫 `HardwareGuard.trigger_emergency_stop(reason)`，立即：
- `set abort_event`
- 狀態切到 `ABORT`
- 任何進行中 pipeline 在下次 `check_or_raise` 拋 `UserStopRequested`

---

## 健康日誌

每個 job 結束（成功或失敗）後，`HealthLog.append()` 寫入 `logs/health_YYYYMMDD.jsonl`：

```json
{
  "job_id": "abc123def456",
  "started_at": 1714128000.123,
  "finished_at": 1714128480.789,
  "succeeded": true,
  "peak_vram_gb": 10.7,
  "peak_temp_c": 76,
  "peak_ram_pct": 68.4,
  "sustained_load_seconds": 0,
  "abort_reason": null,
  "stages": {
    "01_prompt": 8.2,
    "02_face_gen": 280.4,
    "03_vrm_assemble": 3.1
  }
}
```

設定頁面可開啟「健康報告」分頁查看歷史紀錄。

---

## 異動規則

修改任何閾值前：
1. 在本檔案說明為什麼要改、新值、影響評估
2. 同步改 `src/autovtuber/safety/thresholds.py` 或 `config.example.toml`
3. 跑 `pytest tests/test_hardware_guard.py` 確認所有測試仍綠
4. 在 `AUTOVTUBER.md` 「主要異動紀錄」列一筆
