"""AutoVtuber 主程式入口。

啟動順序：
    1. logging 初始化
    2. 載入 settings + 解析 paths
    3. precheck_hardware_or_exit() — 不符規格立即拒絕
    4. 建立 QApplication + 安裝 i18n
    5. 啟動 HardwareGuard + MonitorWorker
    6. 顯示 MainWindow（首次啟動會在這裡判斷是否跑 setup wizard）
    7. 進入 Qt event loop
"""
from __future__ import annotations

import sys

from .config.paths import Paths
from .config.settings import load_settings, resolved_paths
from .i18n.translator import install as install_translator
from .pipeline.job_spec import JobSpec
from .safety.exceptions import HardwareUnsupported
from .safety.hardware_guard import HardwareGuard, precheck_hardware_or_exit
from .safety.thresholds import Thresholds
from .utils.logging_setup import configure as configure_logging
from .utils.logging_setup import get_logger


def main() -> int:
    # 0. 路徑修正：若安裝在 Unicode 路徑（如「claude專案資料夾」），自動建立 ASCII junction
    #    並 re-exec — 這是 MediaPipe 等 C++ 套件 Windows 路徑相容必要步驟
    paths = Paths()
    paths.ensure_writable_dirs()
    from .safety.path_helpers import reexec_via_ascii_if_needed
    reexec_via_ascii_if_needed(paths.root)

    # 1. 載入設定（無需 logging — 可能 logs 目錄都還沒建）
    settings = load_settings(paths)
    # 重新解析（settings.paths 可能覆寫 paths）
    paths = resolved_paths(settings)
    paths.ensure_writable_dirs()

    # 2. logging
    configure_logging(paths.logs, level=settings.app.log_level)
    log = get_logger(__name__)
    log.info("AutoVtuber starting...")

    # 3. 硬體檢查（不符規格直接退出）
    try:
        precheck_hardware_or_exit()
    except HardwareUnsupported as e:
        log.error("Hardware precheck failed: {}", e)
        # 嘗試彈對話框
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "AutoVtuber — 硬體不符規格", str(e))
        except ImportError:
            print(f"[FATAL] Hardware precheck failed:\n{e}", file=sys.stderr)
        return 1

    # 4. QApplication
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("AutoVtuber")
    app.setOrganizationName("AutoVtuber")

    # i18n
    install_translator(app, paths.i18n, settings.app.language)

    # 5. HardwareGuard + MonitorWorker
    thresholds = Thresholds.from_settings(settings.safety)
    guard = HardwareGuard(thresholds)
    guard.start()

    from .workers.monitor_worker import MonitorWorker
    from .workers.signals import make_monitor_signals

    monitor_signals = make_monitor_signals()
    monitor = MonitorWorker(guard, monitor_signals)
    # （guard 已 started；MonitorWorker 只是把 callback 綁起來）

    # 6. 建立 pipeline 元件（不會立刻載入模型；模型在第一次任務時才 lazy load）
    from .pipeline.face_aligner import FaceAligner
    from .pipeline.face_generator import FaceGenerator
    from .pipeline.image_to_3d import ImageTo3D
    from .pipeline.mesh_fitter import MeshFitter
    from .pipeline.orchestrator import Orchestrator
    from .pipeline.persona_generator import PersonaGenerator
    from .pipeline.prompt_builder import PromptBuilder
    from .pipeline.vrm_assembler import VRMAssembler
    from .presets.preset_store import PresetStore
    from .safety.health_log import HealthLog
    from .safety.model_loader import ModelLoader
    from .ui.main_window import MainWindow
    from .workers.job_worker import JobWorker
    from .workers.signals import make_job_signals

    loader = ModelLoader(guard)
    health_log = HealthLog(paths.logs)
    preset_store = PresetStore(paths.presets)

    # 建立 pipeline（PromptBuilder 嘗試自動偵測 Ollama 模型；若 Ollama 未啟，降級到 default_model 名）
    try:
        prompt_builder = PromptBuilder(
            loader, guard,
            base_url=settings.ollama.base_url,
            default_model=settings.ollama.default_model,
            preferred_model=settings.ollama.preferred_model,
            request_timeout_seconds=settings.ollama.request_timeout_seconds,
            unload_poll_timeout_seconds=settings.ollama.unload_poll_timeout_seconds,
        )
    except RuntimeError as e:
        log.warning("PromptBuilder init failed (Ollama not reachable?): {} — UI will still launch", e)
        prompt_builder = None

    face_generator = FaceGenerator(
        loader, guard, paths.models,
        steps=settings.generation.sdxl_steps,
        cfg_scale=settings.generation.sdxl_cfg_scale,
        size=tuple(settings.generation.sdxl_size),  # type: ignore[arg-type]
        ip_adapter_scale_with_photo=settings.generation.ip_adapter_scale_with_photo,
        ip_adapter_scale_without_photo=settings.generation.ip_adapter_scale_without_photo,
    )
    face_aligner = FaceAligner(paths.models)
    vrm_assembler = VRMAssembler(paths.base_models, paths.models)
    # qwen2.5:3b 對中文長文章節輸出穩定度高於 gemma4:e2b（後者偶爾掉第 7 章節）
    persona_generator = PersonaGenerator(preferred_model="qwen2.5:3b")
    image_to_3d = ImageTo3D(loader, guard, paths.models, mc_resolution=128)
    mesh_fitter = MeshFitter(mode="tint", tint_strength=0.5)

    orchestrator = Orchestrator(
        paths, guard, loader,
        prompt_builder=prompt_builder,  # type: ignore[arg-type]
        face_generator=face_generator,
        face_aligner=face_aligner,
        vrm_assembler=vrm_assembler,
        health_log=health_log,
        persona_generator=persona_generator,
        image_to_3d=image_to_3d,
        mesh_fitter=mesh_fitter,
    )

    # 7. MainWindow + 任務處理
    def _on_emergency_stop(reason: str) -> None:
        monitor.trigger_emergency_stop(reason)

    # 保留任務 thread 引用避免被 GC
    _job_threads: list = []

    def _on_submit_job(spec: JobSpec) -> None:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QMessageBox

        if prompt_builder is None:
            QMessageBox.warning(
                None,
                "Ollama 未連線",
                "找不到 Ollama 服務（http://localhost:11434）。\n\n"
                "請先啟動 Ollama 並確認 `gemma4:e4b` 等模型已 pull，再試一次。",
            )
            win.set_busy(False)
            return

        log.info("Submitting job {} → starting JobWorker thread", spec.job_id)

        signals = make_job_signals()
        worker = JobWorker(orchestrator, signals)
        thread = QThread()
        # worker 不繼承 QObject，所以無法 moveToThread；用 thread.started 觸發 worker.run
        thread.started.connect(lambda: (worker.run(spec), thread.quit()))

        def _on_finished(result_json: str) -> None:
            import json as _json
            try:
                data = _json.loads(result_json)
                vrm_path = data.get("output_vrm_path")
            except Exception:
                vrm_path = None
            QMessageBox.information(
                None, "✨ 生成完成",
                f"V皮 已建立！\n\n輸出：{vrm_path or '(未知)'}\n\n"
                f"已自動載入內建預覽器；可點 📚 角色庫 看完整列表，或用 VSeeFace 開啟測試動作。"
            )
            # 自動載入到預覽器 + 刷新角色庫
            if vrm_path:
                try:
                    win.load_vrm_in_preview(vrm_path)
                except Exception as ex:
                    log.warning("preview load failed: {}", ex)
            try:
                win.refresh_library()
            except Exception:
                pass
            win.set_busy(False)

        def _on_failed(msg: str) -> None:
            QMessageBox.critical(None, "生成失敗", msg)
            win.set_busy(False)

        signals.job_finished.connect(_on_finished)
        signals.job_failed.connect(_on_failed)
        thread.finished.connect(thread.deleteLater)

        _job_threads.append(thread)
        thread.start()

    # ----- MVP4-α R2: 拆兩段流程 ----- #
    # 共享 ConceptWorker 實例（保留 last_concept 供 finish 階段用）
    from .workers.concept_worker import ConceptWorker, FullFromConceptWorker
    from .workers.signals import make_concept_signals
    _concept_worker_holder = {"worker": None}  # mutable holder

    def _on_preview_concept(spec: JobSpec) -> None:
        """🎨 預覽概念圖：跑 ConceptWorker (Stage 1+2)。"""
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QMessageBox
        if prompt_builder is None or not prompt_builder.health_check():
            QMessageBox.warning(None, "Ollama 未連線", "請先啟動 Ollama 再試。")
            return
        win.set_busy(True)
        log.info("Concept preview job {} → starting ConceptWorker", spec.job_id)
        c_signals = make_concept_signals()
        worker = ConceptWorker(orchestrator, c_signals)
        _concept_worker_holder["worker"] = worker  # 保留供 finish 階段取 last_concept
        thread = QThread()
        thread.started.connect(lambda: (worker.run(spec), thread.quit()))

        def _on_concept_ready(image_path: str, persona_path: str, jid: str) -> None:
            QMessageBox.information(
                None, "🎨 概念圖完成",
                f"SDXL 概念圖已生成！\n\n圖片：{image_path}\n人設：{persona_path}\n\n"
                f"滿意 → 點「✨ 完成 V皮」組裝 .vrm（~30 秒）\n"
                f"不滿意 → 微調表單再點「🎨 預覽概念圖」",
            )
            try:
                win.load_concept_in_preview(image_path)
            except Exception as ex:
                log.warning("concept preview load failed: {}", ex)
            win.set_busy(False)
            win.set_concept_ready(True)

        def _on_concept_failed(msg: str) -> None:
            QMessageBox.critical(None, "概念圖生成失敗", msg)
            win.set_busy(False)
            win.set_concept_ready(False)

        c_signals.concept_ready.connect(_on_concept_ready)
        c_signals.concept_failed.connect(_on_concept_failed)
        thread.finished.connect(thread.deleteLater)
        _job_threads.append(thread)
        thread.start()

    def _on_finish_from_concept() -> None:
        """✨ 完成 V皮：用 cached concept 跑 Stage 2.5+3。"""
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QMessageBox

        worker_holder = _concept_worker_holder["worker"]
        if worker_holder is None or worker_holder.last_concept is None:
            QMessageBox.warning(None, "尚未有概念圖", "請先點「🎨 預覽概念圖」")
            return

        win.set_busy(True)
        concept = worker_holder.last_concept
        log.info("Finish from concept job {} → FullFromConceptWorker", concept.spec.job_id)
        signals = make_job_signals()
        worker = FullFromConceptWorker(orchestrator, signals)
        thread = QThread()
        thread.started.connect(lambda: (worker.run(concept), thread.quit()))

        def _on_full_finished(result_json: str) -> None:
            import json as _json
            try:
                data = _json.loads(result_json)
                vrm_path = data.get("output_vrm_path")
            except Exception:
                vrm_path = None
            QMessageBox.information(
                None, "✨ V皮 完成",
                f"VRM 已建立！\n\n輸出：{vrm_path}\n\n用 VSeeFace 載入即可動。",
            )
            if vrm_path:
                try:
                    win.load_vrm_in_preview(vrm_path)
                except Exception:
                    pass
            try:
                win.refresh_library()
            except Exception:
                pass
            win.set_busy(False)
            win.set_concept_ready(False)  # 用完歸零，避免重複組同個 concept

        def _on_full_failed(msg: str) -> None:
            QMessageBox.critical(None, "V皮 組裝失敗", msg)
            win.set_busy(False)

        signals.job_finished.connect(_on_full_finished)
        signals.job_failed.connect(_on_full_failed)
        thread.finished.connect(thread.deleteLater)
        _job_threads.append(thread)
        thread.start()

    # 6.5 First-run check：若沒 setup_complete.flag → 跳 SetupWizard
    if not paths.setup_flag.exists():
        log.info("setup_complete.flag missing → launching first-run setup wizard")
        from .ui.setup_wizard import SetupWizard
        wizard = SetupWizard(paths, ollama_base_url=settings.ollama.base_url).build()
        result = wizard.exec()
        if result == 0:  # QDialog.Rejected → 使用者取消
            log.warning("Setup wizard cancelled by user; exiting")
            guard.stop()
            return 0
        log.info("Setup wizard accepted; proceeding to main window")

    win = MainWindow(
        app,
        paths,
        settings,
        monitor_signals,
        on_emergency_stop=_on_emergency_stop,
        on_submit_job=_on_submit_job,
        on_preview_concept=_on_preview_concept,
        on_finish_from_concept=_on_finish_from_concept,
    )
    win.show()

    # 7. event loop
    exit_code = app.exec()
    log.info("AutoVtuber exiting (code={})", exit_code)
    guard.stop()
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
