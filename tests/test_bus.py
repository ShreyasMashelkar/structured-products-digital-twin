"""Smoke test for the event bus — proves `pip install -e .` wiring works (Month 0 DoD)."""

from spdt.core.bus import EventBus, Message


def test_bus_delivers_message_to_subscriber():
    bus = EventBus()
    received: list[Message] = []
    bus.subscribe("snapshot.built", received.append)

    bus.publish(Message(topic="snapshot.built", payload={"date": "2023-06-15"}))

    assert len(received) == 1
    assert received[0].payload["date"] == "2023-06-15"


def test_bus_ignores_unsubscribed_topics():
    bus = EventBus()
    received: list[Message] = []
    bus.subscribe("snapshot.built", received.append)

    bus.publish(Message(topic="other.topic", payload=None))

    assert received == []
