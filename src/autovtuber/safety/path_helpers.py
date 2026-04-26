"""Windows Unicode 路徑修正 — MediaPipe 等 C++ 套件無法讀含中文/日文的路徑。

策略：
    1. 偵測安裝路徑是否為純 ASCII
    2. 若否，嘗試在 C:\\ 下建立 junction（不需 admin），re-exec Python
    3. 若 junction 建立失敗（disk full、防毒擋下等），警告但繼續
       — face_aligner 會 fallback 到無偵測模式

junction 不同於 symlink，在 Windows 上不需 admin 權限。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..utils.logging_setup import get_logger

_log = get_logger(__name__)

#: 預設 ASCII junction 目標路徑
DEFAULT_JUNCTION = Path("C:/avt")


def path_is_ascii(p: Path) -> bool:
    """檢查路徑是否完全 ASCII（含父目錄）。"""
    try:
        str(p.resolve()).encode("ascii")
        return True
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False


def ensure_ascii_path(project_root: Path, junction: Path = DEFAULT_JUNCTION) -> Path:
    """確保 project_root 從 ASCII 路徑可達。

    回傳 ASCII 版本的 project_root（可能就是 junction 路徑）。
    若已經是 ASCII，原樣回傳。
    若 junction 已存在指向同一目標，直接用。
    若沒有 junction 且無法建立，回原路徑並 log 警告。
    """
    if path_is_ascii(project_root):
        return project_root

    if junction.exists():
        # 檢查 junction 是否指向我們的 project_root
        try:
            target_real = junction.resolve()
            wanted = project_root.resolve()
            if str(target_real).lower() == str(wanted).lower():
                _log.info("Reusing existing junction {} -> {}", junction, wanted)
                return junction
            else:
                _log.warning(
                    "Junction {} points to {} (not {}); cannot use; will run via Unicode path",
                    junction, target_real, wanted,
                )
                return project_root
        except Exception as e:  # noqa: BLE001
            _log.warning("Existing junction unusable: {}", e)
            return project_root

    # 建立 junction
    if sys.platform != "win32":
        return project_root  # 非 Windows，不適用

    try:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(project_root)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode == 0:
            _log.info("Created junction {} -> {}", junction, project_root)
            return junction
        _log.warning(
            "mklink failed (code {}): {}{}",
            result.returncode, result.stdout.strip(), result.stderr.strip(),
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        _log.warning("Could not run mklink: {}", e)
    return project_root


def reexec_via_ascii_if_needed(project_root: Path) -> None:
    """若 sys.executable 來自 Unicode 路徑，且能建立 ASCII junction，re-exec via junction。

    呼叫此函式應該在 `__main__.py` 最早期呼叫，在任何 ML 模組 import 之前。
    若已經在 ASCII 路徑或無法切換，直接回傳（呼叫者繼續執行）。
    """
    if path_is_ascii(Path(sys.executable)):
        return

    ascii_root = ensure_ascii_path(project_root)
    if ascii_root == project_root:
        # 沒有改變
        return

    # 把 sys.executable 重映射到 junction 下
    rel = Path(sys.executable).resolve().relative_to(project_root.resolve())
    new_executable = ascii_root / rel
    if not new_executable.exists():
        _log.warning("Junction created but {} not visible — staying on original path", new_executable)
        return

    # 已經是 re-exec 過的避免無限迴圈
    if os.environ.get("AUTOVTUBER_REEXEC") == "1":
        return

    env = os.environ.copy()
    env["AUTOVTUBER_REEXEC"] = "1"
    args = [str(new_executable)] + sys.argv
    _log.info("Re-exec via ASCII junction: {} {}", new_executable, sys.argv)
    os.execve(str(new_executable), args, env)
