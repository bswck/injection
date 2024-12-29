from __future__ import annotations

from contextlib import suppress
from contextvars import ContextVar, copy_context
from dataclasses import dataclass
from threading import Lock, RLock, get_ident
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    Literal,
    TypeVar,
    cast,
    overload,
)
from weakref import WeakSet

from injection.compat import get_frame

if TYPE_CHECKING:
    from collections.abc import Callable

    from typing_extensions import Never, Self, TypeAlias

    Locals: TypeAlias = "dict[str, Any]"


__all__ = (
    "EarlyObject",
    "Injection",
    "InjectionKey",
    "ObjectState",
    "inject",
    "lenient_recursion_guard",
    "strict_recursion_guard",
)


Object_co = TypeVar("Object_co", covariant=True)

PEEK_MUTEX = RLock()
peeking_var: ContextVar[bool] = ContextVar("peeking", default=False)
peeked_early_var: ContextVar[EarlyObject[Any]] = ContextVar("peeked_early")


class InjectionKey(str):
    __slots__ = ("early", "hash", "origin", "reset")

    def __init__(self, alias: str, early: EarlyObject[object]) -> None:
        self.origin = alias
        self.hash = hash(alias)
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

        try:
            caller_locals = get_frame(1).f_locals
        except ValueError:
            # can happen if we patch sys
            return True

        if caller_locals.get("__injection_recursive_guard__"):
            return True

        if peeking_var.get():
            peeked_early_var.set(self.early)
            return True

        with self.early.__mutex__:
            __injection_recursive_guard__ = True  # noqa: F841
            self.early.__inject__()

        return True

    def __hash__(self) -> int:
        return self.hash


def lenient_recursion_guard(early: EarlyObject[object]) -> None:
    pass


def strict_recursion_guard(early: EarlyObject[object]) -> Never:
    msg = f"{early} requested itself"
    raise RecursionError(msg)


@dataclass(frozen=True)
class InjectionFactoryWrapper(Generic[Object_co]):
    actual_factory: Any
    pass_scope: bool

    def __call__(self, scope: Locals) -> Object_co:
        if self.pass_scope:
            return cast("Object_co", self.actual_factory(scope))
        return cast("Object_co", self.actual_factory())


@dataclass
class Injection(Generic[Object_co]):
    actual_factory: Callable[..., Object_co]
    pass_scope: bool = False
    cache: bool = False
    cache_per_alias: bool = False
    recursion_guard: Callable[[EarlyObject[Any]], object] = lenient_recursion_guard
    debug_info: str | None = None

    _reassignment_lock: ClassVar[Lock] = Lock()

    @property
    def factory(self) -> InjectionFactoryWrapper[Object_co]:
        return InjectionFactoryWrapper(
            actual_factory=self.actual_factory,
            pass_scope=self.pass_scope,
        )

    def __post_init__(self) -> None:
        if self.debug_info is None:
            actual_factory, cache, cache_per_alias = (
                self.actual_factory,
                self.cache,
                self.cache_per_alias,
            )
            init_opts = f"{actual_factory=!r}, {cache=!r}, {cache_per_alias=!r}"
            include = ""
            if debug_info := self.debug_info:
                include = f", {debug_info}"
            self.debug_info = f"<injection {init_opts}{include}>"

    def assign_to(
        self,
        *aliases: str,
        scope: Locals,
    ) -> WeakSet[EarlyObject[Object_co]]:
        if not aliases:
            msg = f"expected at least one alias in Injection.assign_to() ({self!r})"
            raise ValueError(msg)

        state: ObjectState[Object_co] = ObjectState(
            cache=self.cache,
            factory=self.factory,
            recursion_guard=self.recursion_guard,
            debug_info=self.debug_info,
            scope=scope,
        )

        cache_per_alias = self.cache_per_alias

        early_objects: WeakSet[EarlyObject[Object_co]] = WeakSet()

        for alias in aliases:
            debug_info = f"{alias!r} from {self.debug_info}"
            early_object = EarlyObject(
                alias=alias,
                state=state,
                cache_per_alias=cache_per_alias,
                debug_info=debug_info,
            )
            early_objects.add(early_object)
            key = early_object.__key__

            with self._reassignment_lock:
                scope.pop(key, None)
                scope[key] = early_object

        return early_objects


SENTINEL = object()


class ObjectState(Generic[Object_co]):
    def __init__(
        self,
        *,
        cache: bool,
        scope: Locals,
        factory: Callable[[Locals], Object_co],
        recursion_guard: Callable[[EarlyObject[Any]], object],
        debug_info: str | None = None,
    ) -> None:
        self.object = SENTINEL
        self.cache = cache
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

    def create(self, early: EarlyObject[Object_co]) -> None:
        if self.object is SENTINEL or not self.cache:
            recursion_key = (id(early), get_ident())
            if recursion_key in self.running:
                self.recursion_guard(early)
            else:
                try:
                    self.running.add(recursion_key)
                    self.object = self.factory(self.scope)
                finally:
                    self.running.remove(recursion_key)


class EarlyObject(Generic[Object_co]):
    def __init__(
        self,
        *,
        alias: str,
        state: ObjectState[Object_co],
        cache_per_alias: bool,
        debug_info: str | None = None,
    ) -> None:
        self.__alias__ = alias
        self.__mutex__ = RLock()
        self.__cache_per_alias = cache_per_alias
        self.__state__ = state
        self.__debug_info = debug_info
        self.__key__ = InjectionKey(alias, self)

    def __inject__(self) -> None:
        # To ever know if we're in a child scope, try:
        # >>> req_scope = get_frame(1).f_locals
        # >>> in_child_scope = next(filter(self.__alias.__eq__, req_scope), True)

        __injection_recursive_guard__ = True  # noqa: F841
        key, alias, scope = (self.__key__, self.__alias__, self.__state__.scope)

        self.__state__.create(self)
        obj = self.__state__.object

        with self.__mutex__:
            with suppress(KeyError):
                del scope[alias]

            if obj is SENTINEL:
                return

            scope[alias] = obj

            if not self.__cache_per_alias:
                del scope[key]
                key.reset = True
                scope[key] = obj

    def __repr__(self) -> str:
        hint = "before __inject__()"
        include = f" ({hint})"
        if debug_info := self.__debug_info:
            include = f" ({debug_info} {hint})"
        return f"<EarlyObject{include}>"


if TYPE_CHECKING:

    @overload
    def inject(
        *aliases: str,
        into: Locals | None = ...,
        factory: Callable[[], Object_co],
        pass_scope: Literal[False] = False,
        cache: bool = ...,
        cache_per_alias: bool = ...,
        recursion_guard: Callable[[EarlyObject[Any]], object] = ...,
        debug_info: str | None = None,
    ) -> None: ...

    @overload
    def inject(
        *aliases: str,
        into: Locals | None = ...,
        factory: Callable[[Locals], Object_co],
        pass_scope: Literal[True],
        cache: bool = ...,
        cache_per_alias: bool = ...,
        recursion_guard: Callable[[EarlyObject[Any]], object] = ...,
        debug_info: str | None = None,
    ) -> None: ...


def inject(  # noqa: PLR0913
    *aliases: str,
    into: Locals | None = None,
    factory: Callable[[], Object_co] | Callable[[Locals], Object_co],
    pass_scope: bool = False,
    cache: bool = False,
    cache_per_alias: bool = False,
    recursion_guard: Callable[[EarlyObject[Any]], object] = strict_recursion_guard,
    debug_info: str | None = None,
) -> None:
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
    cache
        Whether to only create the object once and reuse it everywhere.
    cache_per_alias
        Whether to still trigger recreating the object under the same alias
        after successful creation. Useful as a replacement for `ContextVar` proxies.
        Once globally overwrites this.
    recursion_guard
        The function to call on recursion error. It does _not_ create a value.
        It has to take accept one argument, i.e. the early object.
    debug_info
        Debug information for more informative representations.

    """
    inj = Injection(
        actual_factory=factory,
        pass_scope=pass_scope,
        cache_per_alias=cache_per_alias,
        cache=cache,
        recursion_guard=recursion_guard,
        debug_info=debug_info,
    )
    if into is not None and aliases:
        inj.assign_to(*aliases, scope=into)


def peek(scope: Locals, alias: str) -> EarlyObject[Any] | None:
    """Safely get early object from a scope without triggering injection behavior."""
    peeking_context = copy_context()
    peeking_context.run(peeking_var.set, True)  # noqa: FBT003
    with suppress(KeyError):
        peeking_context.run(scope.__getitem__, alias)
    return peeking_context.get(peeked_early_var)


def peek_or_inject(  # noqa: PLR0913
    scope: Locals,
    alias: str,
    *,
    metafactory: Callable[[], Callable[[], Object_co] | Callable[[Locals], Object_co]],
    pass_scope: bool = False,
    cache: bool = False,
    cache_per_alias: bool = False,
    recursion_guard: Callable[[EarlyObject[Any]], object] = strict_recursion_guard,
    debug_info: str | None = None,
) -> EarlyObject[Object_co]:
    """
    Peek or inject as necessary in a thread-safe manner.

    If an injection is present, return the existing early object.
    If it is not present, create a new injection, inject it and return an early object.

    This function works only for one alias at a time.
    """
    with PEEK_MUTEX:
        metadata = peek(scope, alias)
        if metadata is None:
            metadata = next(
                iter(
                    Injection(
                        actual_factory=metafactory(),
                        pass_scope=pass_scope,
                        cache=cache,
                        cache_per_alias=cache_per_alias,
                        recursion_guard=recursion_guard,
                        debug_info=debug_info,
                    ).assign_to(alias, scope=scope)
                )
            )
        return metadata
