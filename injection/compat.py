from __future__ import annotations

import platform
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import FrameType


__all__ = ("get_frame",)


def get_frame(level: int = 0, remedy: str | None = None) -> FrameType:
    """Attempt to get a frame from the interpreter stack."""
    level += 1  # This frame.

    if not hasattr(sys, "_getframe"):
        msg = (
            "`sys._getframe()` is unavailable in this "
            f"Python implementation - {platform.python_implementation}"
        )
        if remedy:
            msg += f"\n{remedy}"
        raise RuntimeError(msg)

    return sys._getframe(level)  # noqa: SLF001
