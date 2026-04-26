"""DownloadWorker — 給 Setup Wizard 用的並行下載 + SHA-256 驗證。

把 utils.http.download_file 包進 worker，可被 wizard 在 QThread 內呼叫。
進度透過 signals 推到 UI。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..config.manifest import ManifestEntry
from ..utils.http import download_file
from ..utils.logging_setup import get_logger

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

_log = get_logger(__name__)


class DownloadWorker:
    """逐項下載 manifest 條目（並非並發 — 維持頻寬可預測性）。"""

    def __init__(self, signals: "QObject", models_dir: Path):
        self._signals = signals
        self._models_dir = Path(models_dir)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self, entries: list[ManifestEntry]) -> None:
        all_ok = True
        for entry in entries:
            if self._cancelled:
                _log.info("Download cancelled by user")
                self._signals.all_done.emit(False)
                return

            dest = self._models_dir / entry.dest_relative

            def _progress(read: int, total: int, key=entry.key) -> None:
                self._signals.progress.emit(key, read, total)

            try:
                download_file(
                    url=entry.url,
                    dest=dest,
                    expected_sha256=entry.sha256 if not entry.sha256.startswith("TBD_") else None,
                    progress=_progress,
                )
                self._signals.item_done.emit(entry.key, True, "")
            except Exception as e:  # noqa: BLE001
                _log.exception("Download failed: {}", entry.key)
                self._signals.item_done.emit(entry.key, False, str(e))
                all_ok = False

        self._signals.all_done.emit(all_ok)
