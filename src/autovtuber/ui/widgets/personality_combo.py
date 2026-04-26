"""人格下拉選單 widget — 列出 16 種人格，含中文標籤。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from ...pipeline.job_spec import Personality

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


# 人格 enum → 顯示名稱（中文）
PERSONALITY_LABELS: dict[Personality, str] = {
    Personality.CHEERFUL_OUTGOING: "開朗外向",
    Personality.CALM_INTROVERTED: "冷靜內向",
    Personality.SHY_GENTLE: "害羞溫柔",
    Personality.CONFIDENT_LEADER: "自信領袖",
    Personality.PLAYFUL_TEASING: "頑皮愛逗",
    Personality.CARING_NURTURING: "照顧型",
    Personality.MYSTERIOUS_COOL: "神秘酷",
    Personality.ENERGETIC_CHAOTIC: "活力過剩",
    Personality.SERIOUS_FOCUSED: "嚴肅專注",
    Personality.DREAMY_ARTISTIC: "夢幻藝術家",
    Personality.ANALYTICAL_LOGICAL: "理性分析",
    Personality.ADVENTUROUS_BRAVE: "冒險勇敢",
    Personality.KIND_HARMONIOUS: "溫和友善",
    Personality.PROUD_NOBLE: "高傲貴族",
    Personality.CURIOUS_CHILDLIKE: "好奇童真",
    Personality.QUIET_OBSERVANT: "安靜觀察",
}


class PersonalityCombo:
    def __init__(
        self,
        initial: Personality = Personality.CALM_INTROVERTED,
        on_change: Callable[[Personality], None] | None = None,
        parent: "QWidget | None" = None,
    ):
        from PySide6.QtWidgets import QComboBox

        self._combo = QComboBox(parent)
        for p, label in PERSONALITY_LABELS.items():
            self._combo.addItem(label, userData=p.value)
        self._on_change = on_change
        self.set_value(initial)
        self._combo.currentIndexChanged.connect(self._on_changed)

    @property
    def widget(self):
        return self._combo

    @property
    def value(self) -> Personality:
        return Personality(self._combo.currentData())

    def set_value(self, p: Personality) -> None:
        idx = list(PERSONALITY_LABELS.keys()).index(p)
        self._combo.setCurrentIndex(idx)

    def _on_changed(self, _idx: int) -> None:
        if self._on_change:
            self._on_change(self.value)
