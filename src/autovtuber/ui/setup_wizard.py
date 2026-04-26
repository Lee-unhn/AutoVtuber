"""首次啟動精靈 — 硬體檢查 + 授權確認 + 資源偵測 + 自動下載 + 完成。

頁面：
    1. 歡迎
    2. 硬體檢測（GPU / VRAM / 驅動）
    3. 授權聲明
    4. 資源偵測（自動掃描 11 項資源）
    5. 自動下載缺漏項（QThread + per-item 進度條）
    6. 完成；寫 setup_complete.flag
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..config.paths import Paths
from ..safety.thresholds import MIN_DRIVER_VERSION, MIN_VRAM_GB
from ..setup.resource_check import ResourceCheck, ResourceState, check_all_resources
from ..utils.logging_setup import get_logger

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWizard

_log = get_logger(__name__)


class SetupWizard:
    """工廠類別 — build() 回傳一個 QWizard。"""

    def __init__(self, paths: Paths, ollama_base_url: str = "http://localhost:11434"):
        self._paths = paths
        self._ollama_url = ollama_base_url
        self._check: ResourceCheck | None = None
        self._download_thread = None  # 保留引用避 GC
        self._download_worker = None
        self._download_signals = None

    def build(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QCheckBox,
            QHBoxLayout,
            QLabel,
            QProgressBar,
            QPushButton,
            QScrollArea,
            QVBoxLayout,
            QWidget,
            QWizard,
            QWizardPage,
        )

        wiz = QWizard()
        wiz.setWindowTitle("AutoVtuber 首次設定")
        wiz.setMinimumSize(750, 550)
        wiz.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        wiz.setOption(QWizard.WizardOption.IndependentPages, False)

        # ---------- 1. 歡迎 ---------- #
        p1 = QWizardPage()
        p1.setTitle("歡迎使用 AutoVtuber 🎭")
        l1 = QVBoxLayout(p1)
        l1.addWidget(QLabel(
            "<h3>自動化 V皮工坊</h3>"
            "<p>從一張表單一鍵生成可動的 VRM VTuber 模型，5–10 分鐘輸出標準 .vrm 檔案。</p>"
            "<p>本精靈會：</p>"
            "<ul>"
            "<li>確認您的硬體符合需求（NVIDIA GPU ≥ 10 GB VRAM）</li>"
            "<li>顯示第三方資產授權聲明</li>"
            "<li>偵測並自動下載缺漏的 AI 模型（首次約 10–12 GB）</li>"
            "</ul>"
            "<p><b>過程中 GPU 不會被超載，遵守「電腦保護護欄」設定。</b></p>"
        ))
        wiz.addPage(p1)

        # ---------- 2. 硬體檢測 ---------- #
        p2 = QWizardPage()
        p2.setTitle("步驟 1/5：硬體檢測")
        l2 = QVBoxLayout(p2)
        l2.addWidget(QLabel(self._hardware_summary()))
        wiz.addPage(p2)

        # ---------- 3. 授權 ---------- #
        p3 = QWizardPage()
        p3.setTitle("步驟 2/5：授權聲明")
        l3 = QVBoxLayout(p3)
        l3.addWidget(QLabel(
            "AutoVtuber 使用以下第三方資產：<br><br>"
            "• <b>Stable Diffusion XL</b>（CreativeML Open RAIL++-M）<br>"
            "• <b>AnimagineXL 4.0</b>（Fair AI Public License — 商用需保留 attribution）<br>"
            "• <b>IP-Adapter Plus Face SDXL</b>（Apache 2.0）<br>"
            "• <b>TripoSR</b>（MIT — VAST-AI-Research / stabilityai）<br>"
            "• <b>rembg / u2net</b>（MIT）<br>"
            "• <b>VRoid AvatarSample</b>（CC0 — madjin/vrm-samples）<br>"
            "• <b>MediaPipe Face Mesh</b>（Apache 2.0）<br><br>"
            "完整清單見 <code>docs/LICENSES.md</code>"
        ))
        ack = QCheckBox("我已閱讀並同意上述授權")
        l3.addWidget(ack)
        p3.registerField("ack_license*", ack)
        wiz.addPage(p3)

        # ---------- 4. 資源偵測 ---------- #
        p4 = QWizardPage()
        p4.setTitle("步驟 3/5：資源偵測")
        l4 = QVBoxLayout(p4)
        scan_btn = QPushButton("🔍 掃描已安裝資源")
        l4.addWidget(scan_btn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scan_result_box = QWidget()
        self._scan_layout = QVBoxLayout(scan_result_box)
        scroll.setWidget(scan_result_box)
        l4.addWidget(scroll)

        summary_label = QLabel("尚未掃描。點擊上方按鈕開始。")
        l4.addWidget(summary_label)
        self._summary_label = summary_label

        scan_btn.clicked.connect(lambda: self._do_scan())
        wiz.addPage(p4)

        # ---------- 5. 自動下載 ---------- #
        p5 = QWizardPage()
        p5.setTitle("步驟 4/5：下載缺漏資源")
        l5 = QVBoxLayout(p5)
        l5.addWidget(QLabel("正在自動下載缺漏的資源（可能需 5–60 分鐘，視網速）"))

        start_btn = QPushButton("⬇️  開始下載")
        l5.addWidget(start_btn)

        self._dl_status = QLabel("等待開始...")
        l5.addWidget(self._dl_status)

        self._dl_overall_progress = QProgressBar()
        self._dl_overall_progress.setRange(0, 100)
        l5.addWidget(self._dl_overall_progress)

        self._dl_current_progress = QProgressBar()
        self._dl_current_progress.setRange(0, 100)
        l5.addWidget(self._dl_current_progress)

        log_scroll = QScrollArea()
        log_scroll.setWidgetResizable(True)
        log_box = QWidget()
        self._dl_log_layout = QVBoxLayout(log_box)
        log_scroll.setWidget(log_box)
        l5.addWidget(log_scroll)

        start_btn.clicked.connect(lambda: self._start_download())
        wiz.addPage(p5)

        # ---------- 6. 完成 ---------- #
        p6 = QWizardPage()
        p6.setTitle("步驟 5/5：完成 ✅")
        l6 = QVBoxLayout(p6)
        l6.addWidget(QLabel(
            "<h3>設定完成！</h3>"
            "<p>您可以關閉此精靈，開始建立第一個 V皮 模型。</p>"
            "<p><i>下次啟動 AutoVtuber 不會再看到此精靈，除非刪除 setup_complete.flag。</i></p>"
        ))
        wiz.addPage(p6)

        wiz.accepted.connect(self._mark_complete)
        return wiz

    # ---------------- internal ---------------- #

    def _do_scan(self) -> None:
        from PySide6.QtWidgets import QLabel
        # 清舊
        while self._scan_layout.count():
            item = self._scan_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._summary_label.setText("掃描中...")
        try:
            self._check = check_all_resources(self._paths, self._ollama_url)
        except Exception as e:  # noqa: BLE001
            self._summary_label.setText(f"❌ 掃描失敗：{e}")
            return

        for item in self._check.items:
            icon = {
                ResourceState.READY: "✅",
                ResourceState.MISSING: "⬇️",
                ResourceState.PARTIAL: "⚠️",
                ResourceState.UNKNOWN: "❓",
            }[item.state]
            text = f"{icon} <b>{item.display_name}</b>"
            if item.state == ResourceState.READY:
                text += f"  <i>(已就緒，{item.actual_size_mb} MB)</i>"
            else:
                text += f"  <i>(預估 {item.expected_size_mb} MB)</i>"
            self._scan_layout.addWidget(QLabel(text))

        if self._check.all_ready:
            self._summary_label.setText(
                f"<span style='color:#2e7d32'><b>✅ 全部 {len(self._check.items)} 項資源就緒，可直接進入下一步</b></span>"
            )
        else:
            self._summary_label.setText(
                f"<span style='color:#1565c0'>需下載 <b>{len(self._check.missing)}</b> 項資源，"
                f"共 <b>{self._check.total_download_mb / 1024:.1f} GB</b></span>"
            )

    def _start_download(self) -> None:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QLabel

        from ..setup.downloader import SetupDownloader
        from ..workers.setup_worker import SetupDownloadWorker
        from ..workers.signals import make_download_signals

        if self._check is None or self._check.all_ready:
            self._dl_status.setText("已全部就緒，無須下載。")
            self._dl_overall_progress.setValue(100)
            return

        self._download_signals = make_download_signals()
        downloader = SetupDownloader(self._paths, self._ollama_url)
        self._download_worker = SetupDownloadWorker(self._download_signals, downloader)

        # signal handlers
        total_items = len(self._check.missing)
        completed_items = {"count": 0}

        def on_progress(key: str, done: int, total: int) -> None:
            if total > 0:
                pct = int(done * 100 / total)
                self._dl_current_progress.setValue(pct)
                self._dl_status.setText(f"下載中 {key}: {done / 1024 / 1024:.1f}/{total / 1024 / 1024:.1f} MB ({pct}%)")

        def on_item_done(key: str, ok: bool, err: str) -> None:
            completed_items["count"] += 1
            self._dl_overall_progress.setValue(int(completed_items["count"] * 100 / total_items))
            mark = "✅" if ok else "❌"
            msg = f"{mark} {key}"
            if not ok and err:
                msg += f"  ({err})"
            self._dl_log_layout.addWidget(QLabel(msg))
            self._dl_current_progress.setValue(0)

        def on_all_done(ok: bool) -> None:
            self._dl_status.setText(
                "✅ 所有下載完成" if ok
                else "⚠️ 部分項目失敗，請查看日誌（pipeline 仍可運作但功能受限）"
            )
            self._dl_overall_progress.setValue(100)

        self._download_signals.progress.connect(on_progress)
        self._download_signals.item_done.connect(on_item_done)
        self._download_signals.all_done.connect(on_all_done)

        # 實際 QThread 啟動
        thread = QThread()
        self._download_thread = thread

        # SetupDownloadWorker.run 是同步函式，要 wrap 進 QObject
        from PySide6.QtCore import QObject, Signal

        class _Runner(QObject):
            done_signal = Signal()

            def __init__(self, worker, check):
                super().__init__()
                self._w = worker
                self._c = check

            def execute(self):
                try:
                    self._w.run(self._c)
                finally:
                    self.done_signal.emit()

        runner = _Runner(self._download_worker, self._check)
        runner.moveToThread(thread)
        thread.started.connect(runner.execute)
        runner.done_signal.connect(thread.quit)
        runner.done_signal.connect(runner.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # 保引用避 GC
        self._runner = runner

        self._dl_status.setText("啟動下載...")
        thread.start()

    def _hardware_summary(self) -> str:
        try:
            from ..safety.hardware_guard import _NvmlAdapter
            adapter = _NvmlAdapter()
            try:
                name = adapter.name()
                _, total_b = adapter.vram_used_total_bytes()
                vram_gb = total_b / (1024 ** 3)
                temp = adapter.temperature_c()
                driver = adapter.driver_version()
            finally:
                adapter.shutdown()
            ok_vram = vram_gb >= MIN_VRAM_GB
            ok_drv = int(driver.split(".")[0]) >= MIN_DRIVER_VERSION[0]
            return (
                f"<b>GPU：</b> {name}<br>"
                f"<b>VRAM：</b> {vram_gb:.1f} GB {'✅' if ok_vram else f'❌ (需 ≥ {MIN_VRAM_GB} GB)'}<br>"
                f"<b>驅動版本：</b> {driver} {'✅' if ok_drv else f'❌ (需 ≥ {MIN_DRIVER_VERSION[0]})'}<br>"
                f"<b>目前溫度：</b> {temp}°C<br><br>"
                f"{'<span style=\"color:#2e7d32\">✅ 硬體符合需求</span>' if (ok_vram and ok_drv) else '<span style=\"color:#c62828\">❌ 硬體不符需求，請更新驅動或升級 GPU</span>'}"
            )
        except Exception as e:  # noqa: BLE001
            return f"❌ 無法偵測硬體：{e}"

    def _mark_complete(self) -> None:
        try:
            self._paths.setup_flag.write_text("1", encoding="utf-8")
            _log.info("setup_complete.flag written")
        except Exception:  # noqa: BLE001
            _log.exception("Failed to write setup_complete.flag")
