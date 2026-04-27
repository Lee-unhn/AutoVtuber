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
    """`#RRGGBB` → "<color> hair" 或 "<color> eyes"。

    R3 升級：改用 HSV-based 分類（原 RGB rules 對暗紅 #7B1F1F 算成 brown 是 bug）。
    HSV 對「色相」分類比 RGB 強，且能正確處理「亮藍 vs 暗藍」「橘色 vs 棕色」。
    """
    import colorsys
    h_str = hex_str.lstrip("#")
    r, g, b = int(h_str[0:2], 16), int(h_str[2:4], 16), int(h_str[4:6], 16)
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    h_deg = h * 360

    # 處理灰階（極暗/極亮/低飽和）
    if v < 0.15:
        return f"black {target}"
    if v > 0.88 and s < 0.10:
        return f"{'white' if target == 'hair' else 'grey'} {target}"
    if s < 0.12:
        return f"{'silver' if target == 'hair' else 'grey'} {target}"

    # 按色相分類
    if h_deg < 15 or h_deg >= 345:
        # 紅 vs 粉紅：高 V + 低 S → 粉（如 #FFC0CB），否則紅
        color = "pink" if (v > 0.85 and s < 0.50) else "red"
    elif h_deg < 45:
        # 暖橘：高 V 是 orange（金髮），低 V 是 brown
        color = "orange" if v > 0.65 else "brown"
    elif h_deg < 65:
        color = "blonde" if target == "hair" else "yellow"
    elif h_deg < 150:
        color = "green"
    elif h_deg < 200:
        color = "blue"  # cyan-ish 也歸藍
    elif h_deg < 250:
        color = "blue"
    elif h_deg < 290:
        color = "purple"
    else:  # 290-345
        # 紫紅 vs 粉紅：飽和度 + 亮度區分
        color = "pink" if (v > 0.7 or s < 0.6) else "purple"

    return f"{color} {target}"


def _color_strength_modifier(hex_str: str) -> str:
    """根據 HSV S/V 給 SDXL 「強度修飾詞」加強色彩穩定。

    例：#5B3A29 (低 V 暗棕) → "deep brown"；#FFB6C1 (高 V 淡粉) → "light pink"
    """
    import colorsys
    h_str = hex_str.lstrip("#")
    r, g, b = int(h_str[0:2], 16), int(h_str[2:4], 16), int(h_str[4:6], 16)
    _h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    if v < 0.40:
        return "dark"
    if v > 0.85:
        return "light"
    if s > 0.75:
        return "vivid"
    return ""


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

        # R3 Post-process: 強制 hair/eye tag 出現（LLM 偶爾忘記）+ anti-drift negative
        hair_color = _hex_to_color_tag(form.hair_color_hex, "hair")
        eye_color = _hex_to_color_tag(form.eye_color_hex, "eyes")
        hair_strength = _color_strength_modifier(form.hair_color_hex)
        eye_strength = _color_strength_modifier(form.eye_color_hex)
        hair_tag = f"{hair_strength} {hair_color}".strip()
        eye_tag = f"{eye_strength} {eye_color}".strip()
        # 用色名（不含 strength）做 contains 判定，更寬鬆
        hair_color_name = hair_color.split()[0]
        eye_color_name = eye_color.split()[0]
        if hair_color_name not in positive.lower():
            _log.info("LLM omitted hair color '{}'; force-prepending '{}'", hair_color_name, hair_tag)
            positive = f"{hair_tag}, " + positive
        if eye_color_name not in positive.lower():
            _log.info("LLM omitted eye color '{}'; force-prepending '{}'", eye_color_name, eye_tag)
            positive = f"{eye_tag}, " + positive
        # Anti-drift negative：排除其他髮色 + 其他眼色
        anti_drift_hair = _other_hair_color_tags(hair_color)
        anti_drift_eye = [f"{c} eyes" for c in _ALL_HAIR_COLORS if c != eye_color_name]
        for tag_list in (anti_drift_hair, anti_drift_eye):
            if tag_list and not any(t in negative for t in tag_list):
                negative = negative + ", " + ", ".join(tag_list)

        return GeneratedPrompt(positive=positive, negative=negative)

    @staticmethod
    def _format_user_message(form: FormInput) -> str:
        # R3：把 hex 轉色名 + 強度修飾詞，讓 LLM 雙保險
        hair_color = _hex_to_color_tag(form.hair_color_hex, "hair")
        eye_color = _hex_to_color_tag(form.eye_color_hex, "eyes")
        hair_strength = _color_strength_modifier(form.hair_color_hex)
        eye_strength = _color_strength_modifier(form.eye_color_hex)
        # 組合：例 "deep brown hair" / "vivid red eyes" / "blonde hair"
        hair_tag = f"{hair_strength} {hair_color}".strip()
        eye_tag = f"{eye_strength} {eye_color}".strip()
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
                    f"Do NOT use any other hair/eye color tag. "
                    f"If the user specified a strength modifier (deep/light/vivid), "
                    f"keep it — it controls saturation/brightness and matters for skin/hair tone."
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
