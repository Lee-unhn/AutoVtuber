"""主視窗 — 表單 + 預覽 + 安全 banner + 緊急停止。

MVP1 版本：分頁 (Tab) 三頁：建立 / 角色庫 / 設定。
3D 預覽器留 placeholder（QtQuick3D 整合在 ticket C08）。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..config.paths import Paths
from ..config.settings import Settings
from ..i18n.translator import SUPPORTED_LANGUAGES, language_display_name, set_language
from ..pipeline.job_spec import FormInput, JobSpec
from ..utils.logging_setup import get_logger
from .form_panel import FormPanel
from .safety_banner import SafetyBanner
from .widgets.stop_button import make_stop_button
from ..presets.preset_store import PresetStore
from .library_panel import LibraryPanel
from .preview_3d import Preview3D

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow

_log = get_logger(__name__)


class MainWindow:
    """主視窗工廠類別。對 PySide6 lazy import。"""

    def __init__(
        self,
        app,
        paths: Paths,
        settings: Settings,
        monitor_signals,
        on_emergency_stop,
        on_submit_job,
    ):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QComboBox,
            QHBoxLayout,
            QLabel,
            QMainWindow,
            QStatusBar,
            QTabWidget,
            QVBoxLayout,
            QWidget,
        )

        self._app = app
        self._paths = paths
        self._settings = settings
        self._on_emergency_stop = on_emergency_stop
        self._on_submit_job = on_submit_job

        self._win = QMainWindow()
        self._win.setWindowTitle("AutoVtuber 自動化 V皮工坊")
        self._win.resize(1200, 800)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---------- 頂部工具列：safety banner + 語言切換 + STOP ---------- #
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(8, 4, 8, 4)
        self._banner = SafetyBanner()
        top_bar.addWidget(self._banner.widget, stretch=1)

        # 語言下拉
        self._lang_combo = QComboBox()
        for code in SUPPORTED_LANGUAGES:
            self._lang_combo.addItem(language_display_name(code), userData=code)
        # 設預設選中
        for i in range(self._lang_combo.count()):
            if self._lang_combo.itemData(i) == settings.app.language:
                self._lang_combo.setCurrentIndex(i)
                break
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        top_bar.addWidget(QLabel("🌐"))
        top_bar.addWidget(self._lang_combo)

        # 臉部追蹤測試（M3-2）
        from PySide6.QtWidgets import QPushButton as _QPushButton
        self._face_track_btn = _QPushButton("👁️ 臉部追蹤")
        self._face_track_btn.setToolTip("開啟 webcam，即時驗證臉部追蹤 + VRM blendshape weight")
        self._face_track_btn.clicked.connect(self._open_face_tracker)
        top_bar.addWidget(self._face_track_btn)

        # 緊急停止
        self._stop_btn = make_stop_button()
        self._stop_btn.clicked.connect(lambda: on_emergency_stop("UI emergency stop"))
        top_bar.addWidget(self._stop_btn)

        outer.addLayout(top_bar)

        # ---------- 主分頁 ---------- #
        self._tabs = QTabWidget()
        self._tabs.setObjectName("mainTabs")

        # 分頁 1：建立
        create_page = QWidget()
        create_layout = QHBoxLayout(create_page)
        self._form = FormPanel(on_submit=self._handle_submit)
        create_layout.addWidget(self._form.widget, stretch=1)

        # 3D 預覽器（QtQuick3D） — 嘗試建立；失敗 fallback 到文字 placeholder
        try:
            self._preview = Preview3D()
            self._preview.widget.setMinimumWidth(500)
            create_layout.addWidget(self._preview.widget, stretch=1)
        except Exception as e:  # noqa: BLE001 — QtQuick3D 模組未裝就 fallback
            from ..utils.logging_setup import get_logger
            get_logger(__name__).warning("3D preview unavailable: {}; falling back", e)
            self._preview = None
            ph = QLabel(f"🎭\n3D 預覽器無法載入\n({e})")
            ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ph.setMinimumWidth(500)
            ph.setStyleSheet("background:#1e1e1e; color:#888; font-size:14px;")
            create_layout.addWidget(ph, stretch=1)

        self._tabs.addTab(create_page, "✨ 建立角色")

        # 分頁 2：角色庫（preset） — 真實 LibraryPanel
        self._preset_store = PresetStore(paths.presets)
        self._library = LibraryPanel(
            store=self._preset_store,
            on_load_to_form=self._on_load_preset_to_form,
        )
        self._tabs.addTab(self._library.widget, "📚 角色庫")

        # 分頁 3：設定
        settings_placeholder = QLabel("⚙️ 設定\n(直接編輯 config.toml 重啟生效)")
        settings_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        settings_placeholder.setStyleSheet("color:#888; font-size:18px;")
        self._tabs.addTab(settings_placeholder, "⚙️ 設定")

        outer.addWidget(self._tabs, stretch=1)

        # ---------- 狀態列 ---------- #
        status = QStatusBar()
        status.showMessage("就緒")
        self._win.setStatusBar(status)
        self._status = status

        self._win.setCentralWidget(central)

        # ---------- 連接 monitor signals ---------- #
        monitor_signals.snapshot.connect(self._banner.update)
        monitor_signals.emergency_triggered.connect(
            lambda r: self._status.showMessage(f"🛑 緊急停止：{r}", 5000)
        )

        self._apply_dark_theme()

    @property
    def window(self):
        return self._win

    def show(self) -> None:
        self._win.show()

    def set_busy(self, busy: bool) -> None:
        self._form.set_busy(busy)
        self._status.showMessage("生成中..." if busy else "就緒")

    # ---------- handlers ---------- #

    def _handle_submit(self, form: FormInput) -> None:
        spec = JobSpec(form=form)
        _log.info("Submitting job {} (nickname={})", spec.job_id, form.nickname)
        self.set_busy(True)
        self._on_submit_job(spec)

    def _on_language_changed(self, _idx: int) -> None:
        lang = self._lang_combo.currentData()
        set_language(self._app, self._paths.i18n, lang)
        self._status.showMessage(f"語言已切換為 {language_display_name(lang)}", 3000)

    def _on_load_preset_to_form(self, spec: JobSpec) -> None:
        """從角色庫雙擊 preset 後填入表單，並切回建立分頁。"""
        self._form.populate(spec.form)
        self._tabs.setCurrentIndex(0)
        self._status.showMessage(f"已載入 preset: {spec.form.nickname}", 3000)

    def load_vrm_in_preview(self, vrm_path) -> None:
        """job 完成後呼叫；把生成的 .vrm 載入 3D 預覽器。"""
        if self._preview is None:
            return
        try:
            self._preview.load_vrm(vrm_path)
            self._status.showMessage(f"已載入到預覽器：{vrm_path}", 5000)
        except Exception as e:  # noqa: BLE001
            _log.warning("Preview load failed: {}", e)

    def refresh_library(self) -> None:
        """job 完成後呼叫，重新整理角色庫。"""
        self._library.refresh()

    def _open_face_tracker(self) -> None:
        """開啟臉部追蹤測試 dialog。"""
        from .face_tracker_dialog import FaceTrackerDialog
        dlg = FaceTrackerDialog(parent=self._win).build()
        dlg.exec()

    def _apply_dark_theme(self) -> None:
        self._win.setStyleSheet(
            """
            QMainWindow, QWidget { background: #2b2b2b; color: #e0e0e0; }
            QTabWidget::pane { border: 1px solid #444; }
            QTabBar::tab {
                background: #3c3c3c; color: #e0e0e0;
                padding: 8px 16px; border: 1px solid #444; border-bottom: none;
            }
            QTabBar::tab:selected { background: #2b2b2b; }
            QPushButton { background: #4a4a4a; color: white; border: 1px solid #555; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background: #5a5a5a; }
            QPushButton:disabled { color: #888; background: #3a3a3a; }
            QLineEdit, QTextEdit, QComboBox { background: #3c3c3c; color: #e0e0e0; border: 1px solid #555; padding: 4px; }
            QStatusBar { background: #1e1e1e; color: #aaa; }
            """
        )
