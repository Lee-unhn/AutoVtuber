"""PromptBuilder 測試 — 完全 mock Ollama HTTP 呼叫，不需要真實 ollama 服務。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import responses
import requests

from autovtuber.pipeline.job_spec import (
    EyeShape,
    FormInput,
    HairLength,
    HairStyle,
    Personality,
    StyleGenre,
)
from autovtuber.pipeline.prompt_builder import PromptBuilder
from autovtuber.safety.model_loader import ModelKind, ModelLoader


def make_form() -> FormInput:
    return FormInput(
        hair_color_hex="#5B3A29",
        hair_length=HairLength.LONG,
        hair_style=HairStyle.STRAIGHT,
        eye_color_hex="#3B5BA5",
        eye_shape=EyeShape.ALMOND,
        style=StyleGenre.ANIME_MODERN,
        personality=Personality.CALM_INTROVERTED,
        extra_freeform="圍巾",
    )


def make_loader() -> ModelLoader:
    """ModelLoader with mocked guard."""
    guard = MagicMock()
    guard.thresholds = MagicMock(cuda_memory_fraction=0.92)
    guard.check_or_raise.return_value = None
    ModelLoader._CURRENT = ModelKind.NONE
    ModelLoader._CURRENT_OBJ = None
    ModelLoader._CURRENT_UNLOADER = None
    return ModelLoader(guard)


@responses.activate
def test_auto_select_prefers_small_model():
    """有裝 gemma2:2b 應優先選；不選 default 的大模型。"""
    responses.add(
        responses.GET,
        "http://localhost:11434/api/tags",
        json={"models": [{"name": "gemma4:e4b"}, {"name": "gemma2:2b"}]},
        status=200,
    )
    loader = make_loader()
    pb = PromptBuilder(loader, MagicMock(), default_model="gemma4:e4b")
    assert pb.selected_model == "gemma2:2b"


@responses.activate
def test_falls_back_to_default_when_no_small_model():
    responses.add(
        responses.GET,
        "http://localhost:11434/api/tags",
        json={"models": [{"name": "gemma4:e4b"}]},
        status=200,
    )
    loader = make_loader()
    pb = PromptBuilder(loader, MagicMock(), default_model="gemma4:e4b")
    assert pb.selected_model == "gemma4:e4b"


@responses.activate
def test_health_check_returns_true_when_ollama_reachable():
    responses.add(
        responses.GET,
        "http://localhost:11434/api/tags",
        json={"models": [{"name": "gemma4:e4b"}]},
        status=200,
    )
    loader = make_loader()
    pb = PromptBuilder(loader, MagicMock(), default_model="gemma4:e4b")
    assert pb.health_check() is True


def test_health_check_returns_false_when_unreachable():
    loader = make_loader()
    with patch("requests.Session.get", side_effect=requests.ConnectionError):
        pb = PromptBuilder(loader, MagicMock(), default_model="gemma4:e4b")
        assert pb.health_check() is False


@responses.activate
def test_enhance_full_round_trip_with_unload_verification():
    """完整流程：tags → warm → chat → keep_alive=0 → poll /api/ps 直到清空。"""
    responses.add(
        responses.GET,
        "http://localhost:11434/api/tags",
        json={"models": [{"name": "gemma4:e4b"}]},
    )
    responses.add(
        responses.POST,
        "http://localhost:11434/api/generate",
        json={"response": "", "done": True},
    )
    responses.add(
        responses.POST,
        "http://localhost:11434/api/chat",
        json={
            "message": {
                "content": (
                    "POSITIVE: 1girl, long brown hair, blue eyes, scarf, masterpiece\n"
                    "NEGATIVE: nsfw, lowres, bad anatomy"
                )
            }
        },
    )
    # /api/ps 第一次回 still loaded，第二次回空 → 模擬卸載延遲
    responses.add(
        responses.GET,
        "http://localhost:11434/api/ps",
        json={"models": [{"name": "gemma4:e4b"}]},
    )
    responses.add(
        responses.GET,
        "http://localhost:11434/api/ps",
        json={"models": []},
    )

    loader = make_loader()
    pb = PromptBuilder(loader, MagicMock(check_or_raise=MagicMock(return_value=None)),
                       default_model="gemma4:e4b", unload_poll_timeout_seconds=3)

    result = pb.enhance(make_form())
    assert "1girl" in result.positive
    assert "nsfw" in result.negative
    # 確認結束後沒有駐留
    assert ModelLoader.currently_loaded() is ModelKind.NONE


@responses.activate
def test_response_parsing_handles_loose_format():
    """模型回應沒乖乖按格式時，應該還能容錯解析。"""
    responses.add(
        responses.GET,
        "http://localhost:11434/api/tags",
        json={"models": [{"name": "gemma4:e4b"}]},
    )
    loader = make_loader()
    pb = PromptBuilder(loader, MagicMock(), default_model="gemma4:e4b")

    pos, neg = PromptBuilder._parse_response(
        "POSITIVE: tag1, tag2\nNEGATIVE: bad1, bad2"
    )
    assert pos == "tag1, tag2"
    assert neg == "bad1, bad2"

    # 容錯
    pos2, neg2 = PromptBuilder._parse_response("first line\nsecond line")
    assert pos2 == "first line"
    assert neg2 == "second line"

    # 完全空 → 安全預設
    pos3, neg3 = PromptBuilder._parse_response("")
    assert "1girl" in pos3
    assert "nsfw" in neg3
