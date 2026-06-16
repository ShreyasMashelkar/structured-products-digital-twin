"""In-process event bus — the "queue" interface.

A thin pub/sub class. The interface is message-shaped, so this could be swapped for
Kafka / Redis Streams without touching business logic. See ADR (docs/adr/) and the
design doc §3.4.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Handler = Callable[["Message"], None]


@dataclass(frozen=True)
class Message:
    """An immutable event flowing across layer boundaries."""

    topic: str
    payload: Any


class EventBus:
    """Synchronous in-process publish/subscribe bus.

    Deliberately minimal: the value is the *boundary*, not the transport. Handlers are
    invoked synchronously in subscription order.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subscribers[topic].append(handler)

    def publish(self, message: Message) -> None:
        for handler in self._subscribers.get(message.topic, []):
            handler(message)
