"""三語切換 — 包裝 PySide6 QTranslator。

設計：
    - app 啟動時呼叫 install(app, language)
    - runtime 切換語言呼叫 set_language(app, language) → 會透過 QEvent 觸發所有
      已 retranslateUi() 的 widget 重繪
    - 找不到 .qm 檔仍可運行（fallback 為英文 source string）
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..utils.logging_setup import get_logger

if TYPE_CHECKING:
    from PySide6.QtCore import QTranslator
    from PySide6.QtWidgets import QApplication

_log = get_logger(__name__)

SUPPORTED_LANGUAGES: tuple[str, ...] = ("zh_TW", "zh_CN", "en_US")
DEFAULT_LANGUAGE: str = "zh_TW"


_active_translator: "QTranslator | None" = None


def _qm_path(i18n_dir: Path, language: str) -> Path:
    return i18n_dir / f"{language}.qm"


def install(app: "QApplication", i18n_dir: Path, language: str = DEFAULT_LANGUAGE) -> bool:
    """安裝指定語言到 QApplication；回傳 True 若 .qm 檔成功載入。"""
    from PySide6.QtCore import QTranslator

    global _active_translator
    if language not in SUPPORTED_LANGUAGES:
        _log.warning("Unsupported language {}, falling back to {}", language, DEFAULT_LANGUAGE)
        language = DEFAULT_LANGUAGE

    # 移除舊的
    if _active_translator is not None:
        app.removeTranslator(_active_translator)
        _active_translator = None

    qm = _qm_path(i18n_dir, language)
    if not qm.exists():
        _log.warning("Translation file not found: {} — using source strings", qm)
        return False

    tr = QTranslator()
    if not tr.load(str(qm)):
        _log.warning("QTranslator.load failed for {}", qm)
        return False

    app.installTranslator(tr)
    _active_translator = tr
    _log.info("Language switched to {}", language)
    return True


def set_language(app: "QApplication", i18n_dir: Path, language: str) -> bool:
    """runtime 切換；UI 元件需自行 retranslateUi()。"""
    return install(app, i18n_dir, language)


def language_display_name(language: str) -> str:
    """給下拉選單用的人類可讀名稱（不需翻譯）。"""
    mapping = {
        "zh_TW": "繁體中文",
        "zh_CN": "简体中文",
        "en_US": "English",
    }
    return mapping.get(language, language)
