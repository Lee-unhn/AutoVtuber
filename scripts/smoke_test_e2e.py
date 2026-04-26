"""端對端煙霧測試 — 不開 UI、不需要使用者互動。

驗證：
    1. Ollama 連線（若有 gemma4:e4b 等模型）
    2. SDXL + IP-Adapter 載入（若 models/sdxl/ + models/ip_adapter/ 存在）
    3. 生成單張 1024x1024 臉部圖（會佔 ~10GB VRAM）
    4. VRM 組裝（會替換 face/hair/iris 紋理）
    5. 輸出 .vrm 檔到 output/

執行：
    C:\\avt\\venv\\Scripts\\python.exe C:\\avt\\scripts\\smoke_test_e2e.py

使用者要：
    python -m autovtuber 後在 UI 點生成；本腳本是 dev-only。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 從 ASCII junction 跑（避免 mediapipe 中文路徑 bug）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main() -> int:
    from autovtuber.config.paths import Paths
    from autovtuber.config.settings import load_settings, resolved_paths
    from autovtuber.pipeline.face_aligner import FaceAligner
    from autovtuber.pipeline.face_generator import FaceGenerator
    from autovtuber.pipeline.image_to_3d import ImageTo3D
    from autovtuber.pipeline.job_spec import (
        EyeShape,
        FormInput,
        HairLength,
        HairStyle,
        JobSpec,
        Personality,
        StyleGenre,
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
    paths.ensure_writable_dirs()
    configure_logging(paths.logs, level="INFO")

    print("[1/5] Hardware precheck...")
    precheck_hardware_or_exit()
    print("      OK")

    print("[2/5] Starting HardwareGuard + ModelLoader...")
    thresholds = Thresholds.from_settings(settings.safety)
    with HardwareGuard(thresholds) as guard:
        loader = ModelLoader(guard)

        print("[3/5] Constructing pipeline components...")
        try:
            pb = PromptBuilder(loader, guard,
                               base_url=settings.ollama.base_url,
                               default_model=settings.ollama.default_model,
                               preferred_model=settings.ollama.preferred_model)
            print(f"      Ollama model: {pb.selected_model}")
        except Exception as e:
            print(f"      [FAIL] PromptBuilder init: {e}")
            print("      Hint: start Ollama and `ollama pull gemma4:e4b`")
            return 1

        fg = FaceGenerator(loader, guard, paths.models)
        fa = FaceAligner(paths.models)
        va = VRMAssembler(paths.base_models, paths.models)
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

        print("[4/5] Building test JobSpec...")
        form = FormInput(
            nickname="smoketest",
            hair_color_hex="#5B3A29",
            hair_length=HairLength.LONG,
            hair_style=HairStyle.STRAIGHT,
            eye_color_hex="#3B5BA5",
            eye_shape=EyeShape.ALMOND,
            style=StyleGenre.ANIME_MODERN,
            personality=Personality.CALM_INTROVERTED,
            extra_freeform="cute hoodie",
            base_model_id="AvatarSample_A",
        )
        spec = JobSpec(form=form)
        print(f"      Job ID: {spec.job_id}")

        print("[5/5] Running orchestrator...")

        def _progress(stage, cur, tot):
            print(f"        [{stage}] {cur}/{tot}")

        result = orch.run(spec, progress_cb=_progress)

        print("=" * 60)
        if result.succeeded:
            print(f"[OK] Generation succeeded!")
            print(f"     Output: {result.output_vrm_path}")
            print(f"     Total time: {result.total_elapsed_seconds:.1f}s")
            print(f"     Stages:")
            for s in result.stages:
                print(f"       {s.name}: {s.elapsed_seconds:.1f}s {'OK' if s.succeeded else 'FAIL'}")
            return 0
        else:
            print(f"[FAIL] {result.error_message}")
            for s in result.stages:
                print(f"       {s.name}: {s.elapsed_seconds:.1f}s {'OK' if s.succeeded else 'FAIL'}")
                if s.error_message:
                    print(f"         err: {s.error_message}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
