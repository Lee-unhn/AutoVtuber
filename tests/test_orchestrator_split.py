"""Orchestrator R2 split 測試 — 驗 run_concept / run_full_from_concept / run 三個入口。

策略：mock 所有重模型（PromptBuilder / FaceGenerator / ImageTo3D / VRMAssembler）
驗 stage 順序、cached image 流通、向後相容。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from autovtuber.pipeline.job_spec import (
    EyeShape,
    FormInput,
    GeneratedPrompt,
    HairLength,
    HairStyle,
    JobSpec,
    Personality,
    StyleGenre,
)
from autovtuber.pipeline.orchestrator import ConceptResult, Orchestrator


def make_form() -> FormInput:
    return FormInput(
        nickname="rsplit",
        hair_color_hex="#5B3A29",
        hair_length=HairLength.LONG,
        hair_style=HairStyle.STRAIGHT,
        eye_color_hex="#3B5BA5",
        eye_shape=EyeShape.ALMOND,
        style=StyleGenre.ANIME_MODERN,
        personality=Personality.CALM_INTROVERTED,
        extra_freeform="",
        base_model_id="AvatarSample_A",
    )


def make_orchestrator(tmp_path: Path) -> tuple[Orchestrator, dict]:
    """造一個全部 mock 的 Orchestrator + 紀錄各 mock 被呼叫多少次。"""
    from autovtuber.config.paths import Paths

    paths = Paths()
    paths.root = tmp_path
    paths.output = tmp_path / "output"
    paths.presets = tmp_path / "presets"
    paths.logs = tmp_path / "logs"
    paths.models = tmp_path / "models"
    paths.assets = tmp_path / "assets"
    paths.base_models = tmp_path / "assets" / "base_models"
    paths.docs = tmp_path / "docs"
    paths.setup_flag = tmp_path / "setup.flag"
    paths.download_manifest = tmp_path / "manifest.md"
    paths.ensure_writable_dirs()

    counters = {"pb": 0, "fg": 0, "i23": 0, "va": 0, "persona_save": 0}

    pb = MagicMock()
    def _enhance(_form, _persona):
        counters["pb"] += 1
        return GeneratedPrompt(positive="1girl", negative="bad"), "## 基本資料\n- 名字：test"
    pb.enhance_with_persona = MagicMock(side_effect=_enhance)

    fg = MagicMock()
    def _gen(prompt, reference_photo_path, progress_cb):
        counters["fg"] += 1
        return Image.new("RGB", (1024, 1024), (200, 150, 130))
    fg.generate = MagicMock(side_effect=_gen)
    fg._steps = 20

    i23 = MagicMock()
    def _i23_gen(image, progress_cb):
        counters["i23"] += 1
        m = MagicMock()
        m.vertices = [[0, 0, 0]] * 100
        m.faces = [[0, 1, 2]] * 50
        return m
    i23.generate = MagicMock(side_effect=_i23_gen)

    va = MagicMock()
    def _assemble(form, sdxl_face_image, output_path, face_aligner, tsr_mesh, mesh_fitter):
        counters["va"] += 1
        # touch output_path 模擬寫檔
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake_vrm")
    va.assemble = MagicMock(side_effect=_assemble)

    persona = MagicMock()
    def _save(md, p):
        counters["persona_save"] += 1
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(md, encoding="utf-8")
        return p
    persona.save = MagicMock(side_effect=_save)

    guard = MagicMock(check_or_raise=MagicMock(return_value=None))
    guard.latest = MagicMock(return_value=None)

    health = MagicMock()
    health.append = MagicMock()

    orch = Orchestrator(
        paths=paths,
        guard=guard,
        loader=MagicMock(),
        prompt_builder=pb,
        face_generator=fg,
        face_aligner=MagicMock(),
        vrm_assembler=va,
        health_log=health,
        persona_generator=persona,
        image_to_3d=i23,
        mesh_fitter=MagicMock(),
    )
    return orch, counters


def test_run_concept_runs_only_stage_1_and_2(tmp_path: Path):
    orch, counters = make_orchestrator(tmp_path)
    spec = JobSpec(form=make_form())
    concept = orch.run_concept(spec)

    # 確認只跑 stage 1 + 2
    assert counters["pb"] == 1, "PromptBuilder.enhance_with_persona should run"
    assert counters["fg"] == 1, "FaceGenerator.generate should run"
    assert counters["i23"] == 0, "ImageTo3D should NOT run in run_concept"
    assert counters["va"] == 0, "VRMAssembler should NOT run in run_concept"

    # ConceptResult 結構
    assert isinstance(concept, ConceptResult)
    assert concept.spec == spec
    assert concept.sdxl_image is not None
    assert concept.persona_path.exists()
    assert concept.concept_image_path.exists()
    assert len(concept.stages) == 2
    assert concept.stages[0].name == "01_prompt_persona"
    assert concept.stages[1].name == "02_face_gen"


def test_run_full_from_concept_skips_stage_1_and_2(tmp_path: Path):
    orch, counters = make_orchestrator(tmp_path)
    spec = JobSpec(form=make_form())
    concept = orch.run_concept(spec)

    # 重置 stage 1+2 counters；然後 run_full_from_concept
    counters["pb"] = 0
    counters["fg"] = 0
    result = orch.run_full_from_concept(concept)

    # 確認 stage 1+2 沒重跑
    assert counters["pb"] == 0, "PromptBuilder should NOT run again"
    assert counters["fg"] == 0, "FaceGenerator should NOT run again"
    # 確認 stage 2.5+3 跑了
    assert counters["i23"] == 1, "ImageTo3D should run"
    assert counters["va"] == 1, "VRMAssembler should run"

    assert result.succeeded
    assert result.output_vrm_path is not None
    assert Path(result.output_vrm_path).exists()


def test_run_full_e2e_calls_both_methods(tmp_path: Path):
    orch, counters = make_orchestrator(tmp_path)
    spec = JobSpec(form=make_form())
    result = orch.run(spec)

    # 全部 4 個 mock 都被呼叫
    assert counters["pb"] == 1
    assert counters["fg"] == 1
    assert counters["i23"] == 1
    assert counters["va"] == 1
    assert result.succeeded


def test_run_concept_includes_stage_results_in_full(tmp_path: Path):
    """run_full_from_concept 的 result.stages 應該包含 concept 階段的 stages。"""
    orch, _ = make_orchestrator(tmp_path)
    spec = JobSpec(form=make_form())
    concept = orch.run_concept(spec)
    result = orch.run_full_from_concept(concept)

    stage_names = [s.name for s in result.stages]
    # 應該包含全部 4 個階段
    assert "01_prompt_persona" in stage_names
    assert "02_face_gen" in stage_names
    assert "025_image_to_3d" in stage_names
    assert "03_vrm_assemble" in stage_names
