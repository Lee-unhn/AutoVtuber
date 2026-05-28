"""Inspect a VRM file and emit texture-atlas registration notes."""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autovtuber.vrm.vrm_io import VRMFile  # noqa: E402


def _guess_slot(name: str) -> str:
    lower = name.lower()
    if "face" in lower and "mouth" not in lower:
        return "face_skin candidate"
    if "skin" in lower:
        return "face_skin candidate"
    if "hair" in lower:
        return "hair candidate"
    if "iris" in lower:
        return "eye_iris candidate"
    if "eyewhite" in lower or ("eye" in lower and "white" in lower):
        return "eye_white candidate"
    if "eye" in lower:
        return "eye candidate"
    if "body" in lower or "cloth" in lower or "wear" in lower:
        return "body/clothing"
    return ""


def _image_rows(vrm: VRMFile) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for entry in vrm.list_images():
        index = int(entry["index"])
        width = height = "unreadable"
        try:
            image = vrm.get_image_pil(index)
            width, height = image.size
        except Exception as exc:  # noqa: BLE001
            width = height = type(exc).__name__
        name = str(entry.get("name") or "")
        rows.append(
            {
                "index": index,
                "name": name,
                "mime": str(entry.get("mimeType") or ""),
                "size": int(entry.get("byte_size") or 0),
                "width": width,
                "height": height,
                "guess": _guess_slot(name),
            }
        )
    return rows


def _markdown(source: Path, vrm: VRMFile, model_id_hint: str) -> str:
    rows = _image_rows(vrm)
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    table = [
        "| index | name | mime | pixels | bytes | guess |",
        "|---:|---|---|---:|---:|---|",
    ]
    for row in rows:
        table.append(
            "| {index} | {name} | {mime} | {width}x{height} | {size} | {guess} |".format(
                **row
            )
        )

    return "\n".join(
        [
            f"# VRM Atlas Inspect - {source.name}",
            "",
            f"- Source: `{source}`",
            f"- SHA-256: `{sha256}`",
            f"- VRM version: `{vrm.vrm_version}`",
            f"- Image count: `{len(rows)}`",
            "",
            "## Texture Images",
            "",
            *table,
            "",
            "## Registration Draft",
            "",
            "After confirming the correct indices visually, register the base with:",
            "",
            "```bash",
            "PYTHONPATH=src python scripts/register_authorized_base.py \\",
            f"  --source {source} \\",
            f"  --model-id {model_id_hint} \\",
            f"  --display-name \"{model_id_hint}\" \\",
            "  --license-reference \"<license document or internal record>\" \\",
            "  --face-skin-index <index> \\",
            "  --hair-index <index> \\",
            "  --eye-iris-index <index> \\",
            "  --eye-white-index <index-or-omit> \\",
            "  --confirm-rights",
            "```",
            "",
            "> This report only helps choose texture indices. It does not prove asset rights.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect VRM image indices for AutoVtuber atlas registration.")
    parser.add_argument("--source", type=Path, required=True, help="Path to a .vrm file.")
    parser.add_argument("--out", type=Path, help="Optional Markdown output path.")
    parser.add_argument("--model-id", default="OwnedBase", help="Model id hint used in the registration draft.")
    args = parser.parse_args()

    if not args.source.exists():
        parser.error(f"--source does not exist: {args.source}")
    vrm = VRMFile.load(args.source)
    report = _markdown(args.source, vrm, args.model_id)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"Wrote atlas report: {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
