"""Authorized base model texture-atlas lookup tests."""
from __future__ import annotations

import json
from pathlib import Path

from autovtuber.vrm.texture_atlas import AtlasMap


def test_registered_base_uses_manifest_atlas_map(tmp_path: Path):
    (tmp_path / "OwnedBase.vrm").write_bytes(b"supplied")
    (tmp_path / "approved_models.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "model_id": "OwnedBase",
                        "usage_rights_confirmed": True,
                        "atlas": {
                            "face_skin_index": 3,
                            "hair_index": 7,
                            "eye_iris_index": 8,
                            "eye_white_index": None,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    atlas = AtlasMap.for_base_model("OwnedBase", tmp_path)

    assert atlas == AtlasMap(face_skin_index=3, hair_index=7, eye_iris_index=8)
