"""SetupDownloader — 對 ResourceStatus 派遣對應下載方法。

不同來源策略：
    - HF Hub model 檔（SDXL, IP-Adapter weight/encoder）→ huggingface_hub.snapshot_download
    - git repo（TripoSR）                              → subprocess git clone
    - Ollama 模型                                      → POST /api/pull stream
    - 直連 URL（VRoid base VRM）                       → utils.http.download_file
    - rembg u2net、TripoSR ckpt                         → 自動下載（不需主動處理）
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from ..config.paths import Paths
from ..utils.http import download_file, make_session
from ..utils.logging_setup import get_logger
from .resource_check import ResourceStatus

_log = get_logger(__name__)


# 進度 callback：(downloaded_bytes, total_bytes)
ProgressCb = Callable[[int, int], None]


class SetupDownloader:
    """根據 ResourceStatus.key dispatch 到對應下載邏輯。"""

    def __init__(self, paths: Paths, ollama_base_url: str = "http://localhost:11434"):
        self._paths = paths
        self._ollama_url = ollama_base_url
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def download(
        self,
        resource: ResourceStatus,
        progress_cb: ProgressCb | None = None,
    ) -> tuple[bool, str]:
        """執行單一資源下載；回傳 (ok, error_message)。"""
        if self._cancelled:
            return False, "cancelled"

        key = resource.key
        try:
            if key == "sdxl_animagine":
                return self._dl_hf_snapshot(
                    "cagliostrolab/animagine-xl-4.0",
                    self._paths.models / "sdxl" / "animagine-xl-4.0",
                    progress_cb,
                )
            if key == "ip_adapter_weight":
                return self._dl_hf_file(
                    "h94/IP-Adapter",
                    "sdxl_models/ip-adapter-plus-face_sdxl_vit-h.bin",
                    self._paths.models / "ip_adapter" / "ip-adapter-plus-face_sdxl_vit-h.bin",
                    progress_cb,
                )
            if key == "ip_adapter_encoder":
                return self._dl_hf_snapshot(
                    "h94/IP-Adapter",
                    self._paths.models / "ip_adapter" / "image_encoder",
                    progress_cb,
                    allow_patterns=["models/image_encoder/*"],
                )
            if key == "triposr_repo":
                return self._dl_git_clone(
                    "https://github.com/VAST-AI-Research/TripoSR.git",
                    self._paths.root / "external" / "TripoSR",
                    progress_cb,
                )
            if key == "triposr_ckpt":
                # 由 TSR.from_pretrained 自動下載；提示使用者
                return True, "skipped (auto-downloaded by TSR.from_pretrained on first inference)"
            if key == "rembg_u2net":
                # 由 rembg 自動下載；提示使用者
                return True, "skipped (auto-downloaded by rembg.remove on first call)"
            if key.startswith("ollama_"):
                model_name = resource.display_name.split(" ")[1]  # "Ollama gemma4:e2b ..." → "gemma4:e2b"
                return self._dl_ollama(model_name, progress_cb)
            if key.startswith("base_vrm_"):
                sample_id = key.split("_")[-1].upper()
                return self._dl_base_vrm(sample_id, progress_cb)

            return False, f"unknown resource key: {key}"
        except Exception as e:  # noqa: BLE001
            _log.exception("Download failed for {}", key)
            return False, f"{type(e).__name__}: {e}"

    # ---------------- HF Hub ---------------- #

    def _dl_hf_snapshot(
        self,
        repo_id: str,
        local_dir: Path,
        progress_cb: ProgressCb | None,
        allow_patterns: list[str] | None = None,
    ) -> tuple[bool, str]:
        from huggingface_hub import snapshot_download

        local_dir.mkdir(parents=True, exist_ok=True)
        # snapshot_download 自帶 retry + resume；只需指定 local_dir
        snapshot_download(
            repo_id=repo_id,
            local_dir=str(local_dir),
            allow_patterns=allow_patterns,
            local_dir_use_symlinks=False,  # Windows 沒 symlink 權限會 fallback hardlink
        )
        # 沒辦法準確報 progress（snapshot_download 沒原生 callback），給 100%
        if progress_cb:
            progress_cb(100, 100)
        return True, ""

    def _dl_hf_file(
        self,
        repo_id: str,
        filename: str,
        dest: Path,
        progress_cb: ProgressCb | None,
    ) -> tuple[bool, str]:
        from huggingface_hub import hf_hub_download

        dest.parent.mkdir(parents=True, exist_ok=True)
        downloaded = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(dest.parent),
        )
        # hf_hub_download 把檔案放進子目錄，需 move
        downloaded_path = Path(downloaded)
        if downloaded_path != dest and downloaded_path.exists():
            shutil.move(str(downloaded_path), str(dest))
        if progress_cb:
            progress_cb(100, 100)
        return True, ""

    # ---------------- git clone ---------------- #

    def _dl_git_clone(
        self,
        url: str,
        dest: Path,
        progress_cb: ProgressCb | None,
    ) -> tuple[bool, str]:
        if dest.exists():
            return True, "already cloned"
        dest.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return False, f"git clone failed: {result.stderr.strip()}"
        if progress_cb:
            progress_cb(100, 100)
        return True, ""

    # ---------------- Ollama API stream ---------------- #

    def _dl_ollama(self, model_name: str, progress_cb: ProgressCb | None) -> tuple[bool, str]:
        """POST /api/pull 串流下載 Ollama 模型。"""
        session = make_session()
        try:
            r = session.post(
                f"{self._ollama_url}/api/pull",
                json={"name": model_name, "stream": True},
                stream=True,
                timeout=300,
            )
            r.raise_for_status()
            total_bytes = 0
            done_bytes = 0
            for line in r.iter_lines(decode_unicode=True):
                if self._cancelled:
                    return False, "cancelled"
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Ollama 串流訊息格式包含 status / digest / total / completed
                if "total" in data and data["total"] > 0:
                    total_bytes = data["total"]
                if "completed" in data:
                    done_bytes = data["completed"]
                if progress_cb and total_bytes > 0:
                    progress_cb(done_bytes, total_bytes)
                if data.get("status") == "success":
                    if progress_cb:
                        progress_cb(total_bytes or 100, total_bytes or 100)
                    return True, ""
            return True, "stream ended without explicit success"
        except Exception as e:  # noqa: BLE001
            return False, f"{type(e).__name__}: {e}"

    # ---------------- 直連 URL ---------------- #

    def _dl_base_vrm(self, sample_id: str, progress_cb: ProgressCb | None) -> tuple[bool, str]:
        url = (
            f"https://github.com/madjin/vrm-samples/raw/master/vroid/stable/"
            f"AvatarSample_{sample_id}.vrm"
        )
        dest = self._paths.base_models / f"AvatarSample_{sample_id}.vrm"
        # 已知的 sha256（從 manifest）
        known_sha = {
            "A": "b86b0b8a66d48911431d6f920a5211a974226f83aa672eca3f3dfade58ac346e",
            "B": "4a271bd3b5a3d19e054fd113ee154635b72e7141f4a8ccbcdba3c7f9cea6ee8d",
            "C": "395d5b04696e888f07bc856ae01bf72a974b7e773132c7443dc59d1688045b8a",
        }
        download_file(
            url=url,
            dest=dest,
            expected_sha256=known_sha.get(sample_id),
            progress=progress_cb,
        )
        return True, ""
