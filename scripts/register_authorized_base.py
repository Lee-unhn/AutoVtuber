"""Register an owner-authorized VRM 0.x base for AutoVtuber product generation."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autovtuber.config.asset_policy import APPROVED_MODELS_MANIFEST  # noqa: E402
from autovtuber.vrm.vrm_io import VRMFile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Register an authorized VRM 0.x base model.")
    parser.add_argument("--source", type=Path, required=True, help="Path to the licensed .vrm file.")
    parser.add_argument("--model-id", required=True, help="Stable model id, for example MyStudioBaseF.")
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--license-reference", required=True, help="License document, contract, or asset receipt reference.")
    parser.add_argument("--face-skin-index", type=int, required=True)
    parser.add_argument("--hair-index", type=int, required=True)
    parser.add_argument("--eye-iris-index", type=int, required=True)
    parser.add_argument("--eye-white-index", type=int)
    parser.add_argument(
        "--confirm-rights",
        action="store_true",
        help="Confirm that you own or hold rights to use this base in character-generation output.",
    )
    args = parser.parse_args()
    if not args.confirm_rights:
        parser.error("--confirm-rights is required before registering a product base model.")
    if not args.model_id.replace("_", "").replace("-", "").isalnum():
        parser.error("--model-id must contain letters, numbers, underscore, or hyphen only.")
    if args.source.suffix.lower() != ".vrm" or not args.source.exists():
        parser.error("--source must point to an existing .vrm file.")

    vrm = VRMFile.load(args.source)
    if vrm.vrm_version != "0.x":
        parser.error(f"AutoVtuber currently requires VRM 0.x; got {vrm.vrm_version}.")
    for index in (args.face_skin_index, args.hair_index, args.eye_iris_index, args.eye_white_index):
        if index is not None:
            vrm.get_image_pil(index).verify()

    destination_dir = ROOT / "assets" / "base_models"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{args.model_id}.vrm"
    if args.source.resolve() != destination.resolve():
        shutil.copy2(args.source, destination)

    manifest_path = destination_dir / APPROVED_MODELS_MANIFEST
    payload = {"models": []}
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    models = [entry for entry in payload.get("models", []) if entry.get("model_id") != args.model_id]
    models.append(
        {
            "model_id": args.model_id,
            "display_name": args.display_name,
            "usage_rights_confirmed": True,
            "license_reference": args.license_reference,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "atlas": {
                "face_skin_index": args.face_skin_index,
                "hair_index": args.hair_index,
                "eye_iris_index": args.eye_iris_index,
                "eye_white_index": args.eye_white_index,
            },
        }
    )
    manifest_path.write_text(json.dumps({"models": models}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Registered product base: {destination}")
    print(f"Rights registry: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
