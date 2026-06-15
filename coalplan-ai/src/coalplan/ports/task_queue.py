from __future__ import annotations

from typing import Callable, Protocol, TypeVar

T = TypeVar("T")


class TaskQueue(Protocol):
    def submit(self, fn: Callable[[], T]) -> T:
        """Submit work. Prototype implementations may run synchronously."""

