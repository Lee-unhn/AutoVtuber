"""`python -m autovtuber` 入口點。

只負責呼叫 main.main()，所有 bootstrap 邏輯都在 main.py 裡。
"""
from __future__ import annotations

import sys


def main() -> int:
    from autovtuber.main import main as _main
    return _main()


if __name__ == "__main__":
    sys.exit(main())
