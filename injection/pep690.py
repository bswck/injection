from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import Never


def lazy() -> Never:
    raise NotImplementedError


def ast_lazy() -> Never:
    raise NotImplementedError


def types() -> Never:
    raise NotImplementedError


def extras() -> Never:
    raise NotImplementedError
