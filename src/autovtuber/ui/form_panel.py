"""主表單 — 髮色 / 髮型 / 眼色 / 個性 / 風格 / 上傳照片 / 暱稱 + 自由文字。"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ..pipeline.job_spec import (
    EyeShape,
    FormInput,
    HairLength,
    HairStyle,
    Personality,
    StyleGenre,
)
from .widgets.color_picker import HexColorPicker
from .widgets.personality_combo import PersonalityCombo

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


# Enum → 中文標籤
HAIR_LENGTH_LABELS = {
    HairLength.SHORT: "短髮",
    HairLength.MEDIUM: "中長髮",
    HairLength.LONG: "長髮",
    HairLength.VERY_LONG: "極長髮",
}
HAIR_STYLE_LABELS = {
    HairStyle.STRAIGHT: "直髮",
    HairStyle.WAVY: "波浪",
    HairStyle.CURLY: "捲髮",
    HairStyle.PONYTAIL: "馬尾",
    HairStyle.TWIN_TAILS: "雙馬尾",
    HairStyle.BUN: "包頭",
    HairStyle.BRAIDED: "辮子",
}
EYE_SHAPE_LABELS = {
    EyeShape.ROUND: "圓眼",
    EyeShape.ALMOND: "杏眼",
    EyeShape.SHARP: "銳利眼",
    EyeShape.SLEEPY: "睡眼",
}
STYLE_LABELS = {
    StyleGenre.ANIME_MODERN: "現代動漫",
    StyleGenre.ANIME_CLASSIC: "經典動漫",
    StyleGenre.CHIBI: "Q 版",
    StyleGenre.CYBERPUNK: "賽博龐克",
    StyleGenre.COTTAGECORE: "田園風",
    StyleGenre.SEMI_REALISTIC: "半寫實",
}


class FormPanel:
    """組合多個 widget 的表單；提供 to_form_input() 取出 FormInput。"""

    def __init__(self, parent: "QWidget | None" = None, on_submit: Callable[[FormInput], None] | None = None):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QComboBox,
            QFileDialog,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )

        self._on_submit = on_submit
        self._reference_photo_path: str | None = None
        self._file_dialog = QFileDialog

        self._widget = QWidget(parent)
        outer = QVBoxLayout(self._widget)
        outer.setContentsMargins(16, 16, 16, 16)
        form = QFormLayout()
        form.setSpacing(10)

        # 暱稱
        self._nickname = QLineEdit()
        self._nickname.setPlaceholderText("給角色一個名字")
        self._nickname.setMaxLength(20)
        form.addRow("暱稱", self._nickname)

        # 髮色
        self._hair_color = HexColorPicker("髮色", initial_hex="#5B3A29")
        form.addRow("髮色", self._hair_color.widget)

        # 髮長
        self._hair_length = QComboBox()
        for hl, label in HAIR_LENGTH_LABELS.items():
            self._hair_length.addItem(label, userData=hl.value)
        form.addRow("髮長", self._hair_length)

        # 髮型
        self._hair_style = QComboBox()
        for hs, label in HAIR_STYLE_LABELS.items():
            self._hair_style.addItem(label, userData=hs.value)
        form.addRow("髮型", self._hair_style)

        # 眼色
        self._eye_color = HexColorPicker("眼色", initial_hex="#3B5BA5")
        form.addRow("眼色", self._eye_color.widget)

        # 眼形
        self._eye_shape = QComboBox()
        for es, label in EYE_SHAPE_LABELS.items():
            self._eye_shape.addItem(label, userData=es.value)
        form.addRow("眼形", self._eye_shape)

        # 風格
        self._style = QComboBox()
        for st, label in STYLE_LABELS.items():
            self._style.addItem(label, userData=st.value)
        form.addRow("風格", self._style)

        # 個性
        self._personality = PersonalityCombo()
        form.addRow("個性", self._personality.widget)

        # 自由文字
        self._extra = QTextEdit()
        self._extra.setPlaceholderText("額外描述（例：圍巾、冬天、貓耳）")
        self._extra.setMaximumHeight(70)
        form.addRow("自由描述", self._extra)

        # 上傳照片
        photo_row = QHBoxLayout()
        self._photo_label = QLabel("（未上傳）")
        photo_btn = QPushButton("📸 上傳參考照片")
        photo_btn.clicked.connect(self._choose_photo)
        clear_btn = QPushButton("清除")
        clear_btn.clicked.connect(self._clear_photo)
        photo_row.addWidget(self._photo_label)
        photo_row.addWidget(photo_btn)
        photo_row.addWidget(clear_btn)
        form.addRow("臉型參考", photo_row)

        outer.addLayout(form)

        # 提交
        self._generate_btn = QPushButton("✨ 開始生成 V皮")
        self._generate_btn.setMinimumHeight(48)
        self._generate_btn.clicked.connect(self._submit)
        outer.addWidget(self._generate_btn)

    @property
    def widget(self):
        return self._widget

    def populate(self, form: FormInput) -> None:
        """從現有 FormInput 填回表單（preset 載入時用）。"""
        self._nickname.setText(form.nickname)
        self._hair_color.set_hex(form.hair_color_hex)
        self._eye_color.set_hex(form.eye_color_hex)
        self._set_combo(self._hair_length, form.hair_length.value)
        self._set_combo(self._hair_style, form.hair_style.value)
        self._set_combo(self._eye_shape, form.eye_shape.value)
        self._set_combo(self._style, form.style.value)
        self._personality.set_value(form.personality)
        self._extra.setPlainText(form.extra_freeform)
        self._reference_photo_path = form.reference_photo_path
        self._photo_label.setText(
            Path(form.reference_photo_path).name if form.reference_photo_path else "（未上傳）"
        )

    def to_form_input(self) -> FormInput:
        return FormInput(
            nickname=self._nickname.text().strip() or "無名",
            hair_color_hex=self._hair_color.hex_value,
            hair_length=HairLength(self._hair_length.currentData()),
            hair_style=HairStyle(self._hair_style.currentData()),
            eye_color_hex=self._eye_color.hex_value,
            eye_shape=EyeShape(self._eye_shape.currentData()),
            style=StyleGenre(self._style.currentData()),
            personality=self._personality.value,
            extra_freeform=self._extra.toPlainText().strip(),
            reference_photo_path=self._reference_photo_path,
        )

    def set_busy(self, busy: bool) -> None:
        self._generate_btn.setEnabled(not busy)
        self._generate_btn.setText("生成中..." if busy else "✨ 開始生成 V皮")

    # ---------------- private ---------------- #

    def _submit(self) -> None:
        if self._on_submit is None:
            return
        try:
            form = self.to_form_input()
        except Exception as e:  # pydantic ValidationError 等
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self._widget, "表單錯誤", str(e))
            return
        self._on_submit(form)

    def _choose_photo(self) -> None:
        path, _ = self._file_dialog.getOpenFileName(
            self._widget,
            "選擇參考照片",
            "",
            "圖片 (*.png *.jpg *.jpeg *.webp)",
        )
        if path:
            self._reference_photo_path = path
            self._photo_label.setText(Path(path).name)

    def _clear_photo(self) -> None:
        self._reference_photo_path = None
        self._photo_label.setText("（未上傳）")

    @staticmethod
    def _set_combo(combo, data_value: str) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == data_value:
                combo.setCurrentIndex(i)
                return
