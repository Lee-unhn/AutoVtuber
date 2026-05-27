# VTuber Quality Gate Test — 2026-05-21

## Goal

Verify whether AutoVtuber outputs are meaningful VTuber assets in the human sense, not just files that happen to save as `.vrm`.

A usable VTuber asset should at minimum have:

- VRM extension metadata
- humanoid bone mapping
- visible mesh geometry
- skinned mesh for body motion
- mouth visemes: `A/I/U/E/O`
- blink and basic expression clips
- ARKit / Perfect Sync compatible clips for modern face tracking workflows

## Finding

AutoVtuber's architecture is VTuber-aligned because it builds on VRoid base `.vrm` models and adds ARKit Perfect Sync clips. However, before this change the pipeline treated a successful `.vrm` save as success. That was too weak: a broken or incomplete VRM could pass even if it did not behave like a usable VTuber.

## Fix

Added a structural quality gate:

- `src/autovtuber/pipeline/vtuber_quality.py`
- `tests/test_vtuber_quality.py`

Integrated it into:

- `src/autovtuber/pipeline/vrm_assembler.py`

After `VRMAssembler` saves the output file, it reloads the VRM and validates the asset. If the model lacks humanoid bones, mouth shapes, blink/expression clips, mesh, or skinning, the job now fails instead of silently producing an unusable asset.

## Local Test Output

Generated test VRM:

```text
output/character_20260521_quality_fixed.vrm
```

Generated concept image:

```text
output/character_20260521_quality_fixed_concept.png
```

Generated six-view screenshots:

```text
output/quality_fixed_views/character_20260521_quality_fixed_front.png
output/quality_fixed_views/character_20260521_quality_fixed_back.png
output/quality_fixed_views/character_20260521_quality_fixed_left.png
output/quality_fixed_views/character_20260521_quality_fixed_right.png
output/quality_fixed_views/character_20260521_quality_fixed_top.png
output/quality_fixed_views/character_20260521_quality_fixed_bottom.png
output/quality_fixed_views/character_20260521_quality_fixed_six_views.png
```

Packaged local artifact:

```text
output/character_20260521_quality_fixed_package.zip
```

These output files are runtime artifacts and are intentionally ignored by Git.

## Quality Gate Result

```text
passed=True
score=10.0
human_bone_count=54
missing_required_bones=[]
blendshape_count=67
emotion_clip_count=5
arkit_like_clip_count=52
mesh_count=3
skin_count=3
primitive_count=90
morph_target_count=560
```

Interpretation: the generated asset passes the minimum structural definition of a VTuber-ready VRM.

## Render Preview

Added a lightweight geometry preview renderer:

```text
scripts/render_vrm_six_views.py
```

It renders front, back, left, right, top, and bottom views without requiring OpenGL. This is meant for CI or constrained machines. It is a geometry/material sanity preview, not a full VSeeFace/Warudo toon-shader render.

## Commands Used

Generate test VRM from the sample concept and VRoid base:

```bash
PYTHONPATH=src /Users/shixi/Desktop/SadTalker-first/SadTalker/venv/bin/python - <<'PY'
from pathlib import Path
from PIL import Image
from autovtuber.pipeline.job_spec import FormInput, HairLength, HairStyle, EyeShape, StyleGenre, Personality
from autovtuber.pipeline.vrm_assembler import VRMAssembler
from autovtuber.pipeline.vtuber_quality import VtuberQualityGate

root = Path('/Users/shixi/Desktop/AutoVtuber')
out = root / 'output' / 'character_20260521_quality_fixed.vrm'
concept = Image.open(root / 'docs/images/sample_concept.png').convert('RGB')
form = FormInput(
    nickname='quality_fixed',
    hair_color_hex='#5B3A29',
    hair_length=HairLength.LONG,
    hair_style=HairStyle.STRAIGHT,
    eye_color_hex='#3B5BA5',
    eye_shape=EyeShape.ALMOND,
    style=StyleGenre.ANIME_MODERN,
    personality=Personality.CALM_INTROVERTED,
    extra_freeform='quality gate test',
    base_model_id='AvatarSample_A',
)
assembler = VRMAssembler(
    root / 'assets/base_models',
    root / 'models',
    allow_restricted_samples_for_validation=True,
)
result = assembler.assemble(form=form, sdxl_face_image=concept, output_path=out, tsr_mesh=None, mesh_fitter=None)
report = VtuberQualityGate().validate_path(result)
print(result)
print(report.passed, report.score)
print(report.details)
PY
```

Render six views:

```bash
PYTHONPATH=src /Users/shixi/Desktop/SadTalker-first/SadTalker/venv/bin/python \
  scripts/render_vrm_six_views.py \
  output/character_20260521_quality_fixed.vrm \
  output/quality_fixed_views
```

Run focused tests:

```bash
PYTHONPATH=src /Users/shixi/Desktop/SadTalker-first/SadTalker/venv/bin/python -m pytest \
  tests/test_vrm_io.py \
  tests/test_arkit_blendshape_writer.py \
  tests/test_vtuber_quality.py
```

Result:

```text
22 passed
```

## Limits

This local run was performed on macOS with Python 3.9 using an existing helper venv. The full AutoVtuber end-to-end SDXL/TripoSR path still requires the intended Windows + Python 3.12 + NVIDIA CUDA environment. This test validates the corrected VRM assembly and VTuber structural quality gate, not the full GPU image-generation pipeline.

## Notes For GitHub

Recommended files to commit:

- `.gitignore`
- `src/autovtuber/pipeline/vtuber_quality.py`
- `src/autovtuber/pipeline/vrm_assembler.py`
- `tests/test_vtuber_quality.py`
- `scripts/render_vrm_six_views.py`
- `docs/VTUBER_QUALITY_GATE_TEST_2026-05-21.md`

Do not commit:

- `output/*`
- `.matplotlib/`
- downloaded `assets/base_models/*.vrm`
