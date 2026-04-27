"""R1 ARKit Perfect Sync blendshape writer 測試 — 用 mock VRM 驗 52 個 clip 加進 extension。"""
from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from autovtuber.vrm.blendshape_writer import ARKIT_TO_VROID, VRMBlendshapeWriter


def make_fake_vrm() -> MagicMock:
    """造一個假 VRMFile，extensions 含 minimal blendShapeMaster。"""
    vrm = MagicMock()
    vrm.raw = MagicMock()
    vrm.raw.extensions = {
        "VRM": {
            "blendShapeMaster": {
                "blendShapeGroups": [
                    {"name": "Joy", "presetName": "joy", "binds": [{"mesh": 0, "index": 5, "weight": 100.0}]},
                    {"name": "Angry", "presetName": "angry", "binds": [{"mesh": 0, "index": 6, "weight": 100.0}]},
                    {"name": "Sorrow", "presetName": "sorrow", "binds": [{"mesh": 0, "index": 7, "weight": 100.0}]},
                    {"name": "Fun", "presetName": "fun", "binds": [{"mesh": 0, "index": 8, "weight": 100.0}]},
                    {"name": "A", "presetName": "a", "binds": [{"mesh": 0, "index": 1, "weight": 100.0}]},
                    {"name": "I", "presetName": "i", "binds": [{"mesh": 0, "index": 2, "weight": 100.0}]},
                    {"name": "U", "presetName": "u", "binds": [{"mesh": 0, "index": 3, "weight": 100.0}]},
                    {"name": "Blink_L", "presetName": "blink_l", "binds": [{"mesh": 0, "index": 9, "weight": 100.0}]},
                    {"name": "Blink_R", "presetName": "blink_r", "binds": [{"mesh": 0, "index": 10, "weight": 100.0}]},
                    {"name": "Surprised", "presetName": "unknown", "binds": [{"mesh": 0, "index": 11, "weight": 100.0}]},
                ],
            },
        },
    }
    return vrm


def test_arkit_to_vroid_has_52_entries():
    """ARKit Perfect Sync 標準是 52 個 blendshape。"""
    assert len(ARKIT_TO_VROID) == 52


def test_arkit_to_vroid_has_unique_names():
    names = [n for n, _, _ in ARKIT_TO_VROID]
    assert len(names) == len(set(names)), "ARKit names should be unique"


def test_add_arkit_clips_adds_52_to_existing():
    vrm = make_fake_vrm()
    initial = len(vrm.raw.extensions["VRM"]["blendShapeMaster"]["blendShapeGroups"])
    added = VRMBlendshapeWriter.add_arkit_clips(vrm)
    assert added == 52
    final = len(vrm.raw.extensions["VRM"]["blendShapeMaster"]["blendShapeGroups"])
    assert final == initial + 52


def test_clip_names_match_arkit_standard():
    vrm = make_fake_vrm()
    VRMBlendshapeWriter.add_arkit_clips(vrm)
    groups = vrm.raw.extensions["VRM"]["blendShapeMaster"]["blendShapeGroups"]
    new_names = [grp["name"] for grp in groups[10:]]  # 跳前 10 個既有
    expected = [n for n, _, _ in ARKIT_TO_VROID]
    assert new_names == expected


def test_smile_left_binds_to_joy_with_60_strength():
    """mouthSmileLeft 應該對應 Joy 的 60% strength。"""
    vrm = make_fake_vrm()
    VRMBlendshapeWriter.add_arkit_clips(vrm)
    groups = vrm.raw.extensions["VRM"]["blendShapeMaster"]["blendShapeGroups"]
    smile = next(g for g in groups if g["name"] == "mouthSmileLeft")
    assert len(smile["binds"]) == 1
    bind = smile["binds"][0]
    # Joy 原 weight 100 → 60% 應變成 60
    assert bind["weight"] == 60.0
    assert bind["index"] == 5  # Joy 的 morph index


def test_jaw_open_binds_to_a_full_strength():
    vrm = make_fake_vrm()
    VRMBlendshapeWriter.add_arkit_clips(vrm)
    groups = vrm.raw.extensions["VRM"]["blendShapeMaster"]["blendShapeGroups"]
    jaw = next(g for g in groups if g["name"] == "jawOpen")
    assert jaw["binds"][0]["weight"] == 100.0
    assert jaw["binds"][0]["index"] == 1  # A 的 morph index


def test_eye_blink_left_full_strength():
    vrm = make_fake_vrm()
    VRMBlendshapeWriter.add_arkit_clips(vrm)
    groups = vrm.raw.extensions["VRM"]["blendShapeMaster"]["blendShapeGroups"]
    blink = next(g for g in groups if g["name"] == "eyeBlinkLeft")
    assert blink["binds"][0]["weight"] == 100.0
    assert blink["binds"][0]["index"] == 9  # Blink_L


def test_unmapped_clips_have_empty_binds():
    """eyeLookUpLeft / jawForward / tongueOut 等沒對應 VRoid morph → binds 應為空。"""
    vrm = make_fake_vrm()
    VRMBlendshapeWriter.add_arkit_clips(vrm)
    groups = vrm.raw.extensions["VRM"]["blendShapeMaster"]["blendShapeGroups"]
    for unmapped_name in ["eyeLookUpLeft", "jawForward", "tongueOut", "mouthLeft"]:
        clip = next(g for g in groups if g["name"] == unmapped_name)
        assert clip["binds"] == [], f"{unmapped_name} should have empty binds"


def test_skip_existing_clips_no_overwrite():
    """已存在的 ARKit name（手動編輯 VRM 加過）不會被覆蓋。"""
    vrm = make_fake_vrm()
    # 預先加一個 mouthSmileLeft 模擬使用者已編輯過
    pre_existing = {
        "name": "mouthSmileLeft",
        "presetName": "unknown",
        "binds": [{"mesh": 0, "index": 99, "weight": 50.0}],
    }
    vrm.raw.extensions["VRM"]["blendShapeMaster"]["blendShapeGroups"].append(pre_existing)

    added = VRMBlendshapeWriter.add_arkit_clips(vrm)
    # 應該只加 51 個（mouthSmileLeft 已存在）
    assert added == 51

    # 確認原 mouthSmileLeft 沒被覆蓋
    groups = vrm.raw.extensions["VRM"]["blendShapeMaster"]["blendShapeGroups"]
    smiles = [g for g in groups if g["name"] == "mouthSmileLeft"]
    assert len(smiles) == 1
    assert smiles[0]["binds"][0]["index"] == 99  # 原值


def test_no_blendshape_master_returns_zero():
    vrm = MagicMock()
    vrm.raw = MagicMock()
    vrm.raw.extensions = {"VRM": {}}
    added = VRMBlendshapeWriter.add_arkit_clips(vrm)
    assert added == 0


def test_no_vrm_extension_returns_zero():
    vrm = MagicMock()
    vrm.raw = MagicMock()
    vrm.raw.extensions = {}
    added = VRMBlendshapeWriter.add_arkit_clips(vrm)
    assert added == 0


def test_clip_metadata_format_matches_vrm_spec():
    """每個 group 應有 name / presetName / binds / materialValues / isBinary。"""
    vrm = make_fake_vrm()
    VRMBlendshapeWriter.add_arkit_clips(vrm)
    groups = vrm.raw.extensions["VRM"]["blendShapeMaster"]["blendShapeGroups"]
    for grp in groups[-52:]:  # 只看新增的
        assert "name" in grp
        assert "presetName" in grp
        assert "binds" in grp
        assert "materialValues" in grp
        assert "isBinary" in grp
        assert grp["presetName"] == "unknown"  # ARKit 不在 VRM 0.x 預設 preset 列表
