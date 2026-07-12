"""Base VRM asset policy used by UI, setup, and generation flows."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APPROVED_MODELS_MANIFEST = "approved_models.json"


@dataclass(frozen=True)
class BaseModelPolicy:
    model_id: str
    display_name: str
    commercial_allowed: bool
    notice: str
    atlas_indices: dict[str, int | None] | None = None
    license_reference: str = ""


_VROID_SAMPLE_NOTICE = (
    "VRoid AvatarSample is retained for legacy local validation only; "
    "it is not cleared for AutoVtuber product character-generation output."
)

BASE_MODEL_POLICIES: tuple[BaseModelPolicy, ...] = (
    BaseModelPolicy(
        "AvatarSample_A",
        "樣本 A - 女性 / 標準臉型 (研究驗證用)",
        False,
        _VROID_SAMPLE_NOTICE,
    ),
    BaseModelPolicy(
        "AvatarSample_B",
        "樣本 B - 女性 / 不同五官 (研究驗證用)",
        False,
        _VROID_SAMPLE_NOTICE,
    ),
    BaseModelPolicy(
        "AvatarSample_C",
        "樣本 C - 男性 / 較高身形 (研究驗證用)",
        False,
        _VROID_SAMPLE_NOTICE,
    ),
)


def _load_approved_models(base_models_dir: Path | None) -> tuple[BaseModelPolicy, ...]:
    """Load owner-approved bases recorded beside local, gitignored VRM assets."""
    if base_models_dir is None:
        return ()
    manifest_path = Path(base_models_dir) / APPROVED_MODELS_MANIFEST
    if not manifest_path.exists():
        return ()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("models", [])
    if not isinstance(entries, list):
        raise ValueError(f"{manifest_path} must contain a models list.")

    policies: list[BaseModelPolicy] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{manifest_path} contains an invalid model entry.")
        model_id = str(entry.get("model_id", "")).strip()
        if not model_id or not model_id.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"Invalid approved base model id: {model_id!r}")
        if not bool(entry.get("usage_rights_confirmed", False)):
            continue
        atlas = _validate_atlas(entry.get("atlas"), model_id)
        policies.append(
            BaseModelPolicy(
                model_id=model_id,
                display_name=str(entry.get("display_name") or model_id),
                commercial_allowed=True,
                notice="Rights confirmed by the project owner in the local approved-model registry.",
                atlas_indices=atlas,
                license_reference=str(entry.get("license_reference") or ""),
            )
        )
    return tuple(policies)


def _validate_atlas(value: Any, model_id: str) -> dict[str, int | None]:
    if not isinstance(value, dict):
        raise ValueError(f"Approved base {model_id!r} must include atlas indices.")
    result: dict[str, int | None] = {}
    for key in ("face_skin_index", "hair_index", "eye_iris_index"):
        index = value.get(key)
        if not isinstance(index, int) or index < 0:
            raise ValueError(f"Approved base {model_id!r} has invalid {key}.")
        result[key] = index
    eye_white = value.get("eye_white_index")
    if eye_white is not None and (not isinstance(eye_white, int) or eye_white < 0):
        raise ValueError(f"Approved base {model_id!r} has invalid eye_white_index.")
    result["eye_white_index"] = eye_white
    return result


def approved_base_models(base_models_dir: Path | None) -> tuple[BaseModelPolicy, ...]:
    """Return approved policies whose local VRM asset is present."""
    if base_models_dir is None:
        return ()
    directory = Path(base_models_dir)
    return tuple(
        policy for policy in _load_approved_models(directory)
        if (directory / f"{policy.model_id}.vrm").exists()
    )


def selectable_base_models(
    commercial_mode: bool,
    allow_restricted_samples_for_validation: bool = False,
    base_models_dir: Path | None = None,
) -> tuple[BaseModelPolicy, ...]:
    """Return models allowed in the requested operating mode."""
    approved = approved_base_models(base_models_dir)
    if allow_restricted_samples_for_validation and not commercial_mode:
        return approved + BASE_MODEL_POLICIES
    return approved


def has_commercial_base_model(base_models_dir: Path | None = None) -> bool:
    return bool(approved_base_models(base_models_dir))


def atlas_indices_for_base_model(model_id: str, base_models_dir: Path | None = None) -> dict[str, int | None] | None:
    for policy in approved_base_models(base_models_dir):
        if policy.model_id == model_id:
            return policy.atlas_indices
    return None


def assert_base_model_allowed(
    model_id: str,
    commercial_mode: bool,
    allow_restricted_samples_for_validation: bool = False,
    base_models_dir: Path | None = None,
) -> None:
    """Reject restricted samples unless explicitly enabled for legacy validation."""
    if any(policy.model_id == model_id for policy in approved_base_models(base_models_dir)):
        return
    policy = next((item for item in BASE_MODEL_POLICIES if item.model_id == model_id), None)
    if policy is None:
        raise PermissionError(
            f"Base model {model_id!r} is not registered in the asset policy. "
            "Add its license review before generation."
        )
    if policy.commercial_allowed:
        return
    if allow_restricted_samples_for_validation and not commercial_mode:
        return
    if not policy.commercial_allowed:
        raise PermissionError(
            f"Base model {model_id!r} is restricted to explicit legacy validation. "
            "Provide an owned or separately authorized VRM 0.x base model for generation."
        )
