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
        del_btn = QPushButton("🗑️ 刪除")
        del_btn.clicked.connect(self._delete_selected)

        btn_row.addWidget(refresh_btn)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(dup_btn)
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
