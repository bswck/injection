"""Pure-Python implementation of PEP 690 in an opt-in fashion."""

from __future__ import annotations

import sys
from builtins import __import__ as builtin_import
from collections.abc import Generator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from copy import copy
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, overload

from injection.compat import get_frame
from injection.main import peek_or_inject

if TYPE_CHECKING:
    from typing_extensions import TypeAlias

    from injection.main import Injection


T = TypeVar("T")
Obj = TypeVar("Obj")
InjectedAttributeStash: TypeAlias = "dict[Injection[Obj], T]"


class StateActionType(Enum):
    PERSIST = auto()
    """Copy state visible now and expose it to the original thread on future request."""

    FUTURE = auto()
    """
    Allow the state to evolve naturally at runtime.

    Rely on that future version of the state when it's requested.
    """

    CONSTANT = auto()
    """Define one state forever (like PERSIST, but with custom value)."""


class StateAction(Generic[T]):
    if TYPE_CHECKING:

        @overload
        def __init__(
            self,
            action_type: Literal[StateActionType.PERSIST, StateActionType.FUTURE],
            data: None = None,
        ) -> None: ...

        @overload
        def __init__(
            self,
            action_type: Literal[StateActionType.CONSTANT],
            data: T,
        ) -> None: ...

    def __init__(
        self,
        action_type: StateActionType,
        data: T | None = None,
    ) -> None:
        self.action_type = action_type
        self.data = data


PERSIST: StateAction[None] = StateAction(StateActionType.PERSIST)
FUTURE: StateAction[None] = StateAction(StateActionType.FUTURE)


injection_var: ContextVar[Injection[Any]] = ContextVar("injection")


@dataclass
class DynamicSysAttribute:
    attribute_name: str
    mainstream_value: Any
    stash: InjectedAttributeStash[Injection[Any], Any]

    def __call__(self) -> Any:
        with suppress(LookupError):
            injection = injection_var.get()
            mapping = self.stash[injection]
            return mapping[injection]
        return self.mainstream_value


@dataclass
class InjectedImportFunction:
    modules_affected: set[str] = field(default_factory=set)

    def __call__(self, *args: Any) -> Any:
        if get_frame(1).f_globals["__name__"] in self.modules_affected:
            return builtin_import(*args)  # lazy (traceback note)
        return builtin_import(*args)  # eager (traceback note)


@contextmanager
def lazy_imports(
    *,
    module_name: str | None = None,
    stack_offset: int = 1,
    sys_path: StateAction[Any] = PERSIST,
    sys_meta_path: StateAction[Any] = PERSIST,
    sys_path_hooks: StateAction[Any] = PERSIST,
) -> Generator[None]:
    stack_offset += 1  # from @contextmanager
    stash: dict[Injection[Any], Any] = {}

    for attribute_name, action in (
        ("path", sys_path),
        ("meta_path", sys_meta_path),
        ("path_hooks", sys_path_hooks),
    ):
        mainstream_value = getattr(sys, attribute_name)
        if action.action_type is StateActionType.PERSIST:
            action.data = copy(mainstream_value)
            action.action_type = StateActionType.CONSTANT

        peek_or_inject(
            vars(sys),
            attribute_name,
            metafactory=lambda: DynamicSysAttribute(
                attribute_name=attribute_name,  # noqa: B023
                mainstream_value=mainstream_value,  # noqa: B023
                stash=stash,
            ),
        ).__inject__()

    frame = get_frame(stack_offset)
    if not isinstance(
        import_function := frame.f_builtins.get("__import__"),
        InjectedImportFunction,
    ):
        frame.f_builtins["__import__"] = import_function = InjectedImportFunction()

    if module_name is None:
        try:
            module_name = frame.f_locals["__name__"]
        except KeyError as e:
            msg = "cannot retrieve callee module `__name__`"
            raise ValueError(msg) from e

    import_function.modules_affected.add(module_name)

    yield
