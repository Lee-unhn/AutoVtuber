"""JobWorker — 把 Orchestrator.run 包進 QThread，避免阻塞 UI。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..pipeline.job_spec import JobSpec
from ..pipeline.orchestrator import Orchestrator
from ..utils.logging_setup import get_logger

if TYPE_CHECKING:
    from PySide6.QtCore import QObject, QThread

_log = get_logger(__name__)


class JobWorker:
    """執行單一 JobSpec 並透過 signals 回報進度。

    用法（在 UI 端）：
        signals = make_job_signals()
        signals.job_finished.connect(_on_finished)
        worker = JobWorker(orchestrator, signals)
        thread = QThread()
        worker_obj = _move_to_qthread(worker, thread)
        thread.started.connect(lambda: worker_obj.run(spec))
        thread.start()
    """

    def __init__(self, orchestrator: Orchestrator, signals: "QObject"):
        self._orch = orchestrator
        self._signals = signals

    def run(self, spec: JobSpec) -> None:
        """阻塞執行；進度透過 signals 推出。"""
        try:
            def _stage_progress(stage: str, cur: int, tot: int) -> None:
                try:
                    self._signals.stage_progress.emit(stage, cur, tot)
                except Exception:  # noqa: BLE001
                    pass

            result = self._orch.run(spec, progress_cb=_stage_progress)

            # 發送各階段完成事件（給 UI timeline 用）
            for stage in result.stages:
                self._signals.stage_done.emit(
                    stage.name,
                    stage.succeeded,
                    stage.elapsed_seconds,
                )

            if result.succeeded:
                self._signals.job_finished.emit(result.model_dump_json())
            else:
                self._signals.job_failed.emit(result.error_message or "unknown")
        except Exception as e:  # noqa: BLE001
            _log.exception("JobWorker crashed")
            self._signals.job_failed.emit(str(e))
