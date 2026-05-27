"""Commercial base-model policy tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from autovtuber.config.asset_policy import (
    assert_base_model_allowed,
    atlas_indices_for_base_model,
    has_commercial_base_model,
    selectable_base_models,
)


def register_owned_base(tmp_path: Path) -> Path:
    base_dir = tmp_path / "base_models"
    base_dir.mkdir()
    (base_dir / "OwnedBase.vrm").write_bytes(b"locally supplied VRM")
    (base_dir / "approved_models.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "model_id": "OwnedBase",
                        "display_name": "Owned Base",
                        "usage_rights_confirmed": True,
                        "license_reference": "contract-001",
                        "atlas": {
                            "face_skin_index": 11,
                            "hair_index": 20,
                            "eye_iris_index": 9,
                            "eye_white_index": 4,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return base_dir


def test_legacy_mode_keeps_sample_models_available_for_existing_validation():
    models = selectable_base_models(
        commercial_mode=False,
        allow_restricted_samples_for_validation=True,
    )
    assert {model.model_id for model in models} == {
        "AvatarSample_A",
        "AvatarSample_B",
        "AvatarSample_C",
    }


def test_commercial_mode_exposes_no_unapproved_sample_model():
    assert selectable_base_models(commercial_mode=True) == ()
    assert has_commercial_base_model() is False


def test_registered_owned_base_is_selectable_and_allowed(tmp_path: Path):
    base_dir = register_owned_base(tmp_path)

    models = selectable_base_models(commercial_mode=True, base_models_dir=base_dir)

    assert [model.model_id for model in models] == ["OwnedBase"]
    assert has_commercial_base_model(base_dir) is True
    assert atlas_indices_for_base_model("OwnedBase", base_dir) == {
        "face_skin_index": 11,
        "hair_index": 20,
        "eye_iris_index": 9,
        "eye_white_index": 4,
    }
    assert_base_model_allowed("OwnedBase", commercial_mode=True, base_models_dir=base_dir)


def test_registry_without_local_vrm_does_not_unlock_generation(tmp_path: Path):
    base_dir = register_owned_base(tmp_path)
    (base_dir / "OwnedBase.vrm").unlink()

    assert selectable_base_models(commercial_mode=False, base_models_dir=base_dir) == ()
    with pytest.raises(PermissionError, match="not registered in the asset policy"):
        assert_base_model_allowed("OwnedBase", commercial_mode=False, base_models_dir=base_dir)


def test_default_mode_rejects_vroid_sample_output():
    with pytest.raises(PermissionError, match="restricted to explicit legacy validation"):
        assert_base_model_allowed("AvatarSample_A", commercial_mode=False)


def test_unregistered_model_is_rejected_until_license_reviewed():
    with pytest.raises(PermissionError, match="not registered in the asset policy"):
        assert_base_model_allowed("MyUnreviewedBase", commercial_mode=False)


def test_commercial_mode_rejects_vroid_sample_even_if_legacy_flag_is_true():
    with pytest.raises(PermissionError, match="restricted to explicit legacy validation"):
        assert_base_model_allowed(
            "AvatarSample_A",
            commercial_mode=True,
            allow_restricted_samples_for_validation=True,
        )


def test_legacy_validation_can_read_existing_sample_asset_only_when_enabled():
    with pytest.raises(PermissionError):
        assert_base_model_allowed("AvatarSample_A", commercial_mode=False)
    assert_base_model_allowed(
        "AvatarSample_A",
        commercial_mode=False,
        allow_restricted_samples_for_validation=True,
    )
