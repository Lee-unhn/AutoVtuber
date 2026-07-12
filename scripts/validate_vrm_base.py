"""Validate whether a candidate VRM is structurally suitable as an AutoVtuber base."""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autovtuber.pipeline.vtuber_quality import VtuberQualityGate  # noqa: E402
from autovtuber.vrm.vrm_io import VRMFile  # noqa: E402


def _issue_table(issues) -> list[str]:
    if not issues:
        return ["| severity | code | message |", "|---|---|---|", "| pass | none | No issues found. |"]
    rows = ["| severity | code | message |", "|---|---|---|"]
    for issue in issues:
        rows.append(f"| {issue.severity} | `{issue.code}` | {issue.message} |")
    return rows


def _markdown(source: Path) -> str:
    vrm = VRMFile.load(source)
    report = VtuberQualityGate().validate_vrm(vrm)
    details = report.details
    verdict = "PASS - structurally usable as a VTuber base" if report.passed else "FAIL - fix before base registration"
    license_note = (
        "This technical report does not grant rights. "
        "A base still needs owner confirmation and license evidence before product use."
    )

    return "\n".join(
        [
            f"# VRM Base Validation - {source.name}",
            "",
            f"- Source: `{source}`",
            f"- SHA-256: `{hashlib.sha256(source.read_bytes()).hexdigest()}`",
            f"- VRM version: `{vrm.vrm_version}`",
            f"- Verdict: **{verdict}**",
            f"- Quality score: `{report.score:.1f}/10`",
            "",
            "## Structural Details",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Human bones | {details.get('human_bone_count', 0)} |",
            f"| Blendshape clips | {details.get('blendshape_count', 0)} |",
            f"| Emotion clips | {details.get('emotion_clip_count', 0)} |",
            f"| ARKit-like clips | {details.get('arkit_like_clip_count', 0)} |",
            f"| Meshes | {details.get('mesh_count', 0)} |",
            f"| Skins | {details.get('skin_count', 0)} |",
            f"| Primitives | {details.get('primitive_count', 0)} |",
            f"| Morph targets | {details.get('morph_target_count', 0)} |",
            "",
            "## Issues",
            "",
            *_issue_table(report.issues),
            "",
            "## Next Steps",
            "",
            "1. If this report fails, fix the VRM in the modeling tool before registering it.",
            "2. Run `scripts/inspect_vrm_atlas.py` to identify texture indices.",
            "3. Register only after rights are confirmed with `scripts/register_authorized_base.py`.",
            "4. Generate one AutoVtuber character and run Windows/VDrama acceptance.",
            "",
            f"> {license_note}",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a candidate VRM base for AutoVtuber.")
    parser.add_argument("--source", type=Path, required=True, help="Path to a .vrm file.")
    parser.add_argument("--out", type=Path, help="Optional Markdown output path.")
    args = parser.parse_args()

    if not args.source.exists():
        parser.error(f"--source does not exist: {args.source}")
    report = _markdown(args.source)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"Wrote base validation report: {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
