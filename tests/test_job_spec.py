"""JobSpec / FormInput / 序列化測試。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_form_input_defaults_valid():
    from autovtuber.pipeline.job_spec import FormInput
    f = FormInput()
    assert f.hair_color_hex == "#5B3A29"
    assert f.eye_color_hex == "#3B5BA5"
    assert f.base_model_id == "AvatarSample_A"


def test_form_input_rejects_bad_hex():
    from pydantic import ValidationError
    from autovtuber.pipeline.job_spec import FormInput

    with pytest.raises(ValidationError):
        FormInput(hair_color_hex="not-a-hex")
    with pytest.raises(ValidationError):
        FormInput(eye_color_hex="#GGGGGG")


def test_job_spec_output_basename_safe():
    from autovtuber.pipeline.job_spec import FormInput, JobSpec

    spec = JobSpec(form=FormInput(nickname="My/Char\\Name?"))
    base = spec.output_basename
    # 不應包含路徑字元
    assert "/" not in base
    assert "\\" not in base
    assert "?" not in base


def test_job_result_to_preset_round_trip(tmp_path: Path):
    from autovtuber.pipeline.job_spec import (
        FormInput,
        JobResult,
        JobSpec,
        StageResult,
    )

    spec = JobSpec(form=FormInput(nickname="testchar"))
    res = JobResult(spec=spec, succeeded=True)
    res.append_stage(StageResult(name="01", succeeded=True, elapsed_seconds=1.0))
    res.append_stage(StageResult(name="02", succeeded=True, elapsed_seconds=2.5))

    p = res.to_preset_path(tmp_path)
    assert p.exists()
    loaded = json.loads(p.read_text(encoding="utf-8"))
    assert loaded["spec"]["form"]["nickname"] == "testchar"
    assert loaded["total_elapsed_seconds"] == 3.5
    assert len(loaded["stages"]) == 2
