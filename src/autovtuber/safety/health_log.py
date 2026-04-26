"""健康紀錄 — 每個 job 結束後記錄峰值 VRAM/溫度，方便事後檢視「今天有沒有逼近紅線」。

格式：JSONL，每行一筆任務。
路徑：logs/health_YYYYMMDD.jsonl
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..utils.logging_setup import get_logger

_log = get_logger(__name__)


@dataclass
class JobHealthRecord:
    """一個任務從開始到結束的硬體健康摘要。"""

    job_id: str
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    succeeded: bool = False
    peak_vram_gb: float = 0.0
    peak_temp_c: int = 0
    peak_ram_pct: float = 0.0
    sustained_load_seconds: int = 0
    abort_reason: str | None = None  # 若中止，原因
    stages: dict[str, float] = field(default_factory=dict)  # 階段名 → 秒數

    def update_peaks(self, vram_gb: float, temp_c: int, ram_pct: float) -> None:
        if vram_gb > self.peak_vram_gb:
            self.peak_vram_gb = vram_gb
        if temp_c > self.peak_temp_c:
            self.peak_temp_c = temp_c
        if ram_pct > self.peak_ram_pct:
            self.peak_ram_pct = ram_pct

    def finalize(self, succeeded: bool, abort_reason: str | None = None) -> None:
        self.finished_at = time.time()
        self.succeeded = succeeded
        self.abort_reason = abort_reason


class HealthLog:
    """JSONL 健康紀錄寫入器。"""

    def __init__(self, logs_dir: Path):
        self._logs_dir = logs_dir
        self._logs_dir.mkdir(parents=True, exist_ok=True)

    def append(self, record: JobHealthRecord) -> Path:
        """寫入一筆記錄；回傳寫入的檔案路徑。"""
        date_str = time.strftime("%Y%m%d", time.localtime(record.started_at))
        path = self._logs_dir / f"health_{date_str}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        _log.debug("HealthLog appended: {} (peak VRAM {:.2f} GB)", record.job_id, record.peak_vram_gb)
        return path
