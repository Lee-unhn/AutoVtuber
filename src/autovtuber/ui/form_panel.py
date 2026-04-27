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

# Base VRM 模型清單（含中文描述 + 性別 + 風格簡述）
BASE_MODEL_OPTIONS = [
    ("AvatarSample_A", "👩 樣本 A — 女性 / 標準臉型（預設推薦）"),
    ("AvatarSample_B", "👩 樣本 B — 女性 / 不同五官（替代風格）"),
    ("AvatarSample_C", "👨 樣本 C — 男性 / 較高身形"),
]


class FormPanel:
    """組合多個 widget 的表單；提供 to_form_input() 取出 FormInput。"""

    def __init__(
        self,
        parent: "QWidget | None" = None,
        on_submit: Callable[[FormInput], None] | None = None,
        on_preview_concept: Callable[[FormInput], None] | None = None,
        on_finish_from_concept: Callable[[], None] | None = None,
    ):
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
        self._on_preview_concept = on_preview_concept
        self._on_finish_from_concept = on_finish_from_concept
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

        # Base VRM 模型選擇
        self._base_model = QComboBox()
        for model_id, label in BASE_MODEL_OPTIONS:
            self._base_model.addItem(label, userData=model_id)
        self._base_model.setToolTip(
            "選擇要使用的 VRoid 基礎角色模型。Stage 3 會把 SDXL 出來的概念色彩\n"
            "（髮色、眼色、膚色）套到這個 base 模型，產出最終 .vrm。"
        )
        form.addRow("基礎模型", self._base_model)

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

        # 提交區（MVP4-α R2：拆兩段）
        # 1. 🎨 預覽概念圖（只跑 Stage 1+2，~5 min）— 主要按鈕，使用者新流程
        # 2. ✨ 完成 V皮（用 cached concept 跑 Stage 2.5+3，~30s）— 預覽滿意才啟用
        # 3. 💨 完整 e2e（向後相容，一鍵跑完）— 為已知參數的使用者保留
        self._preview_btn = QPushButton("🎨 預覽概念圖（推薦：5 分鐘看 SDXL 概念，不滿意可微調）")
        self._preview_btn.setMinimumHeight(48)
        self._preview_btn.setStyleSheet("background:#3b6ea5; color:white; font-weight:bold;")
        self._preview_btn.clicked.connect(self._submit_preview)
        outer.addWidget(self._preview_btn)

        finish_row = QHBoxLayout()
        self._finish_btn = QPushButton("✨ 完成 V皮（用上面的概念圖組 .vrm，~30 秒）")
        self._finish_btn.setMinimumHeight(40)
        self._finish_btn.setEnabled(False)  # 沒概念圖時 disabled
        self._finish_btn.setToolTip("先點「🎨 預覽概念圖」拿到滿意的 SDXL 圖，這個按鈕才會啟用")
        self._finish_btn.clicked.connect(self._submit_finish)
        finish_row.addWidget(self._finish_btn)

        self._generate_btn = QPushButton("💨 直接完整生成（跳過預覽）")
        self._generate_btn.setMinimumHeight(40)
        self._generate_btn.setToolTip("一鍵跑完整 8 分鐘 e2e，適合已知表單參數的回頭客")
        self._generate_btn.clicked.connect(self._submit)
        finish_row.addWidget(self._generate_btn)
        outer.addLayout(finish_row)

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
        self._set_combo(self._base_model, form.base_model_id)
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
            base_model_id=self._base_model.currentData() or "AvatarSample_A",
        )

    def set_busy(self, busy: bool) -> None:
        """進行中時所有提交按鈕一起 disabled。"""
        self._generate_btn.setEnabled(not busy)
        self._preview_btn.setEnabled(not busy)
        # 完成按鈕需要有 concept 才啟用；busy=True 一律 disable，busy=False 維持原狀
        if busy:
            self._finish_btn.setEnabled(False)

    def set_concept_ready(self, ready: bool) -> None:
        """ConceptWorker 跑完通知；ready=True 啟用「✨ 完成 V皮」按鈕。"""
        self._finish_btn.setEnabled(ready)

    # ---------------- private ---------------- #

    def _submit(self) -> None:
        """💨 完整 e2e（向後相容）。"""
        if self._on_submit is None:
            return
        try:
            form = self.to_form_input()
        except Exception as e:  # pydantic ValidationError 等
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self._widget, "表單錯誤", str(e))
            return
        self._on_submit(form)

    def _submit_preview(self) -> None:
        """🎨 跑 ConceptWorker（只 Stage 1+2）。"""
        if self._on_preview_concept is None:
            # callback 沒接 → 退回完整 run
            self._submit()
            return
        try:
            form = self.to_form_input()
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self._widget, "表單錯誤", str(e))
            return
        self._on_preview_concept(form)

    def _submit_finish(self) -> None:
        """✨ 跑 FullFromConceptWorker（用 cached concept）。"""
        if self._on_finish_from_concept is None:
            return
        self._on_finish_from_concept()

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
