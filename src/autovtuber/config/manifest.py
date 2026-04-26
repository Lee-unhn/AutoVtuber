"""載入 docs/DOWNLOAD_MANIFEST.md 中的模型下載清單。

manifest 是 markdown 表格，每行一個檔案：
| key | url | sha256 | size_mb | dest_relative |

Setup wizard 用此清單決定要下載什麼。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ManifestEntry:
    key: str
    url: str
    sha256: str
    size_mb: int
    dest_relative: str  # 相對 models/ 目錄

    @property
    def is_known_size(self) -> bool:
        return self.size_mb > 0


_TABLE_ROW = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*(https?://[^|\s]+)\s*\|\s*([a-fA-F0-9]{64})\s*\|"
    r"\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*$"
)


def load_manifest(manifest_path: Path) -> list[ManifestEntry]:
    """解析 manifest markdown 檔，回傳所有條目。

    缺檔或無條目時回傳空 list（讓 setup wizard 顯示友善訊息，而非崩潰）。
    """
    if not manifest_path.exists():
        return []
    entries: list[ManifestEntry] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        m = _TABLE_ROW.match(line)
        if not m:
            continue
        entries.append(
            ManifestEntry(
                key=m.group(1).strip(),
                url=m.group(2).strip(),
                sha256=m.group(3).strip().lower(),
                size_mb=int(m.group(4)),
                dest_relative=m.group(5).strip(),
            )
        )
    return entries


def total_download_size_mb(entries: list[ManifestEntry]) -> int:
    return sum(e.size_mb for e in entries if e.is_known_size)
