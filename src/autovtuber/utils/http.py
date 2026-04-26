"""共用 HTTP session — 含重試 + 斷點續傳下載。"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .logging_setup import get_logger

_log = get_logger(__name__)


def make_session(retries: int = 3, backoff: float = 0.5) -> requests.Session:
    """回傳具自動重試的 requests Session。"""
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(500, 502, 503, 504, 429),
        allowed_methods=("GET", "HEAD", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "AutoVtuber/0.1"})
    return session


def download_file(
    url: str,
    dest: Path,
    expected_sha256: str | None = None,
    progress: Callable[[int, int], None] | None = None,
    chunk_size: int = 1024 * 1024,
    session: requests.Session | None = None,
) -> Path:
    """下載到 `dest`，支援斷點續傳；下載完成後可選擇驗證 SHA-256。

    存在 `dest.partial` 暫存檔，完成後 rename 為 `dest`。
    若 `dest` 已存在且 SHA 正確，直接回傳不重下。

    Raises:
        ValueError: SHA-256 驗證失敗
        requests.HTTPError: 下載失敗（重試後仍失敗）
    """
    from .hashing import verify_sha256

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and expected_sha256 and verify_sha256(dest, expected_sha256):
        _log.info("✓ Already present, hash OK: {}", dest.name)
        return dest

    sess = session or make_session()
    partial = dest.with_suffix(dest.suffix + ".partial")
    headers = {}
    resume_from = partial.stat().st_size if partial.exists() else 0
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"
        _log.info("Resuming download from byte {} → {}", resume_from, dest.name)

    with sess.get(url, headers=headers, stream=True, timeout=(10, 60)) as r:
        if r.status_code == 416:
            # Server says we already have the whole file
            partial.rename(dest)
            return _verify_or_raise(dest, expected_sha256)
        r.raise_for_status()

        total = int(r.headers.get("Content-Length", 0)) + resume_from
        mode = "ab" if resume_from > 0 else "wb"
        downloaded = resume_from
        with partial.open(mode) as f:
            for chunk in r.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total)

    partial.rename(dest)
    return _verify_or_raise(dest, expected_sha256)


def _verify_or_raise(path: Path, expected_sha256: str | None) -> Path:
    if expected_sha256:
        from .hashing import verify_sha256
        if not verify_sha256(path, expected_sha256):
            path.unlink(missing_ok=True)
            raise ValueError(f"SHA-256 mismatch on {path.name} — file removed")
        _log.info("✓ SHA-256 OK: {}", path.name)
    return path
