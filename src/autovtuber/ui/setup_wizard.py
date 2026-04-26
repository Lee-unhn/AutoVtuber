"""首次啟動精靈 — 硬體檢查 + 授權確認 + 模型下載。

頁面：
    1. 歡迎
    2. 硬體檢測結果（GPU 型號、VRAM、驅動）
    3. 授權聲明（顯示 LICENSES.md 摘要，使用者打勾）
    4. 商用模式確認
    5. 下載清單與大小（從 DOWNLOAD_MANIFEST.md 讀）
    6. 並行下載 + 進度條
    7. 煙霧測試（載入 SDXL → 確認 < 11 GB → 卸載）
    8. 完成；寫 setup_complete.flag
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..config.manifest import load_manifest, total_download_size_mb
from ..config.paths import Paths
from ..safety.thresholds import MIN_DRIVER_VERSION, MIN_VRAM_GB
from ..utils.logging_setup import get_logger

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWizard

_log = get_logger(__name__)


class SetupWizard:
    """工廠類別 — build() 回傳一個 QWizard。"""

    def __init__(self, paths: Paths):
        self._paths = paths

    def build(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QCheckBox,
            QLabel,
            QProgressBar,
            QVBoxLayout,
            QWidget,
            QWizard,
            QWizardPage,
        )

        wiz = QWizard()
        wiz.setWindowTitle("AutoVtuber 首次設定")
        wiz.setMinimumSize(700, 500)
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
            "<li>下載 ~10 GB AI 模型權重（首次設定）</li>"
            "<li>跑一次 SDXL 煙霧測試確認可正常生成</li>"
            "</ul>"
            "<p><b>過程中 GPU 不會被超載，遵守「電腦保護護欄」設定。</b></p>"
        ))
        wiz.addPage(p1)

        # ---------- 2. 硬體檢測 ---------- #
        p2 = QWizardPage()
        p2.setTitle("步驟 1/5：硬體檢測")
        l2 = QVBoxLayout(p2)
        hw_text = self._hardware_summary()
        l2.addWidget(QLabel(hw_text))
        wiz.addPage(p2)

        # ---------- 3. 授權 ---------- #
        p3 = QWizardPage()
        p3.setTitle("步驟 2/5：授權聲明")
        l3 = QVBoxLayout(p3)
        l3.addWidget(QLabel(
            "AutoVtuber 使用以下第三方資產：\n\n"
            "• Stable Diffusion XL（CreativeML Open RAIL++-M）\n"
            "• AnimagineXL 4.0（Fair AI Public License 1.0-SD — 商用需保留 attribution）\n"
            "• IP-Adapter Plus Face SDXL（Apache 2.0）\n"
            "• InsightFace buffalo_l（⚠️ 非商用授權 — 僅 R&D 用，商用請改用其他臉部偵測）\n"
            "• VRoid CC0 base 模型（待 D01 ticket 確認來源）\n\n"
            "完整清單見 docs/LICENSES.md"
        ))
        ack = QCheckBox("我已閱讀並同意上述授權")
        l3.addWidget(ack)
        p3.registerField("ack_license*", ack)
        wiz.addPage(p3)

        # ---------- 4. 下載清單 ---------- #
        p4 = QWizardPage()
        p4.setTitle("步驟 3/5：下載清單")
        l4 = QVBoxLayout(p4)
        entries = load_manifest(self._paths.download_manifest)
        if not entries:
            l4.addWidget(QLabel(
                "⚠️ 找不到 docs/DOWNLOAD_MANIFEST.md\n"
                "請先填入模型下載清單（見 D01 ticket）。"
            ))
        else:
            total_mb = total_download_size_mb(entries)
            l4.addWidget(QLabel(
                f"<p>將下載 <b>{len(entries)} 個檔案</b>，總計約 <b>{total_mb / 1024:.1f} GB</b>：</p>"
            ))
            for e in entries:
                l4.addWidget(QLabel(f"  • {e.key}（{e.size_mb} MB） → models/{e.dest_relative}"))
        wiz.addPage(p4)

        # ---------- 5. 下載進度 ---------- #
        p5 = QWizardPage()
        p5.setTitle("步驟 4/5：下載中")
        l5 = QVBoxLayout(p5)
        l5.addWidget(QLabel("正在下載 AI 模型權重...\n（可能需要 10–60 分鐘，視網速）"))
        progress = QProgressBar()
        progress.setRange(0, 100)
        l5.addWidget(progress)
        l5.addWidget(QLabel("⚠️ 完整下載/煙霧測試邏輯由 ticket D03–D04 補上"))
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
