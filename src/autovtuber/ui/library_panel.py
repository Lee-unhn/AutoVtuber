"""角色庫分頁 — 列出 presets/ 內所有 .preset.json，提供載入/複製/刪除。"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ..pipeline.job_spec import JobSpec
from ..presets.preset_store import PresetStore, PresetSummary

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


class LibraryPanel:
    def __init__(
        self,
        parent: "QWidget | None" = None,
        store: PresetStore | None = None,
        on_load_to_form: Callable[[JobSpec], None] | None = None,
    ):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QHBoxLayout,
            QHeaderView,
            QLabel,
            QListWidget,
            QListWidgetItem,
            QMessageBox,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )

        self._store = store
        self._on_load_to_form = on_load_to_form

        self._widget = QWidget(parent)
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(16, 16, 16, 16)

        layout.addWidget(QLabel("📚 我的角色庫"))

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._load_selected)
        layout.addWidget(self._list, stretch=1)

        # 按鈕列
        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("🔄 重新整理")
        refresh_btn.clicked.connect(self.refresh)
        load_btn = QPushButton("📥 載入到表單")
        load_btn.clicked.connect(self._load_selected)
        dup_btn = QPushButton("📋 複製")
        dup_btn.clicked.connect(self._duplicate_selected)
        export_btn = QPushButton("📤 匯出")
        export_btn.setToolTip("匯出 .preset.json — 可傳給朋友載入相同設定")
        export_btn.clicked.connect(self._export_selected)
        import_btn = QPushButton("📦 匯入")
        import_btn.setToolTip("從外部 .preset.json 載入設定")
        import_btn.clicked.connect(self._import_preset)
        del_btn = QPushButton("🗑️ 刪除")
        del_btn.clicked.connect(self._delete_selected)

        btn_row.addWidget(refresh_btn)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(dup_btn)
        btn_row.addWidget(export_btn)
        btn_row.addWidget(import_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.refresh()

    @property
    def widget(self):
        return self._widget

    def refresh(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QListWidgetItem
        import time

        self._list.clear()
        if self._store is None:
            return
        for s in self._store.list_summaries():
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(s.created_at)) if s.created_at else "—"
            mark = "✅" if s.succeeded else "⚠️"
            text = f"{mark}  {s.nickname}    {ts}    [{s.job_id[:8]}]"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, s)
            self._list.addItem(item)

    # ---------- handlers ---------- #

    def _selected_summary(self) -> PresetSummary | None:
        from PySide6.QtCore import Qt
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _load_selected(self, *_args) -> None:
        from PySide6.QtWidgets import QMessageBox
        s = self._selected_summary()
        if s is None or self._store is None or self._on_load_to_form is None:
            return
        try:
            spec = self._store.load_spec(s.path)
            self._on_load_to_form(spec)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self._widget, "載入失敗", str(e))

    def _duplicate_selected(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        s = self._selected_summary()
        if s is None or self._store is None or self._on_load_to_form is None:
            return
        try:
            spec = self._store.duplicate(s.path)
            self._on_load_to_form(spec)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self._widget, "複製失敗", str(e))

    def _export_selected(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        s = self._selected_summary()
        if s is None or self._store is None:
            return
        target, _ = QFileDialog.getSaveFileName(
            self._widget,
            "匯出 Preset",
            f"{s.nickname}.preset.json",
            "Preset (*.preset.json *.json)",
        )
        if not target:
            return
        try:
            self._store.export_preset(s.path, Path(target))
            QMessageBox.information(self._widget, "匯出成功", f"已匯出至:\n{target}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self._widget, "匯出失敗", str(e))

    def _import_preset(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox
        if self._store is None:
            return
        source, _ = QFileDialog.getOpenFileName(
            self._widget,
            "選擇要匯入的 Preset",
            "",
            "Preset (*.preset.json *.json)",
        )
        if not source:
            return
        # 可選重新命名
        new_nick, ok = QInputDialog.getText(
            self._widget,
            "新暱稱（可選）",
            "若想重新命名匯入的 preset，請輸入新暱稱（留空保留原名）：",
        )
        try:
            target = self._store.import_preset(
                Path(source),
                new_nickname=new_nick.strip() if (ok and new_nick.strip()) else None,
            )
            QMessageBox.information(self._widget, "匯入成功", f"已匯入到角色庫:\n{target.name}")
            self.refresh()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self._widget, "匯入失敗", str(e))

    def _delete_selected(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        s = self._selected_summary()
        if s is None or self._store is None:
            return
        confirm = QMessageBox.question(
            self._widget,
            "刪除確認",
            f"確定要刪除「{s.nickname}」嗎？此動作無法復原。",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if self._store.delete(s.path):
            self.refresh()
