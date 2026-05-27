"""Commercial base-model policy tests."""
from __future__ import annotations

import pytest

from autovtuber.config.asset_policy import (
    assert_base_model_allowed,
    has_commercial_base_model,
    selectable_base_models,
)


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
