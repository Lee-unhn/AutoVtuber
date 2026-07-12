"""Orchestrator — 把 PromptBuilder / FaceGenerator / VRMAssembler 串成一個 job。

提供三個入口（MVP4-α R2 加入兩階段拆分）：
    - run_concept(spec) → 跑 Stage 1+2 出概念圖（~5 min），不跑 TripoSR/VRM 組裝
                          給「使用者預覽 → 不滿意可微調表單重生」用，省下 3 min
    - run_full_from_concept(concept) → 帶 cached concept 跑 Stage 2.5+3 (~30s)
    - run(spec) → 完整 e2e（向後相容）= run_concept + run_full_from_concept

每階段：
    - guard.check_or_raise() 在開始前
    - StageTimer 計時
    - StageResult 寫入 JobResult
    - HealthLog 收峰值

頂層介面 run() / run_concept() 設計成可被 QThread worker 直接 invoke。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from ..config.paths import Paths
from ..safety.exceptions import SafetyAbort
from ..safety.hardware_guard import HardwareGuard
from ..safety.health_log import HealthLog, JobHealthRecord
from ..safety.model_loader import ModelLoader
from ..utils.logging_setup import get_logger
from ..utils.timing import StageTimer
from .face_aligner import FaceAligner
from .face_generator import FaceGenerator
from .image_to_3d import ImageTo3D
from .job_spec import GeneratedPrompt, JobResult, JobSpec, StageResult
from .mesh_fitter import MeshFitter
from .persona_generator import PersonaGenerator
from .prompt_builder import PromptBuilder
from .vrm_assembler import VRMAssembler

if TYPE_CHECKING:
    from PIL import Image as _PILImage

_log = get_logger(__name__)


# 進度回呼類型：(stage_name, current_step, total_steps)
ProgressCallback = Callable[[str, int, int], None]


@dataclass
class ConceptResult:
    """run_concept() 的中間結果 — 跑完 Stage 1+2 但還沒做 3D 處理。

    給 GUI 「概念圖預覽」使用：使用者可以先看 SDXL 出來的圖滿不滿意，
    不滿意可以微調表單重跑（只重跑 Stage 1+2 ~5 min），滿意才把
    這個 ConceptResult 餵給 run_full_from_concept() 完成 .vrm 組裝。
    """

    spec: JobSpec
    prompt: GeneratedPrompt
    persona_md: str
    sdxl_image: "_PILImage.Image"
    persona_path: Path  # 已寫到 disk
    concept_image_path: Path  # 已寫到 disk（為了 GUI 展示）
    elapsed_seconds: float
    stages: list[StageResult] = field(default_factory=list)


class Orchestrator:
    """串接整個生成 pipeline。每個 job 一個實例，使用後即拋。"""

    def __init__(
        self,
        paths: Paths,
        guard: HardwareGuard,
        loader: ModelLoader,
        prompt_builder: PromptBuilder,
        face_generator: FaceGenerator,
        face_aligner: FaceAligner,
        vrm_assembler: VRMAssembler,
        health_log: HealthLog,
        persona_generator: PersonaGenerator | None = None,
        image_to_3d: ImageTo3D | None = None,
        mesh_fitter: MeshFitter | None = None,
        voice_generator=None,   # MVP5.5：VoiceGenerator | None；可選，None 則跳過 Stage 4
    ):
        self._paths = paths
        self._guard = guard
        self._loader = loader
        self._pb = prompt_builder
        self._fg = face_generator
        self._fa = face_aligner
        self._va = vrm_assembler
        self._health = health_log
        self._persona = persona_generator or PersonaGenerator()
        self._i23 = image_to_3d
        self._mf = mesh_fitter
        self._vg = voice_generator

    def run_concept(
        self,
        spec: JobSpec,
        progress_cb: ProgressCallback | None = None,
    ) -> ConceptResult:
        """快速跑 Stage 1 + 2 出概念圖；不跑 TripoSR/VRM 組裝。

        給 GUI 「概念圖預覽」用：使用者可先看 SDXL 圖滿不滿意，
        滿意才呼叫 run_full_from_concept() 完成 .vrm（省下 ~30s）。

        Raises:
            SafetyAbort: 硬體護欄中止
            Exception: Ollama / SDXL 任何階段崩潰
        """
        record = JobHealthRecord(job_id=spec.job_id)
        stages: list[StageResult] = []
        total_elapsed = 0.0

        try:
            # Stage 1: Prompt + Persona
            self._guard.check_or_raise()
            with StageTimer("01_prompt_persona") as t:
                if progress_cb:
                    progress_cb("01_prompt_persona", 0, 2)
                prompt, persona_md = self._pb.enhance_with_persona(spec.form, self._persona)
                if progress_cb:
                    progress_cb("01_prompt_persona", 1, 2)
                persona_path = self._paths.output / f"{spec.output_basename}_persona.md"
                self._persona.save(persona_md, persona_path)
                # MVP5：把 persona 萃取成 runtime JSON（給未來 chat 接口用）
                try:
                    from .persona_runtime import build_persona_runtime, save_persona_runtime
                    rt = build_persona_runtime(persona_md)
                    runtime_path = self._paths.output / f"{spec.output_basename}_persona_runtime.json"
                    save_persona_runtime(rt, runtime_path)
                except Exception:  # noqa: BLE001
                    _log.exception("persona_runtime save failed (non-fatal)")
                if progress_cb:
                    progress_cb("01_prompt_persona", 2, 2)
            stages.append(StageResult(
                name="01_prompt_persona",
                succeeded=True,
                elapsed_seconds=t.elapsed_seconds,
                artifact_path=str(persona_path),
            ))
            total_elapsed += t.elapsed_seconds

            # Stage 2: SDXL face image — 含 iris-color assertion 一次重生機會
            self._guard.check_or_raise()
            from .concept_assertions import assert_iris_color_matches_form
            with StageTimer("02_face_gen") as t:
                def _step_progress(cur: int, tot: int):
                    if progress_cb:
                        progress_cb("02_face_gen", cur, tot)
                # session()：retry 共用已載入 pipeline，不重載 6.5GB ckpt（省 ~230s）
                with self._fg.session() as fg_sess:
                    face_img = fg_sess.generate(
                        prompt=prompt,
                        reference_photo_path=spec.form.reference_photo_path,
                        progress_cb=_step_progress,
                    )
                    # Iris 色彩斷言：若 concept 眼色與表單偏差太大，重生一次（避免 AnimagineXL bias）
                    iris_check = assert_iris_color_matches_form(face_img, spec.form)
                    if not iris_check.passed:
                        _log.warning(
                            "Iris color assertion FAILED on first try: {} — regenerating with different seed",
                            iris_check.detail,
                        )
                        # 重生：略改 seed 提示模型 explore 不同樣本
                        retry_prompt = prompt.model_copy(
                            update={"seed": (prompt.seed + 7919) if prompt.seed >= 0 else -1}
                        )
                        face_img = fg_sess.generate(
                            prompt=retry_prompt,
                            reference_photo_path=spec.form.reference_photo_path,
                            progress_cb=_step_progress,
                        )
                        iris_check_retry = assert_iris_color_matches_form(face_img, spec.form)
                        _log.warning(
                            "After regeneration: {} ({})",
                            "PASS" if iris_check_retry.passed else "still FAIL",
                            iris_check_retry.detail,
                        )
                    else:
                        _log.info("Iris color check OK: {}", iris_check.detail)
            stages.append(StageResult(
                name="02_face_gen",
                succeeded=True,
                elapsed_seconds=t.elapsed_seconds,
            ))
            total_elapsed += t.elapsed_seconds

            # 把概念圖寫到 disk 給 GUI 顯示
            concept_path = self._paths.output / f"{spec.output_basename}_concept.png"
            try:
                face_img.save(concept_path)
            except Exception:  # noqa: BLE001
                _log.exception("Failed to save concept PNG (non-fatal)")

            return ConceptResult(
                spec=spec,
                prompt=prompt,
                persona_md=persona_md,
                sdxl_image=face_img,
                persona_path=persona_path,
                concept_image_path=concept_path,
                elapsed_seconds=total_elapsed,
                stages=stages,
            )
        finally:
            self._health.append(record)

    def run_full_from_concept(
        self,
        concept: ConceptResult,
        progress_cb: ProgressCallback | None = None,
    ) -> JobResult:
        """帶 cached concept 跑 Stage 2.5 + 3 出 .vrm（不重跑 prompt/SDXL）。"""
        spec = concept.spec
        result = JobResult(spec=spec, succeeded=False)
        record = JobHealthRecord(job_id=spec.job_id)
        result.prompt = concept.prompt
        result.persona_md_path = str(concept.persona_path)
        # 把 concept 階段的 stage results 複製進來
        for s in concept.stages:
            result.append_stage(s)
            record.stages[s.name] = s.elapsed_seconds

        face_img = concept.sdxl_image

        def _peak(stage_name: str):
            snap = self._guard.latest()
            if snap is not None:
                record.update_peaks(snap.vram_used_gb, snap.gpu_temp_c, snap.ram_used_pct)

        try:
            # Stage 2.5: Image-to-3D（可選）
            tsr_mesh = None
            if self._i23 is not None:
                self._guard.check_or_raise()
                with StageTimer("025_image_to_3d") as t:
                    def _i23_progress(stage: str, cur: int, tot: int):
                        if progress_cb:
                            progress_cb(f"025_image_to_3d:{stage}", cur, tot)
                    try:
                        tsr_mesh = self._i23.generate(face_img, progress_cb=_i23_progress)
                        _peak("025_image_to_3d")
                    except Exception as e:  # noqa: BLE001 — image-to-3D 失敗不應擋 pipeline
                        _log.warning(
                            "ImageTo3D 失敗 ({}: {}) — 退回 MVP1 mode（無 mesh tint）",
                            type(e).__name__, e,
                        )
                        tsr_mesh = None
                stage_succeeded = tsr_mesh is not None
                result.append_stage(
                    StageResult(
                        name="025_image_to_3d",
                        succeeded=stage_succeeded,
                        elapsed_seconds=t.elapsed_seconds,
                        error_message=None if stage_succeeded else "image-to-3D failed; pipeline continued",
                    )
                )
                record.stages["025_image_to_3d"] = t.elapsed_seconds

            # ---------------- Stage 3: VRM assembly ---------------- #
            self._guard.check_or_raise()
            output_path = self._paths.output / f"{spec.output_basename}.vrm"
            with StageTimer("03_vrm_assemble") as t:
                if progress_cb:
                    progress_cb("03_vrm_assemble", 0, 1)
                self._va.assemble(
                    form=spec.form,
                    sdxl_face_image=face_img,
                    output_path=output_path,
                    face_aligner=self._fa,
                    tsr_mesh=tsr_mesh,
                    mesh_fitter=self._mf,
                )
                _peak("03_vrm_assemble")
                if progress_cb:
                    progress_cb("03_vrm_assemble", 1, 1)
            result.append_stage(
                StageResult(
                    name="03_vrm_assemble",
                    succeeded=True,
                    elapsed_seconds=t.elapsed_seconds,
                    artifact_path=str(output_path),
                )
            )
            record.stages["03_vrm_assemble"] = t.elapsed_seconds

            # ---------------- Stage 4 (MVP5.5): Voice preview ---------------- #
            # 非阻塞 — 失敗只 log 不擋主 pipeline
            if self._vg is not None:
                try:
                    self._guard.check_or_raise()
                except SafetyAbort:
                    _log.warning("Voice stage skipped due to safety abort earlier in run")
                else:
                    with StageTimer("04_voice_preview") as t:
                        try:
                            from .persona_runtime import build_persona_runtime
                            # persona_md 來自 ConceptResult（run_full_from_concept 收到的）；
                            # 若直接 caller 進 run() 則來自 stage 1 的局部變數
                            persona_md_text = concept.persona_md
                            rt = build_persona_runtime(persona_md_text)
                            voice_out = self._paths.output / f"{spec.output_basename}_voice_sample.wav"
                            vres = self._vg.generate(spec.form, rt, voice_out)
                            # 把 voice_description 寫回 runtime JSON（MVP5.5 → MVP6 接口）
                            try:
                                from .persona_runtime import save_persona_runtime
                                rt.voice_profile = vres.voice_description
                                rt_path = self._paths.output / f"{spec.output_basename}_persona_runtime.json"
                                save_persona_runtime(rt, rt_path)
                            except Exception:  # noqa: BLE001
                                _log.exception("Failed to update persona_runtime with voice_profile")
                            _peak("04_voice_preview")
                            ok = vres.wav_path is not None
                        except Exception as e:  # noqa: BLE001
                            _log.warning("Stage 4 voice gen crashed ({}: {}) — pipeline continues",
                                         type(e).__name__, e)
                            ok = False
                    result.append_stage(
                        StageResult(
                            name="04_voice_preview",
                            succeeded=ok,
                            elapsed_seconds=t.elapsed_seconds,
                            error_message=None if ok else "voice gen failed; non-blocking",
                        )
                    )
                    record.stages["04_voice_preview"] = t.elapsed_seconds

            # ---------------- 完成 ---------------- #
            result.succeeded = True
            result.output_vrm_path = str(output_path)
            record.finalize(succeeded=True)
            return result

        except SafetyAbort as e:
            _log.warning("🛑 Job {} aborted by safety: {}", spec.job_id, e)
            result.succeeded = False
            result.error_message = str(e)
            record.finalize(succeeded=False, abort_reason=str(e))
            return result
        except Exception as e:
            _log.exception("Job {} failed: {}", spec.job_id, e)
            result.succeeded = False
            result.error_message = str(e)
            record.finalize(succeeded=False, abort_reason=f"unexpected: {e}")
            return result
        finally:
            self._health.append(record)
            # 永遠存 preset（即使失敗，也方便診斷）
            try:
                result.to_preset_path(self._paths.presets)
            except Exception:  # noqa: BLE001
                _log.exception("Failed to save preset")

    def run(
        self,
        spec: JobSpec,
        progress_cb: ProgressCallback | None = None,
    ) -> JobResult:
        """完整 e2e 入口（向後相容）= run_concept → run_full_from_concept。

        新介面用 run_concept + run_full_from_concept 拆兩段以支援使用者
        微調循環（GUI 預覽概念圖後決定要不要組 .vrm）。
        """
        try:
            concept = self.run_concept(spec, progress_cb)
        except SafetyAbort as e:
            _log.warning("🛑 Job {} aborted by safety in concept stage: {}", spec.job_id, e)
            result = JobResult(spec=spec, succeeded=False, error_message=str(e))
            try:
                result.to_preset_path(self._paths.presets)
            except Exception:  # noqa: BLE001
                pass
            return result
        except Exception as e:
            _log.exception("Job {} concept stage failed: {}", spec.job_id, e)
            result = JobResult(spec=spec, succeeded=False, error_message=str(e))
            try:
                result.to_preset_path(self._paths.presets)
            except Exception:  # noqa: BLE001
                pass
            return result
        return self.run_full_from_concept(concept, progress_cb)


def run_smoke(spec_json: str) -> int:
    """CLI 煙霧測試入口：`python -m autovtuber.pipeline.orchestrator <spec.json>`。"""
    import json
    import sys

    from ..config.settings import load_settings, resolved_paths
    from ..safety.thresholds import Thresholds

    settings = load_settings()
    paths = resolved_paths(settings)
    paths.ensure_writable_dirs()

    thresholds = Thresholds.from_settings(settings.safety)
    spec = JobSpec.model_validate(json.loads(Path(spec_json).read_text(encoding="utf-8")))

    with HardwareGuard(thresholds, poll_root_path=paths.output) as guard:
        loader = ModelLoader(guard)
        pb = PromptBuilder(
            loader, guard,
            base_url=settings.ollama.base_url,
            default_model=settings.ollama.default_model,
            preferred_model=settings.ollama.preferred_model,
        )
        fg = FaceGenerator(loader, guard, paths.models)
        fa = FaceAligner(paths.models)
        va = VRMAssembler(
            paths.base_models,
            paths.models,
            commercial_mode=settings.commercial.mode,
            allow_restricted_samples_for_validation=settings.assets.allow_restricted_samples_for_validation,
        )
        persona = PersonaGenerator()
        i23 = ImageTo3D(loader, guard, paths.models, mc_resolution=128)
        mf = MeshFitter(mode="tint", tint_strength=0.5)
        health = HealthLog(paths.logs)

        orch = Orchestrator(
            paths, guard, loader, pb, fg, fa, va, health,
            persona_generator=persona,
            image_to_3d=i23,
            mesh_fitter=mf,
        )
        result = orch.run(spec)
        print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
        return 0 if result.succeeded else 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m autovtuber.pipeline.orchestrator <spec.json>")
        sys.exit(2)
    sys.exit(run_smoke(sys.argv[1]))
