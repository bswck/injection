from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from threading import Lock, RLock, get_ident
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Literal, TypeVar, overload

from injection.compat import get_frame

if TYPE_CHECKING:
    from collections.abc import Callable

    from typing_extensions import Never, Self, TypeAlias

    Locals: TypeAlias = "dict[str, Any]"


__all__ = (
    "EarlyObject",
    "InjectionKey",
    "Injection",
    "ObjectState",
    "inject",
    "lenient_recursion_guard",
    "strict_recursion_guard",
)


Object_co = TypeVar("Object_co", covariant=True)


class InjectionKey(str):
    __slots__ = ("origin", "hash", "reset", "early")

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

        caller_locals = get_frame(1).f_locals

        if caller_locals.get("__injection_recursive_guard__"):
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


@dataclass
class Injection(Generic[Object_co]):
    factory: Callable[..., Object_co]
    pass_scope: bool = False
    cache: bool = False
    cache_per_alias: bool = False
    recursion_guard: Callable[[EarlyObject[Any]], object] = lenient_recursion_guard
    debug_info: str | None = None

    _reassignment_lock: ClassVar[Lock] = Lock()

    def _call_factory(self, scope: Locals) -> Object_co:
        if self.pass_scope:
            return self.factory(scope)
        return self.factory()

    def __post_init__(self) -> None:
        if self.debug_info is None:
            factory, cache, cache_per_alias = (
                self.factory,
                self.cache,
                self.cache_per_alias,
            )
            init_opts = f"{factory=!r}, {cache=!r}, {cache_per_alias=!r}"
            include = ""
            if debug_info := self.debug_info:
                include = f", {debug_info}"
            self.debug_info = f"<injection {init_opts}{include}>"

    def assign_to(self, *aliases: str, scope: Locals) -> None:
        if not aliases:
            msg = f"expected at least one alias in Injection.assign_to() ({self!r})"
            raise ValueError(msg)

        state = ObjectState(
            cache=self.cache,
            factory=self._call_factory,
            recursion_guard=self.recursion_guard,
            debug_info=self.debug_info,
            scope=scope,
        )

        cache_per_alias = self.cache_per_alias

        for alias in aliases:
            debug_info = f"{alias!r} from {self.debug_info}"
            early = EarlyObject(
                alias=alias,
                state=state,
                cache_per_alias=cache_per_alias,
                debug_info=debug_info,
            )
            key = early.__key__

            with self._reassignment_lock:
                scope.pop(key, None)
                scope[key] = early


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
        self.__state = state
        self.__debug_info = debug_info
        self.__key__ = InjectionKey(alias, self)

    def __inject__(self) -> None:
        # To ever know if we're in a child scope, try:
        # >>> req_scope = get_frame(1).f_locals
        # >>> in_child_scope = next(filter(self.__alias.__eq__, req_scope), True)

        __injection_recursive_guard__ = True  # noqa: F841
        key, alias, scope = (self.__key__, self.__alias__, self.__state.scope)

        self.__state.create(self)
        obj = self.__state.object

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
        factory=factory,
        pass_scope=pass_scope,
        cache_per_alias=cache_per_alias,
        cache=cache,
        recursion_guard=recursion_guard,
        debug_info=debug_info,
    )
    if into is not None and aliases:
        inj.assign_to(*aliases, scope=into)
