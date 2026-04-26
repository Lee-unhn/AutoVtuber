"""SetupDownloadWorker — QThread 包裝 SetupDownloader，逐項下載缺漏資源。

使用 download_signals（key/progress/item_done/all_done）讓 wizard UI 即時更新。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..setup.downloader import SetupDownloader
from ..setup.resource_check import ResourceCheck, ResourceStatus
from ..utils.logging_setup import get_logger

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

_log = get_logger(__name__)


class SetupDownloadWorker:
    """逐項下載 ResourceCheck 內 missing 的資源；不並發（保資源頻寬）。"""

    def __init__(self, signals: "QObject", downloader: SetupDownloader):
        self._signals = signals
        self._downloader = downloader
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self._downloader.cancel()

    def run(self, check: ResourceCheck) -> None:
        all_ok = True
        missing = check.missing
        _log.info("SetupDownloadWorker starting: {} items to download", len(missing))

        for resource in missing:
            if self._cancelled:
                _log.info("Setup download cancelled")
                self._signals.all_done.emit(False)
                return

            def _progress(done: int, total: int, key: str = resource.key) -> None:
                self._signals.progress.emit(key, done, total)

            ok, err = self._downloader.download(resource, progress_cb=_progress)
            self._signals.item_done.emit(resource.key, ok, err)
            if not ok:
                all_ok = False
                _log.warning("Resource {} failed: {}", resource.key, err)

        self._signals.all_done.emit(all_ok)
