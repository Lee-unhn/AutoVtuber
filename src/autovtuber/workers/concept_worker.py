"""ConceptWorker — 把 Orchestrator.run_concept 包進 QThread。

差別於 JobWorker：只跑 Stage 1 + 2（Ollama prompt/persona + SDXL 概念圖），
**不跑 TripoSR / VRM 組裝**。給「使用者預覽 SDXL 概念圖滿不滿意」用。

使用者點滿意 → 把 ConceptResult 餵給 JobWorker.run_full_from_concept 完成 .vrm。
不滿意 → 微調表單 → 再點「🎨 預覽概念圖」→ 重跑 ConceptWorker（省下 ~30s）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..pipeline.job_spec import JobSpec
from ..pipeline.orchestrator import Orchestrator
from ..utils.logging_setup import get_logger

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

_log = get_logger(__name__)


class ConceptWorker:
    """執行 Orchestrator.run_concept 並透過 signals 回報。

    Signals 用法：
        signals = make_concept_signals()
        signals.concept_progress.connect(...)  # (stage, cur, tot)
        signals.concept_ready.connect(...)     # (concept_image_path: str, persona_md_path: str, concept_obj_id: str)
        signals.concept_failed.connect(...)
    """

    def __init__(self, orchestrator: Orchestrator, signals: "QObject"):
        self._orch = orchestrator
        self._signals = signals
        self._last_concept = None  # 保存最近一次 ConceptResult

    @property
    def last_concept(self):
        """主程序在使用者點「✨ 開始生成 V皮」時取出來餵給 run_full_from_concept。"""
        return self._last_concept

    def run(self, spec: JobSpec) -> None:
        try:
            def _progress(stage: str, cur: int, tot: int) -> None:
                try:
                    self._signals.concept_progress.emit(stage, cur, tot)
                except Exception:  # noqa: BLE001
                    pass

            concept = self._orch.run_concept(spec, progress_cb=_progress)
            self._last_concept = concept
            self._signals.concept_ready.emit(
                str(concept.concept_image_path),
                str(concept.persona_path),
                concept.spec.job_id,
            )
        except Exception as e:  # noqa: BLE001
            _log.exception("ConceptWorker crashed")
            self._signals.concept_failed.emit(str(e))


class FullFromConceptWorker:
    """補完 Stage 2.5 + 3 的 worker；input 是 ConceptResult，output 是完整 JobResult。

    使用者在 GUI 對 ConceptWorker 結果按「✨ 完成 V皮」時用。
    """

    def __init__(self, orchestrator: Orchestrator, signals: "QObject"):
        self._orch = orchestrator
        self._signals = signals

    def run(self, concept) -> None:
        try:
            def _progress(stage: str, cur: int, tot: int) -> None:
                try:
                    self._signals.stage_progress.emit(stage, cur, tot)
                except Exception:  # noqa: BLE001
                    pass

            result = self._orch.run_full_from_concept(concept, progress_cb=_progress)

            for stage in result.stages:
                try:
                    self._signals.stage_done.emit(
                        stage.name, stage.succeeded, stage.elapsed_seconds,
                    )
                except Exception:  # noqa: BLE001
                    pass

            if result.succeeded:
                self._signals.job_finished.emit(result.model_dump_json())
            else:
                self._signals.job_failed.emit(result.error_message or "unknown")
        except Exception as e:  # noqa: BLE001
            _log.exception("FullFromConceptWorker crashed")
            self._signals.job_failed.emit(str(e))
