# ruff: noqa: FBT001, SLF001
from __future__ import annotations

import sys
import types
from importlib import reload
from typing import Any
from unittest.mock import patch

import pytest

from injection import compat


def in_compat_get_frame(*, stack_offset: int) -> bool:
    """Check whether the caller is [`injection.compat.get_frame`][]."""
    frame = sys._getframe(stack_offset)
    return (
        frame.f_code.co_filename == compat.__file__
        and frame.f_code.co_name == "get_frame"
    )


class PatchedSys(types.ModuleType):
    def __getattr__(self, attribute: str) -> Any:
        """Raise [`AttributeError`][] on [`sys._getframe`][] access."""
        if attribute == "_getframe" and in_compat_get_frame(stack_offset=2):
            raise AttributeError
        return getattr(sys, attribute)

    @classmethod
    def with_getframe(cls, *, supported: bool) -> types.ModuleType:
        """Don't patch if supported, patch if unsupported."""
        return sys if supported else cls("sys")


@pytest.mark.parametrize("supported", [False, True])
def test_get_frame(supported: bool) -> None:
    patched_sys = PatchedSys.with_getframe(supported=supported)

    with patch.dict(sys.modules, {"sys": patched_sys}):
        reload(compat)

        if supported:
            assert compat.get_frame(0) is sys._getframe(0)
        else:
            with pytest.raises(
                RuntimeError,
                match="unavailable in this Python implementation",
            ):
                compat.get_frame(0)
