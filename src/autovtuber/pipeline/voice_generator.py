"""MVP5.5 — VoxCPM voice preview generator.

從 persona 萃取 voice description + catchphrase → 5-10s WAV 音檔。

設計原則（依 AUTOVTUBER.md 「VoxCPM 整合 DO/DON'T」）：
    1. 用 0.5B variant（5GB VRAM）給 12GB GPU 留空間
    2. 透過 ModelLoader.acquire(ModelKind.VOX_TTS) 序列化，避免跟 SDXL/TripoSR 共處
    3. Fallback：失敗只 log warning + 跳過 wav 不擋 VRM 主 pipeline
    4. Voice Design 描述放最前括號 `"(young female, soft, slow) 文字"`

輸出：`output/<basename>_voice_sample.wav`（24kHz / 16-bit / mono）
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from ..safety.exceptions import SafetyAbort
from ..safety.hardware_guard import HardwareGuard
from ..safety.model_loader import ModelKind, ModelLoader
from ..utils.logging_setup import get_logger

if TYPE_CHECKING:
    from .job_spec import FormInput
    from .persona_runtime import PersonaRuntime

_log = get_logger(__name__)


# 預設模型：0.5B variant（5GB VRAM）
_DEFAULT_MODEL_ID = "openbmb/VoxCPM-0.5B"
_DEFAULT_SAMPLE_RATE_FALLBACK = 16000  # 0.5B output rate


# ---------------- Voice Description 推導（純規則） ---------------- #


def _personality_to_voice_description(form: "FormInput", runtime: "PersonaRuntime") -> str:
    """從 form + runtime 組「自然語言聲音描述」給 VoxCPM Voice Design。

    格式參考 VoxCPM 文件：括號內含 gender/age/tone/emotion/pace 等。
    """
    from .job_spec import Personality

    # 性別：VRoid 預設 1girl 所以多女聲；若需要可從 form 額外欄位拓展
    gender = "young female"

    # 從個性映射 tone（音色）+ pace（語速）
    personality_voice_map = {
        Personality.CHEERFUL_OUTGOING: "bright, energetic, fast pace",
        Personality.CALM_INTROVERTED: "soft, calm, slow pace",
        Personality.SHY_GENTLE: "soft, slightly hesitant, gentle",
        Personality.CONFIDENT_LEADER: "clear, confident, steady pace",
        Personality.PLAYFUL_TEASING: "playful, mischievous, varied pace",
        Personality.CARING_NURTURING: "warm, soothing, gentle pace",
        Personality.MYSTERIOUS_COOL: "low, calm, slightly raspy, slow",
        Personality.ENERGETIC_CHAOTIC: "high energy, fast, expressive",
        Personality.SERIOUS_FOCUSED: "even, focused, measured",
        Personality.DREAMY_ARTISTIC: "soft, dreamy, drawn-out pace",
        Personality.ANALYTICAL_LOGICAL: "clear, precise, even pace",
        Personality.ADVENTUROUS_BRAVE: "energetic, bright, eager",
        Personality.KIND_HARMONIOUS: "warm, gentle, even",
        Personality.PROUD_NOBLE: "graceful, controlled, slower",
        Personality.CURIOUS_CHILDLIKE: "bright, slightly higher pitch, excited",
        Personality.QUIET_OBSERVANT: "soft, low, measured",
    }
    voice_tone = personality_voice_map.get(form.personality, "calm, even")

    # 包成 VoxCPM Voice Design 格式
    return f"({gender}, {voice_tone})"


def _pick_sample_text(runtime: "PersonaRuntime") -> str:
    """從 persona 挑一句適合朗讀的話。

    優先序：
        1. 第一個口頭禪（短、有特色）
        2. 簽名 prop 相關的口頭禪（綁定關鍵字）
        3. 預設打招呼句
    """
    if runtime.catchphrases:
        first = runtime.catchphrases[0].strip()
        # 移除 markdown 引號 + 註解
        first = re.split(r"\s+#\s+", first)[0].strip()
        first = first.strip("「」").strip("『』")
        if 4 <= len(first) <= 50:
            return first
    return f"大家好，我是 {runtime.nickname}，請多指教。"


# ---------------- 核心 API ---------------- #


@dataclass
class VoiceGenResult:
    wav_path: Path | None        # 成功時為 wav 路徑，失敗 None
    voice_description: str       # 用了什麼 voice description（給 persona_runtime 存）
    sample_text: str             # 朗讀的文字
    sample_rate: int             # 取樣率
    elapsed_seconds: float       # 耗時


class VoiceGenerator:
    """用 VoxCPM 生成聲音預覽。

    Lifetime：每個 job 一個實例，由 orchestrator 透過 ModelLoader 序列化呼叫。
    """

    def __init__(
        self,
        loader: ModelLoader,
        guard: HardwareGuard,
        model_id: str = _DEFAULT_MODEL_ID,
        cfg_value: float = 2.0,
        inference_timesteps: int = 10,
    ):
        self._loader = loader
        self._guard = guard
        self._model_id = model_id
        self._cfg_value = cfg_value
        self._inference_timesteps = inference_timesteps

    def generate(
        self,
        form: "FormInput",
        runtime: "PersonaRuntime",
        output_path: Path,
    ) -> VoiceGenResult:
        """生成聲音預覽到指定路徑。

        Returns:
            VoiceGenResult（wav_path None 表示失敗 — 不拋例外，主 pipeline 繼續）
        """
        import time
        t0 = time.perf_counter()
        voice_desc = _personality_to_voice_description(form, runtime)
        sample_text = _pick_sample_text(runtime)
        full_text = f"{voice_desc} {sample_text}"
        _log.info("Voice preview text: {!r}", full_text)

        # ModelLoader 序列化：VoxCPM 不跟 SDXL/TripoSR 共處
        def _loader_fn():
            return self._build_pipe()

        def _unloader_fn(pipe):
            self._free_pipe(pipe)

        try:
            with self._loader.acquire(ModelKind.VOX_TTS, _loader_fn, _unloader_fn) as model:
                self._post_load_recovery()
                self._guard.check_or_raise()
                wav, sr = self._run_inference(model, full_text)
        except SafetyAbort:
            _log.warning("VoxCPM voice gen aborted by HardwareGuard — skipping (non-fatal)")
            return VoiceGenResult(
                wav_path=None, voice_description=voice_desc,
                sample_text=sample_text, sample_rate=0,
                elapsed_seconds=time.perf_counter() - t0,
            )
        except Exception as e:  # noqa: BLE001 — TTS 失敗永遠不阻 VRM 主 pipeline
            _log.warning("VoxCPM voice gen failed ({}: {}) — skipping (non-fatal)",
                         type(e).__name__, e)
            return VoiceGenResult(
                wav_path=None, voice_description=voice_desc,
                sample_text=sample_text, sample_rate=0,
                elapsed_seconds=time.perf_counter() - t0,
            )

        # 寫檔
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            import soundfile as sf
            sf.write(str(output_path), wav, sr, subtype="PCM_16")
            _log.info("🎙️ Voice sample saved → {} ({:.2f}s wav at {} Hz)",
                      output_path.name, len(wav) / sr, sr)
            return VoiceGenResult(
                wav_path=output_path, voice_description=voice_desc,
                sample_text=sample_text, sample_rate=sr,
                elapsed_seconds=time.perf_counter() - t0,
            )
        except Exception as e:  # noqa: BLE001
            _log.warning("Failed to save voice wav: {}", e)
            return VoiceGenResult(
                wav_path=None, voice_description=voice_desc,
                sample_text=sample_text, sample_rate=sr,
                elapsed_seconds=time.perf_counter() - t0,
            )

    # ---------- internal ---------- #

    def _post_load_recovery(self) -> None:
        """VoxCPM ckpt 載入後若 abort_event 仍鎖定，給系統時間回落並嘗試解鎖。

        Race scenario（同 image_to_3d._post_load_recovery）：from_pretrained 把
        ckpt 塞進 CPU RAM 的瞬間可能觸發 RAM abort；載入完成後 RAM 回落，
        本方法輪詢清掉殘留的 abort_event，避免 voice 步驟被誤殺。
        """
        import time
        if not getattr(self._guard, "abort_event", None) or not self._guard.abort_event.is_set():
            return
        _log.info("Post-VoxCPM-load abort_event set, attempting recovery...")
        for attempt in range(8):
            time.sleep(0.5)
            if self._guard.try_clear_abort_if_recovered(source=f"voice_generator att{attempt}"):
                _log.info("✓ Recovered after attempt {}", attempt)
                return
        _log.warning("Could not clear abort_event after 4s; downstream check_or_raise will raise")

    def _build_pipe(self):
        """載入 VoxCPM。lazy import 避免測試環境需要整套 VoxCPM stack。"""
        from voxcpm import VoxCPM
        _log.info("Loading VoxCPM {} (first run downloads ~2.5GB)", self._model_id)
        model = VoxCPM.from_pretrained(self._model_id, load_denoiser=False)
        return model

    @staticmethod
    def _free_pipe(pipe) -> None:
        """卸載 VoxCPM。"""
        try:
            del pipe
        except Exception:  # noqa: BLE001
            pass

    def _run_inference(self, model, text: str) -> tuple[np.ndarray, int]:
        """執行推論，回傳 (wav array, sample_rate)。"""
        import torch
        with torch.inference_mode():
            wav = model.generate(
                text=text,
                cfg_value=self._cfg_value,
                inference_timesteps=self._inference_timesteps,
            )
        # 嘗試從模型抓 sample_rate；失敗回 fallback
        sr = _DEFAULT_SAMPLE_RATE_FALLBACK
        try:
            sr = int(model.tts_model.sample_rate)
        except AttributeError:
            pass
        # 確保 numpy 1D float32
        if hasattr(wav, "cpu"):
            wav = wav.cpu().numpy()
        wav = np.asarray(wav, dtype=np.float32).flatten()
        return wav, sr
