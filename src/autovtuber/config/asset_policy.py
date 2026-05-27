"""Base VRM asset policy used by UI and setup flows."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BaseModelPolicy:
    model_id: str
    display_name: str
    commercial_allowed: bool
    notice: str


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


def selectable_base_models(
    commercial_mode: bool,
    allow_restricted_samples_for_validation: bool = False,
) -> tuple[BaseModelPolicy, ...]:
    """Return models allowed in the requested operating mode."""
    if allow_restricted_samples_for_validation and not commercial_mode:
        return BASE_MODEL_POLICIES
    return tuple(policy for policy in BASE_MODEL_POLICIES if policy.commercial_allowed)


def has_commercial_base_model() -> bool:
    return any(policy.commercial_allowed for policy in BASE_MODEL_POLICIES)


def assert_base_model_allowed(
    model_id: str,
    commercial_mode: bool,
    allow_restricted_samples_for_validation: bool = False,
) -> None:
    """Reject restricted samples unless explicitly enabled for legacy validation."""
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
