"""FaceGenerator — SDXL + AnimagineXL + IP-Adapter Plus Face 包裝。

VRAM 安全策略：
    - 透過 ModelLoader.acquire(ModelKind.SDXL) 序列化（同時間 GPU 只一個重模型）
    - 強制 enable_sequential_cpu_offload() — 慢但 12GB VRAM 安全
    - 強制 enable_vae_slicing() + enable_vae_tiling() — 防 VAE 解碼爆 VRAM
    - 預設 steps=20 / size=1024² / batch=1（保守參數）

設計原則：
    - 模組可在沒裝 torch/diffusers 的環境 import（lazy import 在 _build_pipeline 內）
    - 給定 mock 的 ModelLoader，能在 CI 跑單元測試（不下載權重）
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PIL import Image

from ..safety.hardware_guard import HardwareGuard
from ..safety.model_loader import ModelKind, ModelLoader
from ..utils.logging_setup import get_logger
from .job_spec import GeneratedPrompt

_log = get_logger(__name__)


_DEFAULT_NEGATIVE = (
    "nsfw, lowres, bad anatomy, bad hands, text, error, missing fingers, "
    "extra digit, fewer digits, cropped, worst quality, low quality, "
    "normal quality, jpeg artifacts, signature, watermark, username, blurry, "
    "multiple views, side view, back view"
)


class FaceGenerator:
    """SDXL + IP-Adapter 圖像生成；每個 job 重建 pipeline 以保證 VRAM 釋放。"""

    SDXL_REPO_DIR_NAME = "animagine-xl-4.0"
    IP_REPO_DIR_NAME = "ip_adapter"
    IP_WEIGHT_FILE = "ip-adapter-plus-face_sdxl_vit-h.bin"

    DEFAULT_STEPS = 20
    DEFAULT_CFG = 6.5
    DEFAULT_SIZE = (1024, 1024)

    def __init__(
        self,
        loader: ModelLoader,
        guard: HardwareGuard,
        models_dir: Path,
        steps: int | None = None,
        cfg_scale: float | None = None,
        size: tuple[int, int] | None = None,
        ip_adapter_scale_with_photo: float = 0.7,
        ip_adapter_scale_without_photo: float = 0.0,
    ):
        self._loader = loader
        self._guard = guard
        self._models_dir = Path(models_dir)
        self._steps = steps or self.DEFAULT_STEPS
        self._cfg = cfg_scale or self.DEFAULT_CFG
        self._size = size or self.DEFAULT_SIZE
        self._ip_scale_with_photo = ip_adapter_scale_with_photo
        self._ip_scale_without_photo = ip_adapter_scale_without_photo

    # ---------------- public ---------------- #

    def generate(
        self,
        prompt: GeneratedPrompt,
        reference_photo_path: str | None = None,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> Image.Image:
        """生成單張前向人臉肖像。"""

        def _loader_fn():
            return self._build_pipeline()

        def _unloader_fn(pipe: Any):
            self._free_pipeline(pipe)

        with self._loader.acquire(ModelKind.SDXL, _loader_fn, _unloader_fn) as pipe:
            self._guard.check_or_raise()
            return self._run_pipeline(pipe, prompt, reference_photo_path, progress_cb)

    # ---------------- internal ---------------- #

    def _build_pipeline(self):
        """Lazy import + 從本地 disk 載入 SDXL ckpt。"""
        import torch
        from diffusers import StableDiffusionXLPipeline

        sdxl_dir = self._models_dir / "sdxl" / self.SDXL_REPO_DIR_NAME
        if not sdxl_dir.exists():
            raise FileNotFoundError(
                f"SDXL ckpt 未下載：{sdxl_dir}\n"
                f"請先跑 setup wizard 或手動下載 AnimagineXL 4.0 至此目錄。"
            )

        _log.info("Loading SDXL pipeline from {}", sdxl_dir)
        pipe = StableDiffusionXLPipeline.from_pretrained(
            str(sdxl_dir),
            torch_dtype=torch.float16,
            use_safetensors=True,
            local_files_only=True,
        )

        # 安全設定：純 GPU 模式（無 CPU offload）+ VAE slicing/tiling
        # 16GB RAM 太緊，model_cpu_offload 也撐不住（RAM 95.1%）
        # 改純 GPU + fp16 → SDXL ~9.5GB VRAM，留 2.5GB 給 VAE/scheduler buffer
        pipe.to("cuda")
        pipe.enable_vae_slicing()
        pipe.enable_vae_tiling()

        # IP-Adapter Plus Face — 控制臉部一致性
        # 失敗 (corrupted weights / missing CLIP encoder) 時 pipeline 仍可正常生成（無參考照片不影響）
        ip_dir = self._models_dir / self.IP_REPO_DIR_NAME
        ip_weight = ip_dir / self.IP_WEIGHT_FILE
        ip_encoder_dir = ip_dir / "image_encoder"
        if ip_weight.exists() and ip_encoder_dir.exists():
            try:
                pipe.load_ip_adapter(
                    str(ip_dir),
                    subfolder=".",
                    weight_name=self.IP_WEIGHT_FILE,
                    local_files_only=True,
                )
                _log.info("IP-Adapter loaded")
            except Exception as e:  # noqa: BLE001 — 不能讓 IP-Adapter 失敗擋住整條 pipeline
                _log.warning(
                    "IP-Adapter 載入失敗（檔案可能損壞）— 改用無參考照片模式：{}", e
                )
        else:
            _log.warning(
                "IP-Adapter 檔案缺漏 (.bin={}, image_encoder={}) — 不影響無參考照片生成",
                ip_weight.exists(), ip_encoder_dir.exists(),
            )

        return pipe

    def _free_pipeline(self, pipe: Any) -> None:
        """釋放所有模組到 CPU，讓 ModelLoader 後續 cuda.empty_cache 真的有效。"""
        try:
            del pipe
        except Exception:  # noqa: BLE001
            pass

    def _run_pipeline(
        self,
        pipe: Any,
        prompt: GeneratedPrompt,
        reference_photo_path: str | None,
        progress_cb: Callable[[int, int], None] | None,
    ) -> Image.Image:
        import torch

        # 設定 IP-Adapter scale
        if reference_photo_path:
            ref_img = Image.open(reference_photo_path).convert("RGB")
            ip_scale = self._ip_scale_with_photo
            try:
                pipe.set_ip_adapter_scale(ip_scale)
            except Exception:  # noqa: BLE001 — IP-Adapter 沒裝就略過
                _log.warning("set_ip_adapter_scale unavailable; reference photo ignored")
                ref_img = None
        else:
            ref_img = None
            try:
                pipe.set_ip_adapter_scale(self._ip_scale_without_photo)
            except Exception:  # noqa: BLE001
                pass

        seed = prompt.seed if prompt.seed >= 0 else int(torch.empty((), dtype=torch.int64).random_().item())
        generator = torch.Generator(device="cuda").manual_seed(seed)

        negative = prompt.negative or _DEFAULT_NEGATIVE

        # 安全 callback：每 step 檢查 guard
        def _step_cb(pipe_self, step_index, timestep, callback_kwargs):
            self._guard.check_or_raise()
            if progress_cb:
                progress_cb(step_index + 1, self._steps)
            return callback_kwargs

        kwargs: dict = dict(
            prompt=prompt.positive,
            negative_prompt=negative,
            num_inference_steps=self._steps,
            guidance_scale=self._cfg,
            width=self._size[0],
            height=self._size[1],
            generator=generator,
            callback_on_step_end=_step_cb,
        )
        if ref_img is not None:
            kwargs["ip_adapter_image"] = ref_img

        with torch.inference_mode():
            result = pipe(**kwargs)
        img = result.images[0]
        # 為了診斷 face_aligner 偵測問題，永遠存原始 SDXL 輸出（覆寫）
        try:
            from pathlib import Path
            debug_path = Path(__file__).resolve().parents[3] / "output" / "_last_sdxl_raw.png"
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(debug_path)
            _log.debug("Saved raw SDXL output to {}", debug_path.name)
        except Exception:  # noqa: BLE001
            pass
        return img
