"""PersonaGenerator 測試 — 完全 mock Ollama HTTP 呼叫。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests
import responses

from autovtuber.pipeline.job_spec import (
    EyeShape,
    FormInput,
    HairLength,
    HairStyle,
    Personality,
    StyleGenre,
)
from autovtuber.pipeline.persona_generator import OllamaSession, PersonaGenerator
from autovtuber.pipeline.prompt_builder import PromptBuilder
from autovtuber.safety.model_loader import ModelKind, ModelLoader


def make_form() -> FormInput:
    return FormInput(
        nickname="米菈",
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
    guard = MagicMock()
    guard.thresholds = MagicMock(cuda_memory_fraction=0.92)
    guard.check_or_raise.return_value = None
    guard.abort_event = MagicMock(is_set=MagicMock(return_value=False))
    ModelLoader._CURRENT = ModelKind.NONE
    ModelLoader._CURRENT_OBJ = None
    ModelLoader._CURRENT_UNLOADER = None
    return ModelLoader(guard)


_VALID_PERSONA = """## 基本資料
- 名字：米菈
- 年齡：18
- 身高：158 cm
- 生日：4/15

## 個性詳細
- 沉穩冷靜
- 喜歡深度對話
- 獨處能充電
- 面對突發狀況先分析
- 完美主義可控

## 背景故事
米菈是現代都市的學生，因為一次直播試播被觀眾留下。她從小喜歡夜晚與雨聲，
覺得世界在那種時候才慢下來。直播成為她整理思緒的方式，也意外讓她接住了
許多和她一樣需要安靜的人。她的目標是把這份溫度持續做下去，並有一天舉辦
線下見面會，跟那些隔著螢幕陪伴的人有真實的擁抱。雖然害怕被看見全部的自己，
但她相信一點點地分享也是一種勇氣。

## 興趣與嗜好
- 收集老物件
- 看電影寫長心得
- 學新語言
- 散步拍街景
- 嘗試做料理

## 口頭禪
- 「⋯⋯讓我想一下喔」
- 「謝謝你陪我到這裡」
- 「欸這個還滿有意思的」

## 直播風格建議
適合做雜談 + 解謎遊戲 + 偶爾的歌回。節目企劃：
1. 米菈的深夜信箱
2. 一起學一個新東西
3. 散步直播

## 與觀眾互動方式
稱呼粉絲為米菈的朋友，互動偏溫和、會記常駐觀眾暱稱。
收到 SC 會稍停頓再認真回應。
"""


@responses.activate
def test_template_fallback_contains_all_required_headings():
    """Ollama 不可用時，template fallback 必須包含七個章節。"""
    md = PersonaGenerator.template_fallback(make_form())
    for heading in PersonaGenerator._REQUIRED_HEADINGS:
        assert heading in md, f"missing {heading}"
    assert "米菈" in md  # nickname 應出現


@responses.activate
def test_template_fallback_uses_personality_descriptions():
    """每個 personality 都有對應 fallback 描述。"""
    form = make_form()
    md = PersonaGenerator.template_fallback(form)
    # CALM_INTROVERTED 的特徵字串
    assert "獨處時能完整充電" in md


def test_post_process_strips_markdown_fence():
    """LLM 常在輸出加 ```markdown ... ``` 圍欄，要清掉。"""
    raw = "```markdown\n## 基本資料\n- 名字：A\n```"
    cleaned = PersonaGenerator._post_process(raw)
    assert cleaned.startswith("## 基本資料")
    assert "```" not in cleaned


def test_post_process_strips_preamble():
    """LLM 有時會加開場白；應該從第一個 ## 起截。"""
    raw = "好的，以下是您的人設：\n\n## 基本資料\n- 名字：A"
    cleaned = PersonaGenerator._post_process(raw)
    assert cleaned.startswith("## 基本資料")
    assert "好的" not in cleaned


def test_validate_raises_on_missing_heading():
    """少了任何必要章節就 raise。"""
    incomplete = "## 基本資料\n- 名字：A\n## 個性詳細\n- 一條"
    with pytest.raises(ValueError, match="missing headings"):
        PersonaGenerator._validate_or_raise(incomplete)


def test_validate_raises_on_too_short():
    short = "\n".join(f"## {h.removeprefix('## ')}\n內容" for h in PersonaGenerator._REQUIRED_HEADINGS)
    with pytest.raises(ValueError, match="too short"):
        PersonaGenerator._validate_or_raise(short)


def test_validate_passes_on_valid_persona():
    PersonaGenerator._validate_or_raise(_VALID_PERSONA)  # should not raise


@responses.activate
def test_generate_with_session_success():
    """LLM 回 valid markdown → 直接返回。"""
    responses.add(
        responses.POST,
        "http://localhost:11434/api/chat",
        json={"message": {"content": _VALID_PERSONA}},
    )
    info = OllamaSession(
        base_url="http://localhost:11434",
        model="gemma4:e2b",
        session=requests.Session(),
        timeout_seconds=10,
    )
    pg = PersonaGenerator()
    md = pg.generate_with_session(info, make_form())
    assert "米菈" in md
    for heading in PersonaGenerator._REQUIRED_HEADINGS:
        assert heading in md


@responses.activate
def test_generate_with_session_falls_back_on_invalid_response():
    """LLM 回殘缺 markdown → 自動 fallback 到 template，不 raise。"""
    responses.add(
        responses.POST,
        "http://localhost:11434/api/chat",
        json={"message": {"content": "## 基本資料\n只有一個章節"}},
    )
    info = OllamaSession(
        base_url="http://localhost:11434",
        model="gemma4:e2b",
        session=requests.Session(),
        timeout_seconds=10,
    )
    pg = PersonaGenerator()
    md = pg.generate_with_session(info, make_form())
    # 應該是 template fallback（含 CALM_INTROVERTED 特徵）
    assert "獨處時能完整充電" in md


@responses.activate
def test_generate_with_session_falls_back_on_http_error():
    responses.add(
        responses.POST,
        "http://localhost:11434/api/chat",
        json={"error": "model not loaded"},
        status=500,
    )
    info = OllamaSession(
        base_url="http://localhost:11434",
        model="gemma4:e2b",
        session=requests.Session(),
        timeout_seconds=10,
    )
    pg = PersonaGenerator()
    md = pg.generate_with_session(info, make_form())
    # template fallback
    for heading in PersonaGenerator._REQUIRED_HEADINGS:
        assert heading in md


def test_save_writes_utf8_and_creates_dirs(tmp_path: Path):
    md = "## 基本資料\n- 名字：測試\n中文 emoji 🎌"
    target = tmp_path / "subdir" / "p.md"
    PersonaGenerator.save(md, target)
    assert target.exists()
    assert target.read_text(encoding="utf-8") == md


# ---------------- 整合測試：與 PromptBuilder 共享 Ollama ---------------- #


@responses.activate
def test_enhance_with_persona_uses_single_warm_unload_cycle():
    """關鍵不變式：prompt + persona 應該共用一次 warm/unload，不是各自 acquire。"""
    responses.add(
        responses.GET,
        "http://localhost:11434/api/tags",
        json={"models": [{"name": "gemma4:e2b"}]},
    )
    # warm
    responses.add(
        responses.POST,
        "http://localhost:11434/api/generate",
        json={"response": "", "done": True},
    )
    # 1) prompt chat
    responses.add(
        responses.POST,
        "http://localhost:11434/api/chat",
        json={"message": {"content": (
            "POSITIVE: 1girl, brown hair, blue eyes, masterpiece\n"
            "NEGATIVE: nsfw, lowres, bad anatomy"
        )}},
    )
    # 2) persona chat（同 endpoint，按順序消耗）
    responses.add(
        responses.POST,
        "http://localhost:11434/api/chat",
        json={"message": {"content": _VALID_PERSONA}},
    )
    # /api/ps 卸載輪詢：第一次仍在，第二次空
    responses.add(
        responses.GET,
        "http://localhost:11434/api/ps",
        json={"models": [{"name": "gemma4:e2b"}]},
    )
    responses.add(
        responses.GET,
        "http://localhost:11434/api/ps",
        json={"models": []},
    )

    loader = make_loader()
    guard = MagicMock(check_or_raise=MagicMock(return_value=None))
    guard.abort_event = MagicMock(is_set=MagicMock(return_value=False))
    pb = PromptBuilder(
        loader, guard,
        default_model="gemma4:e2b",
        unload_poll_timeout_seconds=3,
    )
    pg = PersonaGenerator()

    prompt, persona_md = pb.enhance_with_persona(make_form(), pg)

    assert "1girl" in prompt.positive
    assert "nsfw" in prompt.negative
    assert "米菈" in persona_md
    # 卸載後不該還有駐留
    assert ModelLoader.currently_loaded() is ModelKind.NONE
    # 應該只 warm 一次（/api/generate 只被打 1 次：warm。卸載 /api/generate 計 1 次更）
    # 簡單檢查：chat endpoint 被呼叫 2 次（prompt + persona）
    chat_calls = [c for c in responses.calls if c.request.url.endswith("/api/chat")]
    assert len(chat_calls) == 2, f"expected 2 chat calls, got {len(chat_calls)}"
