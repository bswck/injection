from __future__ import annotations

import threading
from collections import Counter
from itertools import product
from operator import methodcaller

import pytest

from injection import Injection, inject, lenient_recursion_guard


def test_injection_basic() -> None:
    """Test basic injection functionality."""
    scope: dict[str, str] = {}
    factory_called = False

    def factory() -> str:
        nonlocal factory_called
        factory_called = True
        return "injected_object"

    inject("my_alias", into=scope, factory=factory)

    assert not factory_called
    obj = scope["my_alias"]
    assert factory_called

    assert obj == "injected_object"
    assert "my_alias" in scope
    assert scope["my_alias"] == "injected_object"


def test_injection_with_pass_scope() -> None:
    """Test injection when the factory requires the scope."""
    scope: dict[str, str] = {}
    factory_called = False

    def factory(scope: dict[str, str]) -> str:
        nonlocal factory_called
        factory_called = True
        return f"injected_object_with_scope_{len(scope)}"

    inject("my_alias", into=scope, factory=factory, pass_scope=True)

    assert not factory_called
    obj: str = scope["my_alias"]

    assert factory_called
    assert obj == f"injected_object_with_scope_{len(scope)}"


def test_injection_multiple_aliases() -> None:
    """Test injection with multiple aliases."""
    scope: dict[str, str] = {}
    factory_called = False

    def factory() -> str:
        nonlocal factory_called
        factory_called = True
        return "injected_object"

    inj = Injection(actual_factory=factory)
    inj.assign_to("alias1", "alias2", scope=scope)

    obj1 = scope["alias1"]

    assert factory_called
    assert obj1 == "injected_object"

    obj2 = scope["alias2"]

    assert obj1 == obj2


def test_injection_different_scopes() -> None:
    """Test that injection works correctly in different scopes."""
    call_count: int = 0

    def factory() -> str:
        nonlocal call_count
        call_count += 1
        return f"injected_object_{call_count}"

    inj = Injection(actual_factory=factory, cache=False, cache_per_alias=False)

    scope1: dict[str, str] = {}
    scope2: dict[str, str] = {}

    # Assign the injection into scope1 and scope2
    inj.assign_to("my_alias", scope=scope1)
    inj.assign_to("my_alias", scope=scope2)

    obj1 = scope1["my_alias"]
    assert call_count == 1
    assert obj1 == "injected_object_1"

    obj2 = scope2["my_alias"]
    assert call_count == 2  # noqa: PLR2004
    assert obj2 == "injected_object_2"

    assert obj1 != obj2


def test_injection_thread_safety() -> None:
    """Test that injection is thread-safe with 'cache=True'."""
    scope: dict[str, str] = {}

    call_counts: Counter[int] = Counter()

    def factory() -> str:
        call_counts.update([threading.get_ident()])
        return "injected_object"

    num_threads: int = 3
    barrier = threading.Barrier(num_threads)

    inject("my_alias", into=scope, factory=factory, cache=True)

    def access() -> None:
        barrier.wait()
        obj = scope["my_alias"]
        assert obj == "injected_object"

    threads: list[threading.Thread] = [
        threading.Thread(target=access) for _ in range(num_threads)
    ]

    for cb, thread in product(map(methodcaller, ("start", "join")), threads):
        cb(thread)

    assert sum(call_counts.values()) == 1


def test_injection_with_multiple_threads_and_once_false() -> None:
    """Test thread safety when 'once' is False."""
    scope: dict[str, str] = {}

    call_counts: Counter[int] = Counter()

    def factory() -> str:
        thread_id = threading.get_ident()
        call_counts.update([thread_id])
        return f"injected_object_{call_counts[thread_id]}"

    num_threads = 3
    barrier = threading.Barrier(num_threads)

    inject("my_alias", into=scope, factory=factory, cache=False)

    def access() -> None:
        barrier.wait()
        obj = scope["my_alias"]
        assert obj == "injected_object_1"

    threads: list[threading.Thread] = [
        threading.Thread(target=access) for _ in range(num_threads)
    ]

    for cb, thread in product(map(methodcaller, ("start", "join")), threads):
        cb(thread)

    assert set(call_counts.values()) == {1}


def test_injection_without_assigning() -> None:
    """Test injection when not assigned into a scope."""
    call_count = 0

    def factory() -> str:
        nonlocal call_count
        call_count += 1
        return f"injected_object_{call_count}"

    inj = Injection(actual_factory=factory)

    scope: dict[str, str] = {}

    with pytest.raises(KeyError):
        scope["my_alias"]

    inj.assign_to("my_alias", scope=scope)

    obj = scope["my_alias"]
    assert call_count == 1
    assert obj == "injected_object_1"


def test_injection_factory_exception() -> None:
    """Test that exceptions in the factory are propagated."""
    scope: dict[str, str] = {}

    def factory() -> str:
        msg = "factory error"
        raise ValueError(msg)

    inject("my_alias", into=scope, factory=factory)

    with pytest.raises(ValueError, match="factory error"):
        scope["my_alias"]


def test_injection_recursive_guard() -> None:
    """Test that recursive injection does not cause infinite recursion."""
    scope: dict[str, str] = {}

    def factory() -> str:
        return scope.get("my_alias", "default_value")

    inject(
        "my_alias",
        into=scope,
        factory=factory,
        recursion_guard=lenient_recursion_guard,
    )

    obj = scope["my_alias"]
    assert obj == "default_value"

    inject("my_alias", into=scope, factory=factory)  # strict

    with pytest.raises(RecursionError, match="requested itself"):
        obj = scope["my_alias"]


def test_injection_with_no_aliases() -> None:
    """Test that injection with no aliases raises an error."""
    scope: dict[str, str] = {}

    def factory() -> str:
        return "injected_object"

    inj = Injection(actual_factory=factory)
    with pytest.raises(ValueError, match="expected at least one alias"):
        inj.assign_to(scope=scope)
