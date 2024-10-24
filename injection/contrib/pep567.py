from __future__ import annotations

from typing import TYPE_CHECKING

from injection.main import injection

if TYPE_CHECKING:
    from contextvars import ContextVar
    from typing import TypeVar

    from injection.main import Injection, Locals

    T = TypeVar("T")


def pep567_injection(
    *aliases: str,
    cv: ContextVar[T],
    into: Locals | None = None,
) -> Injection[T]:
    return injection(*aliases, into=into, factory=cv.get, cache_per_alias=True)
