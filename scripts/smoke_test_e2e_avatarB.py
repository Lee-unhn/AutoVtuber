"""端對端跑 AvatarSample_B 驗證跨 base 模型 — D 任務。

複製 smoke_test_e2e.py 但 base_model_id="AvatarSample_B"。
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main() -> int:
    from autovtuber.config.paths import Paths
    from autovtuber.config.settings import load_settings, resolved_paths
    from autovtuber.pipeline.face_aligner import FaceAligner
    from autovtuber.pipeline.face_generator import FaceGenerator
    from autovtuber.pipeline.image_to_3d import ImageTo3D
    from autovtuber.pipeline.job_spec import (
        EyeShape, FormInput, HairLength, HairStyle, JobSpec, Personality, StyleGenre,
    )
    from autovtuber.pipeline.mesh_fitter import MeshFitter
    from autovtuber.pipeline.orchestrator import Orchestrator
    from autovtuber.pipeline.persona_generator import PersonaGenerator
    from autovtuber.pipeline.prompt_builder import PromptBuilder
    from autovtuber.pipeline.vrm_assembler import VRMAssembler
    from autovtuber.safety.hardware_guard import HardwareGuard, precheck_hardware_or_exit
    from autovtuber.safety.health_log import HealthLog
    from autovtuber.safety.model_loader import ModelLoader
    from autovtuber.safety.thresholds import Thresholds
    from autovtuber.utils.logging_setup import configure as configure_logging

    paths = Paths()
    paths.ensure_writable_dirs()
    settings = load_settings(paths)
    paths = resolved_paths(settings)
    configure_logging(paths.logs, level="INFO")
    print("[1/5] Hardware precheck...")
    precheck_hardware_or_exit()

    thresholds = Thresholds.from_settings(settings.safety)
    with HardwareGuard(thresholds) as guard:
        loader = ModelLoader(guard)
        try:
            pb = PromptBuilder(
                loader, guard,
                base_url=settings.ollama.base_url,
                default_model=settings.ollama.default_model,
                preferred_model=settings.ollama.preferred_model,
            )
        except Exception as e:
            print(f"[FAIL] {e}")
            return 1
        fg = FaceGenerator(loader, guard, paths.models)
        fa = FaceAligner(paths.models)
        va = VRMAssembler(paths.base_models, paths.models)
        persona = PersonaGenerator(preferred_model="qwen2.5:3b")
        i23 = ImageTo3D(loader, guard, paths.models, mc_resolution=128)
        mf = MeshFitter(mode="tint", tint_strength=0.5)
        health = HealthLog(paths.logs)
        orch = Orchestrator(
            paths, guard, loader, pb, fg, fa, va, health,
            persona_generator=persona, image_to_3d=i23, mesh_fitter=mf,
        )

        # AvatarSample_B + 不同表單參數測廣度
        form = FormInput(
            nickname="testB",
            hair_color_hex="#1E1E1E",  # 黑髮
            hair_length=HairLength.MEDIUM,
            hair_style=HairStyle.WAVY,
            eye_color_hex="#7B1F1F",   # 紅眼
            eye_shape=EyeShape.SHARP,
            style=StyleGenre.CYBERPUNK,
            personality=Personality.MYSTERIOUS_COOL,
            extra_freeform="leather jacket",
            base_model_id="AvatarSample_B",
        )
        spec = JobSpec(form=form)
        print(f"[2/5] Job ID: {spec.job_id}, base=AvatarSample_B")

        def _progress(s, c, t):
            print(f"        [{s}] {c}/{t}")

        result = orch.run(spec, progress_cb=_progress)

        if result.succeeded:
            print(f"[OK] {result.output_vrm_path}")
            print(f"     time: {result.total_elapsed_seconds:.1f}s")
            for s in result.stages:
                print(f"       {s.name}: {s.elapsed_seconds:.1f}s {'OK' if s.succeeded else 'FAIL'}")
            return 0
        print(f"[FAIL] {result.error_message}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
