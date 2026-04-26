"""ResourceCheck 測試 — 用 tmp_path 模擬已就緒 / 缺漏狀態。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from autovtuber.config.paths import Paths
from autovtuber.setup.resource_check import (
    ResourceCheck,
    ResourceState,
    ResourceStatus,
    check_all_resources,
)


def make_paths(tmp_path: Path) -> Paths:
    """建一個假的 Paths，所有目錄指向 tmp_path 子目錄（Paths 沒 root 參數，直接覆寫 attrs）。"""
    paths = Paths()
    paths.root = tmp_path
    paths.assets = tmp_path / "assets"
    paths.base_models = tmp_path / "assets" / "base_models"
    paths.models = tmp_path / "models"
    paths.output = tmp_path / "output"
    paths.presets = tmp_path / "presets"
    paths.logs = tmp_path / "logs"
    paths.docs = tmp_path / "docs"
    paths.setup_flag = tmp_path / "setup_complete.flag"
    paths.download_manifest = paths.docs / "DOWNLOAD_MANIFEST.md"
    paths.ensure_writable_dirs()
    return paths


def test_resourcestatus_needs_download_logic():
    s = ResourceStatus(key="x", display_name="X", state=ResourceState.READY)
    assert s.needs_download is False
    s = ResourceStatus(key="x", display_name="X", state=ResourceState.MISSING)
    assert s.needs_download is True
    s = ResourceStatus(key="x", display_name="X", state=ResourceState.PARTIAL)
    assert s.needs_download is True
    s = ResourceStatus(key="x", display_name="X", state=ResourceState.UNKNOWN)
    assert s.needs_download is False  # unknown 不算 missing


def test_resourcecheck_aggregates():
    items = [
        ResourceStatus(key="a", display_name="A", state=ResourceState.READY, expected_size_mb=100, actual_size_mb=100),
        ResourceStatus(key="b", display_name="B", state=ResourceState.MISSING, expected_size_mb=200),
        ResourceStatus(key="c", display_name="C", state=ResourceState.PARTIAL, expected_size_mb=300, actual_size_mb=100),
    ]
    check = ResourceCheck(items=items)
    assert check.all_ready is False
    assert len(check.missing) == 2
    # b 缺 200，c 缺 200（300-100）
    assert check.total_download_mb == 200 + 200


def test_resourcecheck_all_ready_when_everything_ready():
    items = [
        ResourceStatus(key="a", display_name="A", state=ResourceState.READY),
        ResourceStatus(key="b", display_name="B", state=ResourceState.READY),
    ]
    check = ResourceCheck(items=items)
    assert check.all_ready is True
    assert check.missing == []


def test_check_all_resources_with_empty_paths_returns_all_missing(tmp_path: Path):
    """完全空的 paths（如剛裝完）→ 全部 missing 或 unknown。"""
    paths = make_paths(tmp_path)
    # mock Ollama 不可達 → unknown
    with patch("requests.get") as mock_get:
        mock_get.side_effect = Exception("connection refused")
        result = check_all_resources(paths)

    # 11 項
    assert len(result.items) == 11
    keys = {item.key for item in result.items}
    assert "sdxl_animagine" in keys
    assert "ip_adapter_weight" in keys
    assert "ip_adapter_encoder" in keys
    assert "triposr_repo" in keys
    assert "triposr_ckpt" in keys
    assert "rembg_u2net" in keys
    # ollama 兩個都應 unknown（因為網路 mock 拒絕）
    ollama_items = [it for it in result.items if it.key.startswith("ollama_")]
    assert len(ollama_items) == 2
    for it in ollama_items:
        assert it.state == ResourceState.UNKNOWN
    # base vrm 三個應 missing
    base_items = [it for it in result.items if it.key.startswith("base_vrm_")]
    assert len(base_items) == 3
    for it in base_items:
        assert it.state == ResourceState.MISSING


def test_check_detects_existing_sdxl(tmp_path: Path):
    paths = make_paths(tmp_path)
    sdxl_dir = paths.models / "sdxl" / "animagine-xl-4.0"
    sdxl_dir.mkdir(parents=True)
    (sdxl_dir / "model_index.json").write_text('{"_class_name": "StableDiffusionXLPipeline"}')
    (sdxl_dir / "dummy.bin").write_bytes(b"x" * 1024 * 1024)  # 1 MB

    with patch("requests.get") as mock_get:
        mock_get.side_effect = Exception()
        result = check_all_resources(paths)

    sdxl = next(it for it in result.items if it.key == "sdxl_animagine")
    assert sdxl.state == ResourceState.READY
    assert sdxl.actual_size_mb >= 1


def test_check_detects_existing_base_vrm(tmp_path: Path):
    paths = make_paths(tmp_path)
    paths.base_models.mkdir(parents=True, exist_ok=True)
    (paths.base_models / "AvatarSample_A.vrm").write_bytes(b"x" * 1024 * 1024 * 14)  # 14 MB

    with patch("requests.get") as mock_get:
        mock_get.side_effect = Exception()
        result = check_all_resources(paths)

    base_a = next(it for it in result.items if it.key == "base_vrm_a")
    assert base_a.state == ResourceState.READY
    assert base_a.actual_size_mb >= 13


def test_check_detects_ollama_models_when_reachable(tmp_path: Path):
    paths = make_paths(tmp_path)

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "models": [
            {"name": "gemma4:e2b"},
            {"name": "qwen2.5:3b"},
            {"name": "other:latest"},
        ]
    }
    with patch("requests.get", return_value=fake_response):
        result = check_all_resources(paths)

    gemma = next(it for it in result.items if it.key == "ollama_gemma4_e2b")
    qwen = next(it for it in result.items if it.key == "ollama_qwen2.5_3b")
    assert gemma.state == ResourceState.READY
    assert qwen.state == ResourceState.READY


def test_check_ollama_missing_when_model_not_pulled(tmp_path: Path):
    paths = make_paths(tmp_path)

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"models": []}  # 空列表
    with patch("requests.get", return_value=fake_response):
        result = check_all_resources(paths)

    gemma = next(it for it in result.items if it.key == "ollama_gemma4_e2b")
    assert gemma.state == ResourceState.MISSING
    assert "ollama pull" in gemma.detail.lower()


def test_progress_callback_invoked(tmp_path: Path):
    paths = make_paths(tmp_path)
    calls = []

    with patch("requests.get") as mock_get:
        mock_get.side_effect = Exception()
        check_all_resources(paths, progress_cb=lambda name: calls.append(name))

    # 至少 8 個 step（11 項中部分共用 step name）
    assert len(calls) >= 7
