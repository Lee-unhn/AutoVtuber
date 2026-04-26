"""Preset 系統 — 角色 JSON 庫的 CRUD。

每個 preset 是 `{nickname}_{job_id}.preset.json`，內容為 JobResult 的 JSON dump。
存在 `presets/` 目錄；UI 的「我的角色庫」分頁掃這個目錄列出。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..pipeline.job_spec import JobResult, JobSpec
from ..utils.logging_setup import get_logger

_log = get_logger(__name__)


@dataclass
class PresetSummary:
    """給 UI 列表用的精簡摘要（不必載入完整 JobResult）。"""

    path: Path
    nickname: str
    created_at: float
    succeeded: bool
    job_id: str
    output_vrm_path: str | None


class PresetStore:
    """JSON CRUD。"""

    def __init__(self, presets_dir: Path):
        self._dir = Path(presets_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ---------------- read ---------------- #

    def list_summaries(self) -> list[PresetSummary]:
        out: list[PresetSummary] = []
        for path in sorted(self._dir.glob("*.preset.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                spec = data.get("spec", {})
                form = spec.get("form", {})
                out.append(
                    PresetSummary(
                        path=path,
                        nickname=form.get("nickname", "無名"),
                        created_at=spec.get("created_at", 0.0),
                        succeeded=data.get("succeeded", False),
                        job_id=spec.get("job_id", ""),
                        output_vrm_path=data.get("output_vrm_path"),
                    )
                )
            except Exception as e:  # noqa: BLE001
                _log.warning("Skipping invalid preset {}: {}", path.name, e)
        # 新到舊
        out.sort(key=lambda s: s.created_at, reverse=True)
        return out

    def load(self, path: Path) -> JobResult:
        return JobResult.model_validate_json(path.read_text(encoding="utf-8"))

    def load_spec(self, path: Path) -> JobSpec:
        """只取 JobSpec（給 UI 表單預填用）。"""
        result = self.load(path)
        return result.spec

    # ---------------- write ---------------- #

    def save(self, result: JobResult) -> Path:
        return result.to_preset_path(self._dir)

    def duplicate(self, path: Path, new_nickname: str | None = None) -> JobSpec:
        """複製一個 preset 為新 spec（新 job_id、新 created_at）。

        回傳 JobSpec，使用者可在 UI 修改後重新生成。
        """
        spec = self.load_spec(path)
        # 用 new spec 強制重生 job_id
        new_form = spec.form.model_copy(update={"nickname": new_nickname or f"{spec.form.nickname}_copy"})
        return JobSpec(form=new_form)

    # ---------------- delete ---------------- #

    def delete(self, path: Path) -> bool:
        try:
            path.unlink()
            _log.info("Preset deleted: {}", path.name)
            return True
        except FileNotFoundError:
            return False
