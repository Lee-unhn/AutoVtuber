"""ImageTo3D — 包裝 TripoSR：PIL Image → trimesh.Trimesh（含 vertex colors）。

VRAM / 安全策略：
    - 透過 ModelLoader.acquire(ModelKind.TRIPO_SR) 序列化（同時間 GPU 只一個重模型）
    - lazy import TSR：模組可在沒裝 torch 的環境 import（CI 友善）
    - 第一次 generate() 會由 hf_hub_download 下載 ~1.7 GB checkpoint 到 HF cache
    - marching cubes 走 PyMCubes shim（純 CPU；無 nvcc 環境也可運作）
    - Race recovery: TSR ckpt 載入時短暫 RAM spike → abort_event 鎖死 → 載完後
      RAM 已回落 → 嘗試清 abort_event 讓推論能跑（同 PromptBuilder._post_unload_recovery）

設計原則：
    - 不呼叫 tsr.utils.remove_background（避開 rembg/onnxruntime 依賴）
    - 預期輸入是 SDXL 已產出的白底 anime portrait（無透明 alpha 也可）
    - 自動 resize 到 TSR 期望的 cond_image_size（config 預設 512）
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from PIL import Image

from ..safety.hardware_guard import HardwareGuard
from ..safety.model_loader import ModelKind, ModelLoader
from ..utils.logging_setup import get_logger

if TYPE_CHECKING:
    import trimesh

_log = get_logger(__name__)


# 預設 TripoSR 原始碼放在 external/TripoSR；首次 import 才把它加進 sys.path
_TRIPOSR_REPO_ROOT = Path(__file__).resolve().parents[3] / "external" / "TripoSR"


def _ensure_tsr_on_path() -> None:
    """把 external/TripoSR 加到 sys.path（idempotent）。"""
    p = str(_TRIPOSR_REPO_ROOT)
    if _TRIPOSR_REPO_ROOT.exists() and p not in sys.path:
        sys.path.insert(0, p)
        _log.debug("Added {} to sys.path", p)


class ImageTo3D:
    """PIL Image → 3D mesh。

    用法：
        i23 = ImageTo3D(loader, guard, paths.models)
        mesh = i23.generate(sdxl_pil_image)   # → trimesh.Trimesh
        mesh.export("output/character.obj")
    """

    HF_REPO = "stabilityai/TripoSR"

    DEFAULT_MC_RESOLUTION = 256
    """marching cubes 解析度。256 = 高品質但 PyMCubes CPU 約 10-30 秒；
    128 = 較粗但 ~3 秒。權衡：MVP2 預設 256（品質第一）。"""

    DEFAULT_CHUNK_SIZE = 8192
    """TSR renderer chunk_size — 控制每批處理 voxel 數量；越大越快但 VRAM 更高。
    8192 是官方 README 建議的 RTX 3060 級別保守值。"""

    DEFAULT_FOREGROUND_RATIO = 0.85
    """resize_foreground 比例：把主體 (前景) 縮放至 image 的 85%。
    TSR 訓練時用 0.85，太大主體出框，太小主體太小細節糊。"""

    def __init__(
        self,
        loader: ModelLoader,
        guard: HardwareGuard,
        models_dir: Path,
        mc_resolution: int | None = None,
        chunk_size: int | None = None,
        foreground_ratio: float | None = None,
        cache_dir: Path | None = None,
    ):
        """
        Args:
            loader, guard: 安全護欄三件組。
            models_dir: 專案 models/ 目錄；本類目前不存 ckpt 在此（HF cache）。
                預留參數方便未來改成自管 cache。
            mc_resolution: 256 = 高品質、128 = 快測。
            chunk_size: renderer 分批大小，調小可降 VRAM peak。
            foreground_ratio: TSR 預處理參數，預設 0.85。
            cache_dir: 若指定，會 set HF_HOME 把 ckpt 下載到此路徑。
                None = 用 HuggingFace 預設 (~/.cache/huggingface/)。
        """
        self._loader = loader
        self._guard = guard
        self._models_dir = Path(models_dir)
        self._mc_resolution = mc_resolution or self.DEFAULT_MC_RESOLUTION
        self._chunk_size = chunk_size or self.DEFAULT_CHUNK_SIZE
        self._foreground_ratio = foreground_ratio or self.DEFAULT_FOREGROUND_RATIO
        self._cache_dir = cache_dir

    # ---------------- public ---------------- #

    def generate(
        self,
        image: Image.Image,
        progress_cb: Callable[[str, int, int], None] | None = None,
    ) -> "trimesh.Trimesh":
        """SDXL anime portrait → 3D textured mesh.

        Args:
            image: PIL Image（RGB 或 RGBA）。建議 1024×1024 白底。
            progress_cb: 可選 (stage, cur, total) 回呼，stage ∈ {"preprocess",
                "infer", "extract_mesh"}.

        Returns:
            trimesh.Trimesh，已含 vertex_colors，可直接 export .obj/.glb。

        Raises:
            FileNotFoundError: external/TripoSR 不存在。
            SafetyAbort: HardwareGuard 中止。
        """
        if not _TRIPOSR_REPO_ROOT.exists():
            raise FileNotFoundError(
                f"TripoSR 程式碼未找到：{_TRIPOSR_REPO_ROOT}\n"
                f"請先 `git clone https://github.com/VAST-AI-Research/TripoSR.git "
                f"{_TRIPOSR_REPO_ROOT}`"
            )

        def _loader_fn():
            return self._build_model()

        def _unloader_fn(model: Any):
            self._free_model(model)

        with self._loader.acquire(ModelKind.TRIPO_SR, _loader_fn, _unloader_fn) as model:
            # Post-load recovery：TSR ckpt 載入瞬間 RAM 可能 spike → guard 設 abort
            # 但載完 RAM 已回落 → 給系統幾秒回穩，嘗試清 abort 再繼續
            self._post_load_recovery()
            self._guard.check_or_raise()
            return self._run(model, image, progress_cb)

    # ---------------- internal ---------------- #

    def _build_model(self):
        """Lazy import TSR 並從 HF Hub 載入（首次 ~1.7 GB）。"""
        if self._cache_dir is not None:
            os.environ.setdefault("HF_HOME", str(self._cache_dir))

        _ensure_tsr_on_path()

        import torch
        from tsr.system import TSR  # noqa: E402

        _log.info(
            "Loading TripoSR from HuggingFace ({}) — first run downloads ~1.7 GB",
            self.HF_REPO,
        )
        model = TSR.from_pretrained(
            self.HF_REPO,
            config_name="config.yaml",
            weight_name="model.ckpt",
        )
        model.renderer.set_chunk_size(self._chunk_size)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)
        _log.info("TripoSR ready on device={}", device)
        return model

    def _post_load_recovery(self) -> None:
        """TSR ckpt 載入後若 abort_event 仍鎖定，給系統時間回落並嘗試解鎖。

        Race scenario: torch.load(weight_path, map_location="cpu") 把 1.7GB ckpt
        塞進 CPU RAM，瞬間 RAM 可能達 97%+。.to("cuda") 後 CPU RAM 釋放。
        但 HardwareGuard 可能已設了 abort_event；本方法輪詢清掉它。
        """
        if not getattr(self._guard, "abort_event", None) or not self._guard.abort_event.is_set():
            return
        _log.info("Post-TSR-load abort_event set, attempting recovery...")
        for attempt in range(8):
            time.sleep(0.5)
            if self._guard.try_clear_abort_if_recovered(source=f"image_to_3d att{attempt}"):
                _log.info("✓ Recovered after attempt {}", attempt)
                return
        _log.warning("Could not clear abort_event after 4s; downstream check_or_raise will raise")

    def _free_model(self, model: Any) -> None:
        """釋放模型；ModelLoader 後續會 cuda.empty_cache。"""
        try:
            # 把 model 從 cuda 拉回 cpu，避免 cuda.empty_cache 卡 fragments
            model.to("cpu")
        except Exception:  # noqa: BLE001
            pass
        try:
            del model
        except Exception:  # noqa: BLE001
            pass

    def _run(
        self,
        model: Any,
        image: Image.Image,
        progress_cb: Callable[[str, int, int], None] | None,
    ) -> "trimesh.Trimesh":
        """核心推論：preprocess → infer → extract_mesh。"""
        import torch

        _ensure_tsr_on_path()
        from tsr.utils import resize_foreground  # noqa: E402

        # ---- Stage A: preprocess ---- #
        if progress_cb:
            progress_cb("preprocess", 0, 1)

        prepared = self._preprocess(image, resize_foreground)
        self._save_debug_image(prepared, "_last_triposr_input.png")

        if progress_cb:
            progress_cb("preprocess", 1, 1)

        # ---- Stage B: forward (image → triplane scene_codes) ---- #
        if progress_cb:
            progress_cb("infer", 0, 1)

        device = next(model.parameters()).device
        with torch.no_grad():
            scene_codes = model([prepared], device=str(device))

        self._guard.check_or_raise()
        if progress_cb:
            progress_cb("infer", 1, 1)

        # ---- Stage C: extract_mesh (marching cubes via PyMCubes shim) ---- #
        if progress_cb:
            progress_cb("extract_mesh", 0, 1)

        meshes = model.extract_mesh(
            scene_codes,
            True,  # has_vertex_color
            resolution=self._mc_resolution,
        )
        if not meshes:
            raise RuntimeError("TripoSR returned no meshes")
        mesh = meshes[0]

        if progress_cb:
            progress_cb("extract_mesh", 1, 1)

        _log.info(
            "TripoSR mesh: {} verts / {} faces / has_colors={}",
            len(mesh.vertices), len(mesh.faces),
            mesh.visual is not None and getattr(mesh.visual, "vertex_colors", None) is not None,
        )
        return mesh

    def _preprocess(
        self,
        image: Image.Image,
        resize_foreground_fn: Callable[..., Image.Image],
    ) -> Image.Image:
        """SDXL 白底圖 → TSR 期望輸入（中性灰 0.5 背景 + foreground resized）。

        SDXL 預設輸出 RGB 接近白底；TSR 期望 RGBA + 中性灰 BG。
        若已是 RGBA 且帶 alpha，直接用；否則用 rembg 做 alpha matting。
        rembg 不在時退回到簡單白色閾值（可能不準）。
        """
        import numpy as np

        # 1) 取得帶 alpha 的 RGBA
        if image.mode == "RGBA" and np.array(image)[..., 3].min() < 255:
            rgba = image  # 已有 alpha
        else:
            rgba = self._remove_background(image)

        # 2) 縮放前景到 image 的 0.85 比例
        rgba = resize_foreground_fn(rgba, self._foreground_ratio)

        # 3) bg=0.5 中性灰合成 → RGB
        arr = np.array(rgba).astype(np.float32) / 255.0
        rgb = arr[..., :3] * arr[..., 3:4] + (1.0 - arr[..., 3:4]) * 0.5
        return Image.fromarray((rgb * 255.0).astype(np.uint8), mode="RGB")

    @staticmethod
    def _remove_background(image: Image.Image) -> Image.Image:
        """嘗試用 rembg；失敗則退回簡單白色閾值。"""
        import numpy as np

        try:
            import rembg  # noqa: PLC0415
            _log.info("Using rembg for alpha matting...")
            rgba = rembg.remove(image.convert("RGB"))
            if rgba.mode != "RGBA":
                rgba = rgba.convert("RGBA")
            return rgba
        except Exception as e:  # noqa: BLE001
            _log.warning(
                "rembg unavailable ({}: {}); falling back to white-bg threshold",
                type(e).__name__, e,
            )
            rgba = image.convert("RGBA")
            arr = np.array(rgba)
            white_mask = (arr[..., :3] >= 230).all(axis=-1)
            arr[white_mask, 3] = 0
            return Image.fromarray(arr, mode="RGBA")

    @staticmethod
    def _save_debug_image(img: Image.Image, filename: str) -> None:
        """除錯：每次跑都覆寫存一份 TSR 實際輸入到 output/ 方便排錯。"""
        try:
            debug_path = Path(__file__).resolve().parents[3] / "output" / filename
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(debug_path)
            _log.debug("Saved TripoSR debug input to {}", debug_path.name)
        except Exception:  # noqa: BLE001
            pass
