"""Pure-Python implementation of PEP 690 in an opt-in fashion."""

from __future__ import annotations

import sys
import types
from collections.abc import Callable
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Generic, Literal, TypedDict, overload

if TYPE_CHECKING:
    from _typeshed.importlib import MetaPathFinderProtocol, PathEntryFinderProtocol
    from typing_extensions import Never, TypeVar

    from injection.main import Injection


T = TypeVar("T", default=None)
Obj = TypeVar("Obj")


class SysActions(Enum):
    PERSIST = auto()
    FUTURE = auto()
    CONSTANT = auto()
    SPECIFIED = auto()


class StateAction(Generic[T]):
    if TYPE_CHECKING:

        @overload
        def __init__(
            self,
            action: Literal[SysActions.PERSIST, SysActions.FUTURE],
            data: None = None,
        ) -> None: ...

        @overload
        def __init__(
            self,
            action: Literal[SysActions.CONSTANT],
            data: T,
        ) -> None: ...

    def __init__(self, action: SysActions, data: T | None = None) -> None:
        self.action = action
        self.data = data


PERSIST: StateAction = StateAction(SysActions.PERSIST)
FUTURE: StateAction = StateAction(SysActions.FUTURE)


injection_var: ContextVar[Injection[Any]] = ContextVar("injection")


class AttributeMappings(TypedDict, Generic[Obj]):
    path: dict[Injection[Obj], list[str]]
    path_hooks: dict[Injection[Obj], list[Callable[[str], PathEntryFinderProtocol]]]
    meta_path: dict[Injection[Obj], list[MetaPathFinderProtocol]]


@dataclass
class _LazyImportsSys(types.ModuleType, Generic[Obj]):
    attribute_mappings: AttributeMappings[Obj]

    def __getattr__(self, name: str) -> Any:
        with suppress(LookupError):
            injection = injection_var.get()
            mapping = self.attribute_mappings[name]  # type: ignore[literal-required]
            return mapping[injection]
        return getattr(sys, name)


@dataclass
class LazyImportBuiltin:
    def __call__(self, *args: Any, **kwds: Any) -> Any:
        pass


def lazy_imports(
    *,
    sys_path: StateAction = PERSIST,
    sys_meta_path: StateAction = PERSIST,
    sys_path_hooks: StateAction = PERSIST,
) -> None:
    pass


def type_imports() -> Never:
    raise NotImplementedError
