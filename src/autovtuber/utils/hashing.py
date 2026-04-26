"""串流式 SHA-256 計算（避免大檔一次讀進記憶體）。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable


_DEFAULT_CHUNK = 1024 * 1024  # 1 MiB


def sha256_file(
    path: Path,
    chunk_size: int = _DEFAULT_CHUNK,
    progress: Callable[[int, int], None] | None = None,
) -> str:
    """計算檔案 SHA-256；回傳 hex 字串（lowercase）。

    Args:
        path: 檔案絕對路徑
        chunk_size: 每次讀取大小，預設 1 MiB
        progress: 進度回呼 `(read_bytes, total_bytes)`，可選

    Raises:
        FileNotFoundError: 檔案不存在
    """
    p = Path(path)
    total = p.stat().st_size
    h = hashlib.sha256()
    read = 0
    with p.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
            read += len(chunk)
            if progress is not None:
                progress(read, total)
    return h.hexdigest()


def verify_sha256(path: Path, expected: str) -> bool:
    """驗證檔案 hash；大小寫不敏感比對。"""
    actual = sha256_file(path)
    return actual.lower() == expected.lower().strip()
