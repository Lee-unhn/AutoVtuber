"""簡單階段計時器。

用法：
    @stage_timer("生成臉部圖")
    def generate_face(...): ...

    或：
    with StageTimer("VRM 組裝") as t:
        ...
    print(t.elapsed_seconds)
"""
from __future__ import annotations

import time
from contextlib import ContextDecorator
from functools import wraps
from typing import Any, Callable

from .logging_setup import get_logger

_log = get_logger(__name__)


class StageTimer(ContextDecorator):
    """Context manager + decorator 計時。"""

    def __init__(self, label: str, log: bool = True):
        self.label = label
        self.log = log
        self._start: float = 0.0
        self.elapsed_seconds: float = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        if self.log:
            _log.info("⏱️  [start] {}", self.label)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.elapsed_seconds = time.perf_counter() - self._start
        if self.log:
            if exc_type is None:
                _log.info("⏱️  [done ] {} — {:.2f}s", self.label, self.elapsed_seconds)
            else:
                _log.warning(
                    "⏱️  [FAIL ] {} — {:.2f}s — {}: {}",
                    self.label,
                    self.elapsed_seconds,
                    exc_type.__name__,
                    exc,
                )
        # 不吞例外
        return False


def stage_timer(label: str | None = None, log: bool = True) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """函式裝飾器版本。`label` 若 None 則用函式名稱。"""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        nonlocal label
        actual_label = label or func.__qualname__

        @wraps(func)
        def wrapper(*args, **kwargs):
            with StageTimer(actual_label, log=log):
                return func(*args, **kwargs)

        return wrapper

    return decorator
