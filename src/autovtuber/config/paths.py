"""集中式路徑解析。所有「在 AutoVtuber/ 哪個位置找 X」邏輯都在這裡。"""
from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """回傳 AutoVtuber/ 專案根目錄（src/autovtuber/config/paths.py 往上 4 層）。"""
    return Path(__file__).resolve().parents[3]


class Paths:
    """應用程式所有路徑的 single source of truth。"""

    def __init__(
        self,
        models_dir: str | None = None,
        output_dir: str | None = None,
        presets_dir: str | None = None,
        logs_dir: str | None = None,
    ):
        root = project_root()
        self.root: Path = root
        self.assets: Path = root / "assets"
        self.base_models: Path = self.assets / "base_models"
        self.i18n: Path = self.assets / "i18n"
        self.docs: Path = root / "docs"
        self.models: Path = Path(models_dir) if models_dir else root / "models"
        self.output: Path = Path(output_dir) if output_dir else root / "output"
        self.presets: Path = Path(presets_dir) if presets_dir else root / "presets"
        self.logs: Path = Path(logs_dir) if logs_dir else root / "logs"
        self.config_file: Path = root / "config.toml"
        self.config_example: Path = root / "config.example.toml"
        self.setup_flag: Path = root / "setup_complete.flag"
        self.download_manifest: Path = self.docs / "DOWNLOAD_MANIFEST.md"

    def ensure_writable_dirs(self) -> None:
        """確保所有寫入目錄存在。應用啟動時呼叫。"""
        for d in (self.models, self.output, self.presets, self.logs):
            d.mkdir(parents=True, exist_ok=True)
