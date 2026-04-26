"""資源偵測 — 哪些 AI 模型 / 第三方資產已就緒，哪些還缺。

setup_wizard 用此模組決定：
    - 全部就緒 → 不跳 wizard，直接進主介面
    - 部分缺漏 → 跳 wizard 並只下載缺漏項
    - 全缺 → 完整 first-run 流程

每項資源的偵測都是「fast path 路徑檢查」（無 import 重模組、無網路），
讓 main.py 開機時 100ms 內判斷完。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from ..config.paths import Paths
from ..utils.logging_setup import get_logger

_log = get_logger(__name__)


class ResourceState(str, Enum):
    """資源就緒狀態。"""

    READY = "ready"          # 已下載且驗證 OK
    MISSING = "missing"       # 完全沒有
    PARTIAL = "partial"       # 部分檔案存在但不完整
    UNKNOWN = "unknown"       # 偵測失敗（如 Ollama 服務沒開）


@dataclass
class ResourceStatus:
    """單一資源的偵測結果。"""

    key: str
    """資源識別 key（如 'sdxl_animagine' / 'triposr_repo' / 'ollama_gemma4_e2b'）。"""

    display_name: str
    """UI 顯示名（如 'SDXL AnimagineXL 4.0'）。"""

    state: ResourceState
    expected_size_mb: int = 0
    actual_size_mb: int = 0
    detail: str = ""

    @property
    def needs_download(self) -> bool:
        return self.state in (ResourceState.MISSING, ResourceState.PARTIAL)


@dataclass
class ResourceCheck:
    """全部資源的偵測結果集合。"""

    items: list[ResourceStatus] = field(default_factory=list)

    @property
    def all_ready(self) -> bool:
        return all(s.state == ResourceState.READY for s in self.items)

    @property
    def missing(self) -> list[ResourceStatus]:
        return [s for s in self.items if s.needs_download]

    @property
    def total_download_mb(self) -> int:
        return sum(s.expected_size_mb - s.actual_size_mb for s in self.missing)


# ---------------- 個別偵測器 ---------------- #


def _detect_sdxl(paths: Paths) -> ResourceStatus:
    """SDXL AnimagineXL 4.0 — 看 model_index.json 是否存在。"""
    index = paths.models / "sdxl" / "animagine-xl-4.0" / "model_index.json"
    if index.exists():
        # 估磁碟大小
        d = paths.models / "sdxl" / "animagine-xl-4.0"
        size_mb = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) // (1024 * 1024)
        return ResourceStatus(
            key="sdxl_animagine",
            display_name="SDXL AnimagineXL 4.0",
            state=ResourceState.READY,
            expected_size_mb=6500,
            actual_size_mb=size_mb,
            detail=f"{size_mb} MB on disk",
        )
    return ResourceStatus(
        key="sdxl_animagine",
        display_name="SDXL AnimagineXL 4.0",
        state=ResourceState.MISSING,
        expected_size_mb=6500,
    )


def _detect_ip_adapter(paths: Paths) -> tuple[ResourceStatus, ResourceStatus]:
    """IP-Adapter Plus Face + image_encoder（兩個獨立資源）。"""
    weight = paths.models / "ip_adapter" / "ip-adapter-plus-face_sdxl_vit-h.bin"
    encoder = paths.models / "ip_adapter" / "image_encoder" / "model.safetensors"

    weight_status = ResourceStatus(
        key="ip_adapter_weight",
        display_name="IP-Adapter Plus Face SDXL",
        state=ResourceState.READY if weight.exists() else ResourceState.MISSING,
        expected_size_mb=1009,
        actual_size_mb=(weight.stat().st_size // (1024 * 1024)) if weight.exists() else 0,
    )
    encoder_status = ResourceStatus(
        key="ip_adapter_encoder",
        display_name="IP-Adapter image_encoder (CLIP ViT-H)",
        state=ResourceState.READY if encoder.exists() else ResourceState.MISSING,
        expected_size_mb=2528,
        actual_size_mb=(encoder.stat().st_size // (1024 * 1024)) if encoder.exists() else 0,
    )
    return weight_status, encoder_status


def _detect_triposr_repo(paths: Paths) -> ResourceStatus:
    """TripoSR git clone 是否存在。"""
    repo_root = paths.root / "external" / "TripoSR"
    system_py = repo_root / "tsr" / "system.py"
    if system_py.exists():
        return ResourceStatus(
            key="triposr_repo",
            display_name="TripoSR source code",
            state=ResourceState.READY,
            expected_size_mb=20,
            detail=f"cloned at {repo_root}",
        )
    return ResourceStatus(
        key="triposr_repo",
        display_name="TripoSR source code",
        state=ResourceState.MISSING,
        expected_size_mb=20,
        detail="git clone https://github.com/VAST-AI-Research/TripoSR.git",
    )


def _detect_triposr_ckpt(paths: Paths) -> ResourceStatus:
    """TripoSR checkpoint — HF cache 內 stabilityai/TripoSR snapshot 是否存在。"""
    # HF cache 預設路徑
    hf_cache = Path.home() / ".cache" / "huggingface" / "hub" / "models--stabilityai--TripoSR"
    if hf_cache.exists():
        # 找 snapshots/<rev>/model.ckpt
        snapshots = hf_cache / "snapshots"
        if snapshots.exists():
            for rev in snapshots.iterdir():
                if (rev / "model.ckpt").exists():
                    size_mb = (rev / "model.ckpt").stat().st_size // (1024 * 1024)
                    return ResourceStatus(
                        key="triposr_ckpt",
                        display_name="TripoSR checkpoint (stabilityai)",
                        state=ResourceState.READY,
                        expected_size_mb=1700,
                        actual_size_mb=size_mb,
                    )
    return ResourceStatus(
        key="triposr_ckpt",
        display_name="TripoSR checkpoint (stabilityai)",
        state=ResourceState.MISSING,
        expected_size_mb=1700,
        detail="auto-downloaded by HF Hub on first inference",
    )


def _detect_rembg_u2net() -> ResourceStatus:
    """rembg 用的 u2net.onnx。"""
    u2net = Path.home() / ".u2net" / "u2net.onnx"
    if u2net.exists():
        return ResourceStatus(
            key="rembg_u2net",
            display_name="rembg u2net.onnx",
            state=ResourceState.READY,
            expected_size_mb=176,
            actual_size_mb=u2net.stat().st_size // (1024 * 1024),
        )
    return ResourceStatus(
        key="rembg_u2net",
        display_name="rembg u2net.onnx",
        state=ResourceState.MISSING,
        expected_size_mb=176,
        detail="auto-downloaded on first rembg.remove() call",
    )


def _detect_ollama_model(model_name: str, display_name: str, base_url: str = "http://localhost:11434") -> ResourceStatus:
    """檢查 Ollama 是否已 pull 指定模型。"""
    try:
        import requests
        r = requests.get(f"{base_url}/api/tags", timeout=3)
        r.raise_for_status()
        models = {m["name"] for m in r.json().get("models", [])}
        if model_name in models:
            return ResourceStatus(
                key=f"ollama_{model_name.replace(':', '_')}",
                display_name=display_name,
                state=ResourceState.READY,
            )
        return ResourceStatus(
            key=f"ollama_{model_name.replace(':', '_')}",
            display_name=display_name,
            state=ResourceState.MISSING,
            expected_size_mb=2000,  # 估值
            detail=f"ollama pull {model_name}",
        )
    except Exception as e:  # noqa: BLE001
        return ResourceStatus(
            key=f"ollama_{model_name.replace(':', '_')}",
            display_name=display_name,
            state=ResourceState.UNKNOWN,
            detail=f"Ollama service unreachable: {type(e).__name__}",
        )


def _detect_base_vrm(paths: Paths, sample_id: str) -> ResourceStatus:
    """VRoid AvatarSample VRM 是否就位。"""
    p = paths.base_models / f"AvatarSample_{sample_id}.vrm"
    if p.exists():
        return ResourceStatus(
            key=f"base_vrm_{sample_id.lower()}",
            display_name=f"VRoid AvatarSample_{sample_id}.vrm",
            state=ResourceState.READY,
            expected_size_mb=15,
            actual_size_mb=p.stat().st_size // (1024 * 1024),
        )
    return ResourceStatus(
        key=f"base_vrm_{sample_id.lower()}",
        display_name=f"VRoid AvatarSample_{sample_id}.vrm",
        state=ResourceState.MISSING,
        expected_size_mb=15,
    )


# ---------------- 主入口 ---------------- #


def check_all_resources(
    paths: Paths,
    ollama_base_url: str = "http://localhost:11434",
    progress_cb: Callable[[str], None] | None = None,
) -> ResourceCheck:
    """偵測所有資源，回傳 ResourceCheck。

    Args:
        paths: 專案路徑物件
        ollama_base_url: Ollama 服務 URL
        progress_cb: 可選 (item_name) 回呼，用於在 UI 顯示「正在檢查 X...」

    Returns:
        ResourceCheck 含 9 項資源狀態
    """
    items: list[ResourceStatus] = []

    def _step(name: str):
        if progress_cb:
            progress_cb(name)
        _log.debug("Checking {}", name)

    _step("SDXL AnimagineXL 4.0")
    items.append(_detect_sdxl(paths))

    _step("IP-Adapter Plus Face")
    ipa_w, ipa_e = _detect_ip_adapter(paths)
    items.append(ipa_w)
    items.append(ipa_e)

    _step("TripoSR repo")
    items.append(_detect_triposr_repo(paths))

    _step("TripoSR checkpoint")
    items.append(_detect_triposr_ckpt(paths))

    _step("rembg u2net.onnx")
    items.append(_detect_rembg_u2net())

    _step("Ollama gemma4:e2b")
    items.append(_detect_ollama_model("gemma4:e2b", "Ollama gemma4:e2b (SDXL prompt)", ollama_base_url))

    _step("Ollama qwen2.5:3b")
    items.append(_detect_ollama_model("qwen2.5:3b", "Ollama qwen2.5:3b (Persona)", ollama_base_url))

    _step("Base VRM A/B/C")
    for sid in ("A", "B", "C"):
        items.append(_detect_base_vrm(paths, sid))

    return ResourceCheck(items=items)
