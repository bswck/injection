from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from injection.main import injection

if TYPE_CHECKING:
    from contextvars import ContextVar
    from typing import TypeVar

    from injection.main import Injection, Locals

    T = TypeVar("T")


def pep567_factory(cv: ContextVar[T], scope: Locals) -> T:  # noqa: ARG001
    return cv.get()


def pep567_injection(*aliases: str, into: Locals, cv: ContextVar[T]) -> Injection[T]:
    factory = partial(pep567_factory, cv)
    return injection(*aliases, into=into, factory=factory, dynamic=True)
