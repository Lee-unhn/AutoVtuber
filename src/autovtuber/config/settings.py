"""讀取 config.toml 並用 pydantic 驗證的設定模組。

首次啟動會自動把 `config.example.toml` 複製成 `config.toml`。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import tomli
from pydantic import BaseModel, Field, field_validator

from .paths import Paths


# ---------------- pydantic 設定模型 ---------------- #


class AppSettings(BaseModel):
    language: str = Field(default="zh_TW", pattern=r"^(zh_TW|zh_CN|en_US)$")
    theme: str = Field(default="dark", pattern=r"^(dark|light)$")
    log_level: str = Field(default="INFO")

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError(f"invalid log_level: {v}")
        return v


class PathsSettings(BaseModel):
    models_dir: str = ""
    output_dir: str = ""
    presets_dir: str = ""
    logs_dir: str = ""


class OllamaSettings(BaseModel):
    base_url: str = "http://localhost:11434"
    preferred_model: str = ""
    default_model: str = "gemma4:e4b"
    request_timeout_seconds: int = 60
    unload_poll_timeout_seconds: int = 10


class GenerationSettings(BaseModel):
    sdxl_steps: int = Field(default=20, ge=4, le=50)
    sdxl_cfg_scale: float = Field(default=6.5, ge=1.0, le=15.0)
    sdxl_size: list[int] = Field(default_factory=lambda: [1024, 1024])
    ip_adapter_scale_with_photo: float = Field(default=0.7, ge=0.0, le=1.0)
    ip_adapter_scale_without_photo: float = Field(default=0.0, ge=0.0, le=1.0)
    seed: int = -1

    @field_validator("sdxl_size")
    @classmethod
    def _check_size(cls, v: list[int]) -> list[int]:
        if len(v) != 2 or any(x < 512 or x > 1536 for x in v):
            raise ValueError("sdxl_size must be [w, h] both in [512, 1536]")
        return v


class SafetySettings(BaseModel):
    """每個欄位都是「會弄壞電腦」的硬性護欄；不開放極端值。"""

    vram_warn_gb: float = Field(default=11.0, ge=4.0, le=23.0)
    vram_abort_gb: float = Field(default=11.5, ge=4.0, le=24.0)
    gpu_temp_warn_c: int = Field(default=78, ge=50, le=85)
    gpu_temp_abort_c: int = Field(default=83, ge=55, le=90)
    ram_warn_pct: float = Field(default=80.0, ge=50.0, le=95.0)
    ram_abort_pct: float = Field(default=92.0, ge=60.0, le=98.0)
    disk_warn_gb: float = Field(default=5.0, ge=1.0)
    disk_abort_gb: float = Field(default=1.0, ge=0.2)
    poll_interval_seconds: float = Field(default=1.0, ge=0.5, le=5.0)
    cuda_memory_fraction: float = Field(default=0.92, ge=0.5, le=0.98)
    abort_hysteresis_seconds: float = Field(default=3.0, ge=0.0, le=30.0)


class CommercialSettings(BaseModel):
    mode: bool = False


class Settings(BaseModel):
    """整合的設定物件。"""

    app: AppSettings = Field(default_factory=AppSettings)
    paths: PathsSettings = Field(default_factory=PathsSettings)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    generation: GenerationSettings = Field(default_factory=GenerationSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    commercial: CommercialSettings = Field(default_factory=CommercialSettings)


# ---------------- 載入函式 ---------------- #


def load_settings(paths: Paths | None = None) -> Settings:
    """從 config.toml 載入設定；首次執行自動複製範例檔。"""
    paths = paths or Paths()

    if not paths.config_file.exists():
        if paths.config_example.exists():
            shutil.copy(paths.config_example, paths.config_file)
        else:
            # 連範例檔都沒有，回傳純預設
            return Settings()

    with paths.config_file.open("rb") as f:
        raw = tomli.load(f)
    return Settings.model_validate(raw)


def resolved_paths(settings: Settings) -> Paths:
    """根據 settings.paths 的覆寫值，回傳最終 Paths 物件。"""
    return Paths(
        models_dir=settings.paths.models_dir or None,
        output_dir=settings.paths.output_dir or None,
        presets_dir=settings.paths.presets_dir or None,
        logs_dir=settings.paths.logs_dir or None,
    )
