"""Pipeline 的單一資料來源 — 所有模組之間用這些 dataclass 溝通。

設計原則：
    - 所有結構都 pydantic 驗證，不允許魔術 dict
    - 每個欄位都有預設值，方便 unit test 建構
    - 加上 model_dump_json() 直接序列化為 preset
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


# ---------------- 列舉值（讓 UI 與後端共用同一定義）---------------- #


class HairLength(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"
    VERY_LONG = "very_long"


class HairStyle(str, Enum):
    STRAIGHT = "straight"
    WAVY = "wavy"
    CURLY = "curly"
    PONYTAIL = "ponytail"
    TWIN_TAILS = "twin_tails"
    BUN = "bun"
    BRAIDED = "braided"


class EyeShape(str, Enum):
    ROUND = "round"
    ALMOND = "almond"
    SHARP = "sharp"
    SLEEPY = "sleepy"


class StyleGenre(str, Enum):
    ANIME_MODERN = "anime_modern"
    ANIME_CLASSIC = "anime_classic"
    CHIBI = "chibi"
    CYBERPUNK = "cyberpunk"
    COTTAGECORE = "cottagecore"
    SEMI_REALISTIC = "semi_realistic"


class Personality(str, Enum):
    """16 種人格軸（簡化 MBTI），影響 idle 表情/動作頻率（MVP2 啟用）。"""

    CHEERFUL_OUTGOING = "cheerful_outgoing"        # ESFP-ish
    CALM_INTROVERTED = "calm_introverted"           # INTJ-ish
    SHY_GENTLE = "shy_gentle"                       # INFP-ish
    CONFIDENT_LEADER = "confident_leader"           # ENTJ-ish
    PLAYFUL_TEASING = "playful_teasing"             # ENTP-ish
    CARING_NURTURING = "caring_nurturing"           # ESFJ-ish
    MYSTERIOUS_COOL = "mysterious_cool"             # INTP-ish
    ENERGETIC_CHAOTIC = "energetic_chaotic"         # ENFP-ish
    SERIOUS_FOCUSED = "serious_focused"             # ISTJ-ish
    DREAMY_ARTISTIC = "dreamy_artistic"             # ISFP-ish
    ANALYTICAL_LOGICAL = "analytical_logical"       # INTP-ish (variant)
    ADVENTUROUS_BRAVE = "adventurous_brave"         # ESTP-ish
    KIND_HARMONIOUS = "kind_harmonious"             # INFJ-ish
    PROUD_NOBLE = "proud_noble"                     # ESTJ-ish
    CURIOUS_CHILDLIKE = "curious_childlike"         # ENFJ-ish (variant)
    QUIET_OBSERVANT = "quiet_observant"             # ISTP-ish


# ---------------- 主要 Schema ---------------- #


class FormInput(BaseModel):
    """使用者表單輸入。所有 UI form 欄位的單一來源。"""

    hair_color_hex: str = Field(default="#5B3A29", pattern=r"^#[0-9A-Fa-f]{6}$")
    hair_length: HairLength = HairLength.MEDIUM
    hair_style: HairStyle = HairStyle.STRAIGHT
    eye_color_hex: str = Field(default="#3B5BA5", pattern=r"^#[0-9A-Fa-f]{6}$")
    eye_shape: EyeShape = EyeShape.ALMOND
    style: StyleGenre = StyleGenre.ANIME_MODERN
    personality: Personality = Personality.CALM_INTROVERTED
    extra_freeform: str = Field(default="", max_length=500)
    reference_photo_path: str | None = None
    base_model_id: str = "AvatarSample_A"  # 對應 assets/base_models/<id>.vrm

    nickname: str = Field(default="無名", max_length=20)
    """preset 顯示名（亦會放在輸出檔名）。"""


class GeneratedPrompt(BaseModel):
    """PromptBuilder 的輸出。"""

    positive: str
    negative: str
    seed: int = -1


class StageResult(BaseModel):
    """單一階段執行結果（用於 UI 進度顯示）。"""

    name: str
    succeeded: bool
    elapsed_seconds: float
    artifact_path: str | None = None
    error_message: str | None = None


class JobSpec(BaseModel):
    """一個完整生成任務的不變輸入。

    一旦建立就不該被修改；所有後續結果存在 JobResult 裡。
    """

    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = Field(default_factory=time.time)
    form: FormInput

    @property
    def output_basename(self) -> str:
        """輸出檔名 stem，例：`character_20260426_153012_acebd2f1_無名.vrm`。"""
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(self.created_at))
        # 移除檔名不允許的字元
        nick = "".join(c for c in self.form.nickname if c.isalnum() or c in "-_") or "vtuber"
        return f"character_{ts}_{self.job_id[:8]}_{nick}"


class JobResult(BaseModel):
    """完整任務執行紀錄。"""

    spec: JobSpec
    succeeded: bool
    output_vrm_path: str | None = None
    persona_md_path: str | None = None
    prompt: GeneratedPrompt | None = None
    stages: list[StageResult] = Field(default_factory=list)
    total_elapsed_seconds: float = 0.0
    error_message: str | None = None

    def append_stage(self, result: StageResult) -> None:
        self.stages.append(result)
        self.total_elapsed_seconds += result.elapsed_seconds

    def to_preset_path(self, presets_dir: Path) -> Path:
        """寫成 preset JSON 檔，回傳路徑。"""
        path = presets_dir / f"{self.spec.output_basename}.preset.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path
