"""PromptBuilder — 把使用者表單轉成 SDXL prompt（透過 Ollama）。

關鍵職責：
    1. 自動偵測 Ollama 已安裝模型，優先選小的（少 VRAM）
    2. 載入時透過 ModelLoader.acquire(ModelKind.OLLAMA) 序列化
    3. 用完一定要呼叫 _force_unload() 並輪詢 /api/ps 確認 VRAM 真的釋放
"""
from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager
from typing import Iterator

import requests

from ..safety.exceptions import SafetyAbort
from ..safety.hardware_guard import HardwareGuard
from ..safety.model_loader import ModelKind, ModelLoader
from ..utils.logging_setup import get_logger
from .job_spec import (
    EyeShape,
    FormInput,
    GeneratedPrompt,
    HairLength,
    HairStyle,
    Personality,
    StyleGenre,
)
from .persona_generator import OllamaSession, PersonaGenerator

_log = get_logger(__name__)


# ---------------- Templated prompt fallback (no Ollama needed) ---------------- #


_HAIR_COLOR_TAGS: dict[str, str] = {
    # 簡化 hex → booru 色名映射（取最近的）
    # 真正部署時可加入更精細的 RGB → 色名查詢
}


def _hex_to_color_tag(hex_str: str, target: str = "hair") -> str:
    """`#RRGGBB` → "<color> hair" 或 "<color> eyes"。"""
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    # 用簡單規則決定主色名
    avg = (r + g + b) / 3
    if avg < 40:
        color = "black"
    elif avg > 220 and abs(r - g) < 20 and abs(g - b) < 20:
        color = "white" if target == "hair" else "grey"
    elif r > 200 and g > 180 and b < 100:
        color = "blonde" if target == "hair" else "yellow"
    elif r > g and r > b and r > 150:
        color = "red"
    elif g > r and g > b:
        color = "green"
    elif b > r and b > g:
        color = "blue"
    elif r > 100 and g > 50 and b < 100:
        color = "brown"
    elif r > 200 and b > 150:
        color = "pink"
    elif r > 150 and b > 150 and g < 150:
        color = "purple"
    elif r > 180 and g > 180 and b > 180:
        color = "silver" if target == "hair" else "grey"
    else:
        color = "brown" if target == "hair" else "blue"
    return f"{color} {target}"


_ALL_HAIR_COLORS = ["black", "white", "blonde", "red", "green", "blue", "brown", "pink", "purple", "silver", "grey"]


def _other_hair_color_tags(active_tag: str) -> list[str]:
    """回傳 active_tag 以外的所有髮色 negative tags（用於 anti-drift）。"""
    active_color = active_tag.split()[0]  # 'brown hair' → 'brown'
    return [f"{c} hair" for c in _ALL_HAIR_COLORS if c != active_color]


_HAIR_LENGTH_TAGS = {
    HairLength.SHORT: "short hair",
    HairLength.MEDIUM: "medium hair",
    HairLength.LONG: "long hair",
    HairLength.VERY_LONG: "very long hair",
}
_HAIR_STYLE_TAGS = {
    HairStyle.STRAIGHT: "straight hair",
    HairStyle.WAVY: "wavy hair",
    HairStyle.CURLY: "curly hair",
    HairStyle.PONYTAIL: "ponytail",
    HairStyle.TWIN_TAILS: "twintails",
    HairStyle.BUN: "hair bun",
    HairStyle.BRAIDED: "braid",
}
_EYE_SHAPE_TAGS = {
    EyeShape.ROUND: "round eyes",
    EyeShape.ALMOND: "",  # 預設不加
    EyeShape.SHARP: "sharp eyes",
    EyeShape.SLEEPY: "sleepy eyes",
}
_STYLE_TAGS = {
    StyleGenre.ANIME_MODERN: "",  # AnimagineXL 預設
    StyleGenre.ANIME_CLASSIC: "90s anime style, retro anime",
    StyleGenre.CHIBI: "chibi, cute, deformed proportions",
    StyleGenre.CYBERPUNK: "cyberpunk, neon lights, futuristic, tech wear",
    StyleGenre.COTTAGECORE: "cottagecore, soft lighting, pastoral, vintage dress",
    StyleGenre.SEMI_REALISTIC: "semi-realistic, detailed shading, refined features",
}
_PERSONALITY_TAGS = {
    Personality.CHEERFUL_OUTGOING: "smile, cheerful expression",
    Personality.CALM_INTROVERTED: "soft smile, calm expression",
    Personality.SHY_GENTLE: "blush, gentle smile",
    Personality.CONFIDENT_LEADER: "confident smile",
    Personality.PLAYFUL_TEASING: "smirk, playful expression",
    Personality.CARING_NURTURING: "gentle smile, soft expression",
    Personality.MYSTERIOUS_COOL: "cool expression, half smile",
    Personality.ENERGETIC_CHAOTIC: "excited expression, open mouth",
    Personality.SERIOUS_FOCUSED: "serious expression, focused gaze",
    Personality.DREAMY_ARTISTIC: "dreamy expression, gentle blush",
    Personality.ANALYTICAL_LOGICAL: "thoughtful expression, narrowed eyes",
    Personality.ADVENTUROUS_BRAVE: "determined smile",
    Personality.KIND_HARMONIOUS: "warm smile, soft eyes",
    Personality.PROUD_NOBLE: "confident expression, raised chin",
    Personality.CURIOUS_CHILDLIKE: "wide eyes, curious expression",
    Personality.QUIET_OBSERVANT: "neutral expression, calm gaze",
}


def template_prompt(form: FormInput) -> GeneratedPrompt:
    """純規則組裝 SDXL prompt — 不需要任何 LLM。

    當 Ollama 不可用（RAM 不夠、未啟動、模型未安裝）時自動 fallback。
    """
    parts = [
        "1girl",
        _hex_to_color_tag(form.hair_color_hex, "hair"),
        _HAIR_LENGTH_TAGS.get(form.hair_length, ""),
        _HAIR_STYLE_TAGS.get(form.hair_style, ""),
        _hex_to_color_tag(form.eye_color_hex, "eyes"),
        _EYE_SHAPE_TAGS.get(form.eye_shape, ""),
        _STYLE_TAGS.get(form.style, ""),
        _PERSONALITY_TAGS.get(form.personality, ""),
        form.extra_freeform.strip(),
        # 永遠包含
        "looking at viewer",
        "upper body",
        "white background",
        "clean lighting",
        "masterpiece, best quality, very aesthetic, absurdres",
    ]
    positive = ", ".join(p for p in parts if p)
    negative = (
        "nsfw, lowres, bad anatomy, bad hands, text, error, "
        "missing fingers, extra digit, fewer digits, cropped, "
        "worst quality, low quality, jpeg artifacts, signature, "
        "watermark, blurry, multiple views, side view, back view, "
        # 為了 BlazeFace 偵測穩定 — 排除常會干擾偵測的背景元素
        "messy background, abstract background, particles, splatter, "
        "chromatic aberration, watercolor splash, paint splash, halo, "
        "artistic effects, hair covering face, hair over eyes, "
        "closed eyes, looking down, looking away"
    )
    return GeneratedPrompt(positive=positive, negative=negative, seed=-1)


_SMALL_MODELS_PRIORITY = [
    "gemma4:e2b",      # 使用者首選 (7.2GB, 2.3B params, 4-6GB RAM 安全)
    "qwen2.5:3b",      # 中文好、最小 (1.9GB)
    "gemma2:2b",       # 1.5GB
    "phi3:mini",
    "llama3.2:3b",
]
"""若使用者另裝小模型，自動優先採用以節省 VRAM。順序 = 偏好。"""


_SYSTEM_PROMPT = """You are an SDXL anime portrait prompt engineer for VTuber model generation.
Output exactly two lines, no other text:
POSITIVE: <comma-separated booru-style tags>
NEGATIVE: <comma-separated booru-style tags>

CRITICAL: The output image will go through automated face landmark detection.
The face must be EASILY DETECTABLE — clear features, plain background, no occlusion.

Rules for POSITIVE:
- Always start with: 1girl, masterpiece, best quality, very aesthetic, absurdres
- single character, front view, upper body portrait, looking at viewer
- centered face, clear face features, simple plain white background
- soft natural lighting, no harsh shadows
- **STRICTLY USE THE EXACT HAIR COLOR TAG provided in the user message** — do NOT substitute
  with similar colors (e.g., never output "silver hair" if user says "brown hair").
  Repeat the color tag twice if needed to enforce: "brown hair, brown long hair"
- **STRICTLY USE THE EXACT EYE COLOR TAG** — same rule
- Translate personality enum to neutral expression tag (e.g. calm_introverted → soft smile, calm expression)
- Translate style enum (anime_modern → no extra tag, cyberpunk → cyberpunk style, etc.)
- Translate freeform field to tags faithfully

Rules for NEGATIVE:
- Always include: nsfw, lowres, bad anatomy, bad hands, multiple views, side view, back view
- Always include: messy background, abstract background, particles, splatter, chromatic aberration,
  watercolor, paint splash, halo behind head, artistic effects, hair covering face, hair over eyes,
  closed eyes, looking down, looking away
- **Add anti-color drift tags**: when user says brown hair, add "white hair, silver hair, blonde hair,
  blue hair, pink hair" to negative; when user says blue eyes, add "red eyes, green eyes, yellow eyes"
"""


class PromptBuilder:
    """負責 Ollama 對話 + 安全卸載。"""

    def __init__(
        self,
        loader: ModelLoader,
        guard: HardwareGuard,
        base_url: str = "http://localhost:11434",
        default_model: str = "gemma4:e4b",
        preferred_model: str = "",
        request_timeout_seconds: int = 60,
        unload_poll_timeout_seconds: int = 10,
        session: requests.Session | None = None,
    ):
        self._loader = loader
        self._guard = guard
        self._base_url = base_url.rstrip("/")
        self._timeout = request_timeout_seconds
        self._unload_timeout = unload_poll_timeout_seconds
        self._session = session or requests.Session()
        self._model = preferred_model or self._auto_select_model(default_model)

    # ---------------- public ---------------- #

    @property
    def selected_model(self) -> str:
        return self._model

    def health_check(self) -> bool:
        """Ollama 連線檢查。"""
        try:
            r = self._session.get(f"{self._base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def enhance(self, form: FormInput) -> GeneratedPrompt:
        """主要入口：表單 → SDXL prompt（單獨呼叫，不含 persona）。"""
        result: GeneratedPrompt | None = None
        try:
            with self.warmed_session() as info:
                self._guard.check_or_raise()
                result = self._chat(form, info)
        except Exception as e:  # noqa: BLE001 — RAM/timeout/network 都 fallback
            _log.warning(
                "Ollama enhance failed ({}: {}) — using template fallback prompt",
                type(e).__name__, e,
            )
            result = template_prompt(form)

        self._post_unload_recovery()
        return result if result is not None else template_prompt(form)

    def enhance_with_persona(
        self,
        form: FormInput,
        persona_gen: PersonaGenerator,
    ) -> tuple[GeneratedPrompt, str]:
        """SDXL prompt + persona markdown，共享一次 Ollama 載入。

        Memory rule: 「整合到 orchestrator.py（Stage 1.5 — 與 prompt 並行，共用 Ollama 載入）」
        以單一 acquire/warm/unload 完成兩次 chat，省去多餘的暖機與卸載循環。

        Returns:
            (GeneratedPrompt, persona_markdown). 任一階段 LLM 失敗會自動 fallback
            到 template；call site 不需處理例外。
        """
        prompt: GeneratedPrompt | None = None
        persona_md: str | None = None

        try:
            with self.warmed_session() as info:
                self._guard.check_or_raise()
                # 1) prompt 先（短）
                try:
                    prompt = self._chat(form, info)
                except Exception as e:  # noqa: BLE001
                    _log.warning(
                        "Ollama prompt chat failed ({}: {}) — fallback template",
                        type(e).__name__, e,
                    )
                    prompt = template_prompt(form)
                # 2) persona 後（長）— 失敗也由 PersonaGenerator 內部 fallback
                self._guard.check_or_raise()
                persona_md = persona_gen.generate_with_session(info, form)
        except Exception as e:  # noqa: BLE001 — warm/acquire 整個失敗
            _log.warning(
                "Shared Ollama session failed ({}: {}) — both fallback to templates",
                type(e).__name__, e,
            )
            if prompt is None:
                prompt = template_prompt(form)
            if persona_md is None:
                persona_md = persona_gen.template_fallback(form)

        self._post_unload_recovery()
        return (
            prompt if prompt is not None else template_prompt(form),
            persona_md if persona_md is not None else persona_gen.template_fallback(form),
        )

    @contextmanager
    def warmed_session(self) -> Iterator[OllamaSession]:
        """Acquire Ollama loader → warm → yield session info → force-unload。

        提供給 PersonaGenerator 等同會話內額外呼叫者重用。所有 chat 呼叫
        都應在 yield 期間完成，否則 Ollama 已被卸載。
        """
        def _loader_fn():
            return self._warm()

        def _unloader_fn(_obj):
            self._force_unload()

        with self._loader.acquire(ModelKind.OLLAMA, _loader_fn, _unloader_fn):
            yield OllamaSession(
                base_url=self._base_url,
                model=self._model,
                session=self._session,
                timeout_seconds=self._timeout,
            )

    def _post_unload_recovery(self) -> None:
        """Ollama 卸載後若 guard 仍鎖定 abort，給系統時間回落並嘗試解鎖。

        Race: warm() 載完瞬間 RAM spike 觸發 abort，但 check_or_raise 沒抓到。
        Ollama 已釋放 → 等系統 RAM 回落後嘗試清 abort，避免後續 SDXL 階段卡住。
        """
        if self._guard.abort_event.is_set():
            _log.info("Post-Ollama abort_event set, attempting recovery...")
            for attempt in range(8):
                time.sleep(0.5)
                if self._guard.try_clear_abort_if_recovered(source=f"prompt_builder att{attempt}"):
                    break

    # ---------------- internal ---------------- #

    def _auto_select_model(self, default: str) -> str:
        try:
            r = self._session.get(f"{self._base_url}/api/tags", timeout=5)
            r.raise_for_status()
            installed = {m["name"] for m in r.json().get("models", [])}
        except requests.RequestException as e:
            _log.warning("Ollama unreachable during model auto-select: {} — falling back to {}", e, default)
            return default

        # 嚴格 exact match：避免「家族匹配」誤選到同家族的大模型（如 gemma4:e2b
        # 找不到時不該 fallback 到 gemma4:e4b 這種會 OOM 的）
        for small in _SMALL_MODELS_PRIORITY:
            if small in installed:
                _log.info("✓ Using small model {} (preferred for VRAM safety)", small)
                return small
        if default in installed:
            _log.info("Using default model {}", default)
            return default
        # 最後 fallback：用 installed 列表的第一個
        if installed:
            chosen = sorted(installed)[0]
            _log.warning("Default {} not found; using {}", default, chosen)
            return chosen
        raise RuntimeError(f"No Ollama models installed. Run `ollama pull {default}`.")

    def _warm(self) -> dict:
        """送一個空 prompt 觸發載入。`keep_alive=-1` 讓 Ollama 保留至明確卸載。"""
        r = self._session.post(
            f"{self._base_url}/api/generate",
            json={"model": self._model, "prompt": "", "keep_alive": -1, "stream": False},
            timeout=self._timeout,
        )
        r.raise_for_status()
        _log.debug("Ollama model {} warmed", self._model)
        return {"warmed": True}

    def _chat(self, form: FormInput, info: OllamaSession | None = None) -> GeneratedPrompt:
        """送對話，解析回應為 (positive, negative)。

        info=None 時使用 self 的連線設定（向後相容單獨呼叫）。
        """
        if info is None:
            info = OllamaSession(
                base_url=self._base_url,
                model=self._model,
                session=self._session,
                timeout_seconds=self._timeout,
            )
        user_msg = self._format_user_message(form)
        r = info.session.post(
            f"{info.base_url}/api/chat",
            json={
                "model": info.model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "stream": False,
                "keep_alive": -1,
            },
            timeout=info.timeout_seconds,
        )
        r.raise_for_status()
        body = r.json()
        content = body.get("message", {}).get("content", "")
        positive, negative = self._parse_response(content)

        # Post-process: 強制 hair/eye tag 出現（LLM 偶爾忘記）+ anti-drift negative
        hair_tag = _hex_to_color_tag(form.hair_color_hex, "hair")
        eye_tag = _hex_to_color_tag(form.eye_color_hex, "eyes")
        if hair_tag.split()[0] not in positive.lower():
            _log.info("LLM omitted hair tag '{}'; force-prepending", hair_tag)
            positive = f"{hair_tag}, " + positive
        if eye_tag.split()[0] not in positive.lower():
            _log.info("LLM omitted eye tag '{}'; force-prepending", eye_tag)
            positive = f"{eye_tag}, " + positive
        # Anti-drift negative：排除其他髮色
        anti_drift_hair = _other_hair_color_tags(hair_tag)
        if anti_drift_hair and not any(t in negative for t in anti_drift_hair):
            negative = negative + ", " + ", ".join(anti_drift_hair)

        return GeneratedPrompt(positive=positive, negative=negative)

    @staticmethod
    def _format_user_message(form: FormInput) -> str:
        # 把 hex 轉成具體 booru-style 色名，讓 LLM 能直接複製「強約束」的字串
        hair_tag = _hex_to_color_tag(form.hair_color_hex, "hair")
        eye_tag = _hex_to_color_tag(form.eye_color_hex, "eyes")
        return json.dumps(
            {
                "hair_color_hex": form.hair_color_hex,
                "REQUIRED_HAIR_TAG_USE_VERBATIM": hair_tag,
                "hair_length": form.hair_length.value,
                "hair_style": form.hair_style.value,
                "eye_color_hex": form.eye_color_hex,
                "REQUIRED_EYE_TAG_USE_VERBATIM": eye_tag,
                "eye_shape": form.eye_shape.value,
                "style": form.style.value,
                "personality": form.personality.value,
                "extra_freeform": form.extra_freeform,
                "RULE": (
                    f"You MUST include the exact tag '{hair_tag}' in POSITIVE. "
                    f"You MUST include the exact tag '{eye_tag}' in POSITIVE. "
                    f"Do NOT use any other hair/eye color tag."
                ),
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _parse_response(content: str) -> tuple[str, str]:
        """從模型回應抓出 POSITIVE / NEGATIVE 兩行；容錯設計。"""
        # 先試嚴格格式
        pos_match = re.search(r"POSITIVE:\s*(.+?)(?:\n|$)", content, re.IGNORECASE)
        neg_match = re.search(r"NEGATIVE:\s*(.+?)(?:\n|$)", content, re.IGNORECASE)
        if pos_match and neg_match:
            return pos_match.group(1).strip(), neg_match.group(1).strip()

        # 容錯：第一段當 positive，第二段當 negative
        parts = [p.strip() for p in content.split("\n") if p.strip()]
        if len(parts) >= 2:
            return parts[0], parts[1]
        if len(parts) == 1:
            return parts[0], "lowres, bad anatomy, multiple views"
        # 完全空 → 用安全預設
        _log.warning("Empty Ollama response; using safe default prompt")
        return (
            "1girl, anime portrait, masterpiece, best quality, very aesthetic, "
            "looking at viewer, white background, upper body",
            "nsfw, lowres, bad anatomy, multiple views, side view, back view",
        )

    def _force_unload(self) -> None:
        """送 keep_alive=0 強制卸載 + 輪詢 /api/ps 等到真的卸了才返回。"""
        try:
            self._session.post(
                f"{self._base_url}/api/generate",
                json={"model": self._model, "prompt": "", "keep_alive": 0, "stream": False},
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            _log.warning("Force-unload request failed: {} — continuing to poll", e)

        deadline = time.time() + self._unload_timeout
        while time.time() < deadline:
            try:
                r = self._session.get(f"{self._base_url}/api/ps", timeout=5)
                r.raise_for_status()
                models = r.json().get("models", [])
                still_loaded = any(
                    (m.get("name") == self._model) or m.get("name", "").startswith(self._model.split(":")[0] + ":")
                    for m in models
                )
                if not still_loaded:
                    _log.debug("✓ Ollama model {} unloaded; VRAM freed", self._model)
                    return
            except requests.RequestException:
                pass
            time.sleep(0.3)
        raise SafetyAbort(
            f"Ollama failed to release VRAM for {self._model} within {self._unload_timeout}s"
        )
