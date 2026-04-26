"""統一日誌設定（loguru）。

每天一個檔案 `logs/autovtuber_YYYYMMDD.log`，自動 14 天輪替、壓縮。
Console 輸出彩色，檔案輸出純文字。
"""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


_INSTALLED: bool = False


def configure(logs_dir: Path, level: str = "INFO") -> None:
    """安裝全域 logger。重複呼叫安全（idempotent）。"""
    global _INSTALLED
    if _INSTALLED:
        return

    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()  # 清除 loguru 預設 handler

    # Console — 彩色，含模組
    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format=(
            "<green>{time:HH:mm:ss}</green> "
            "<level>{level:<7}</level> "
            "<cyan>{name}:{line}</cyan> "
            "<level>{message}</level>"
        ),
    )

    # File — 14 天輪替
    log_path = logs_dir / "autovtuber_{time:YYYYMMDD}.log"
    logger.add(
        str(log_path),
        level="DEBUG",  # 檔案永遠 DEBUG 全收
        rotation="00:00",
        retention="14 days",
        compression="zip",
        encoding="utf-8",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level:<7} | "
            "{name}:{function}:{line} | "
            "{message}"
        ),
    )

    _INSTALLED = True
    logger.info("Logging initialized → {}", log_path.parent)


def get_logger(name: str | None = None):
    """回傳 loguru logger。`name` 目前忽略（loguru 自動帶模組名），保留簽名相容性。"""
    return logger
