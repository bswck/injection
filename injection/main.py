from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from threading import RLock, get_ident
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, cast, overload

from injection.compat import get_frame

if TYPE_CHECKING:
    from collections.abc import Callable

    from typing_extensions import Self, TypeAlias

    Locals: TypeAlias = "dict[str, Any]"


__all__ = (
    "EarlyObject",
    "InjectionKey",
    "Injection",
    "ObjectState",
    "injection",
)


Object_co = TypeVar("Object_co", covariant=True)


class InjectionKey(str):
    __slots__ = ("origin", "hash", "reset", "early")

    def __init__(self, key: str, early: EarlyObject[object]) -> None:
        self.origin = key
        self.hash = hash(key)
        self.reset = False
        self.early = early

    def __new__(cls, key: str, early: EarlyObject[object]) -> Self:  # noqa: ARG003
        return super().__new__(cls, key)

    def __eq__(self, other: object) -> bool:
        if self.origin != other:
            return False

        if self.reset:
            self.reset = False
            return True

        caller_locals = get_frame(1).f_locals

        if caller_locals.get("__injection_recursive_guard__"):
            return True

        with self.early.__mutex__:
            __injection_recursive_guard__ = True  # noqa: F841
            self.early.__inject__(self)

        return True

    def __hash__(self) -> int:
        return self.hash


def default_recursion_guard(early: EarlyObject[object]) -> None:
    pass


@dataclass
class Injection(Generic[Object_co]):
    factory: Callable[[Locals], Object_co]
    once: bool = False
    dynamic: bool = False
    recursion_guard: Callable[[EarlyObject[Any]], object] = default_recursion_guard
    debug_info: str | None = None

    def __post_init__(self) -> None:
        if self.debug_info is None:
            factory, once, dynamic = (
                self.factory,
                self.once,
                self.dynamic,
            )
            init_opts = f"{factory=!r}, {once=!r}, {dynamic=!r}"
            include = ""
            if debug_info := self.debug_info:
                include = f", {debug_info}"
            self.debug_info = f"<injection {init_opts}{include}>"

    def assign_to(self, *aliases: str, scope: Locals) -> None:
        if not aliases:
            msg = f"expected at least one alias in Injection.assign_to() ({self!r})"
            raise ValueError(msg)

        dynamic = self.dynamic

        state = ObjectState(
            once=self.once,
            scope=scope,
            factory=self.factory,
            recursion_guard=self.recursion_guard,
            debug_info=self.debug_info,
        )
        for alias in aliases:
            debug_info = f"{alias!r} from {self.debug_info}"
            early = EarlyObject(
                alias=alias,
                state=state,
                dynamic=dynamic,
                debug_info=debug_info,
            )
            key = InjectionKey(alias, early)
            scope[key] = early


SENTINEL = object()


class ObjectState(Generic[Object_co]):
    def __init__(
        self,
        *,
        once: bool,
        scope: Locals,
        factory: Callable[[Locals], Object_co],
        recursion_guard: Callable[[EarlyObject[Any]], object],
        debug_info: str | None = None,
    ) -> None:
        self.object = SENTINEL
        self.once = once
        self.factory = factory
        self.scope = scope
        self.debug_info = debug_info
        self.recursion_guard = recursion_guard
        self.running: set[tuple[int, int]] = set()

    def __repr__(self) -> str:
        include = ""
        if debug_info := self.debug_info:
            include = f" ({debug_info})"
        return f"<ObjectState{include}>"

    def create(self, scope: Locals, early: EarlyObject[Object_co]) -> None:
        if self.object is SENTINEL or not self.once:
            recursion_key = (id(early), get_ident())
            if recursion_key in self.running:
                self.recursion_guard(early)
            else:
                try:
                    self.running.add(recursion_key)
                    self.object = self.factory(scope)
                finally:
                    self.running.remove(recursion_key)


class EarlyObject(Generic[Object_co]):
    def __init__(
        self,
        *,
        alias: str,
        state: ObjectState[Object_co],
        dynamic: bool,
        debug_info: str | None = None,
    ) -> None:
        self.__mutex__ = RLock()
        self.__dynamic = dynamic
        self.__alias = alias
        self.__state = state
        self.__debug_info = debug_info

    @property
    def __alias__(self) -> str:
        return self.__alias

    def __inject__(self, key: InjectionKey) -> None:
        scope = self.__state.scope

        __injection_recursive_guard__ = True  # noqa: F841

        # To ever know if we're in a child scope, try:
        # >>> req_scope = get_frame(1).f_locals
        # >>> in_child_scope = next(filter(self.__alias.__eq__, req_scope), True)

        self.__state.create(scope, self)
        obj, alias = self.__state.object, self.__alias

        with self.__mutex__:
            with suppress(KeyError):
                del scope[alias]

            if obj is SENTINEL:
                return

            scope[alias] = obj

            if self.__dynamic and not self.__state.once:
                del scope[key]
                key.reset = True
                scope[key] = obj

    def __repr__(self) -> str:
        include = ""
        if debug_info := self.__debug_info:
            include = f" ({debug_info})"
        return f"<EarlyObject{include}>"


def _static_factory(factory: Callable[[], Object_co], _scope: Locals) -> Object_co:
    return factory()


if TYPE_CHECKING:

    @overload
    def injection(
        *aliases: str,
        into: Locals | None = ...,
        factory: Callable[[], Object_co],
        pass_scope: Literal[False] = False,
        once: bool = ...,
        dynamic: bool = ...,
        recursion_guard: Callable[[EarlyObject[Any]], object] = ...,
        debug_info: str | None = None,
    ) -> Injection[Object_co]: ...

    @overload
    def injection(
        *aliases: str,
        into: Locals | None = ...,
        factory: Callable[[Locals], Object_co],
        pass_scope: Literal[True],
        once: bool = ...,
        dynamic: bool = ...,
        recursion_guard: Callable[[EarlyObject[Any]], object] = ...,
        debug_info: str | None = None,
    ) -> Injection[Object_co]: ...


def injection(  # noqa: PLR0913
    *aliases: str,
    into: Locals | None = None,
    factory: Callable[[], Object_co] | Callable[[Locals], Object_co],
    pass_scope: bool = False,
    once: bool = False,
    dynamic: bool = False,
    recursion_guard: Callable[[EarlyObject[Any]], object] = default_recursion_guard,
    debug_info: str | None = None,
) -> Injection[Object_co]:
    """
    Create an injection.

    Parameters
    ----------
    *aliases
        Aliases to the injection. They generally should be valid Python identifiers,
        but in special cases don't have to.
    into
        The local scope to inject into.
    factory
        A callable that creates the injected object.
    pass_scope
        Whether the factory should be passed an argument (i.e. the target scope).
    once
        Whether to only create the object once and reuse it everywhere.
    dynamic
        Whether to still trigger recreating the object in the same scope
        after successful creation. Useful as a replacement for `ContextVar` proxies.
    recursion_guard
        The function to call on recursion error. It does _not_ create a value.
        It has to take accept one argument, i.e. the early object.
    debug_info
        Debug information for more informative representations.

    """
    if not pass_scope:
        factory = partial(_static_factory, factory)  # type: ignore[arg-type]
    inj = Injection(
        factory=cast("Callable[[Locals], Object_co]", factory),
        dynamic=dynamic,
        once=once,
        recursion_guard=recursion_guard,
        debug_info=debug_info,
    )
    if into is not None and aliases:
        inj.assign_to(*aliases, scope=into)
    return inj
