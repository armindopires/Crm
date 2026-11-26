"""EventBus: porta de transporte de eventos. Implementações: NATS JetStream (inicial) e memória (testes).

Entrega at-least-once. A deduplicação no broker usa Nats-Msg-Id = event_id (janela JetStream);
os consumidores são idempotentes independentemente disso.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def publish(self, subject: str, envelope: dict[str, Any], msg_id: str) -> bool: ...
    async def subscribe(self, durable: str, handler: Handler) -> None: ...
    async def healthy(self) -> bool: ...


class NatsJetStreamBus:
    def __init__(self, url: str, stream: str) -> None:
        self.url, self.stream = url, stream
        self.nc: Any = None
        self.js: Any = None
        self._subs: list[Any] = []

    async def connect(self) -> None:
        import nats
        from nats.js.api import RetentionPolicy, StorageType, StreamConfig

        self.nc = await nats.connect(
            self.url, max_reconnect_attempts=-1, reconnect_time_wait=1, name="we-core"
        )
        self.js = self.nc.jetstream()
        cfg = StreamConfig(name=self.stream, subjects=["we.>"], retention=RetentionPolicy.LIMITS,
                           storage=StorageType.FILE, duplicate_window=600, max_age=14 * 24 * 3600)  # fmt: skip
        try:
            await self.js.add_stream(cfg)
        except Exception:  # noqa: BLE001 - já existe: atualiza configuração
            await self.js.update_stream(cfg)

    async def close(self) -> None:
        if self.nc:
            await self.nc.drain()

    async def publish(self, subject: str, envelope: dict[str, Any], msg_id: str) -> bool:
        ack = await self.js.publish(subject, json.dumps(envelope).encode(), headers={"Nats-Msg-Id": msg_id},
                                    timeout=5)  # fmt: skip
        return not bool(getattr(ack, "duplicate", False))

    async def subscribe(self, durable: str, handler: Handler) -> None:
        from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy

        async def _cb(msg: Any) -> None:
            try:
                await handler(json.loads(msg.data))
                await msg.ack()
            except Exception:  # noqa: BLE001 - nak com atraso → nova entrega; DLQ após max_deliver
                await msg.nak(delay=2)

        sub = await self.js.subscribe(
            "we.>", durable=durable, cb=_cb, manual_ack=True,
            config=ConsumerConfig(ack_policy=AckPolicy.EXPLICIT, deliver_policy=DeliverPolicy.ALL,
                                  max_deliver=10, ack_wait=30),
        )  # fmt: skip
        self._subs.append(sub)

    async def healthy(self) -> bool:
        return bool(self.nc and self.nc.is_connected)


class InMemoryBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, Any]]] = []
        self._seen: set[str] = set()
        self._handlers: list[Handler] = []
        self.fail_next = 0

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def publish(self, subject: str, envelope: dict[str, Any], msg_id: str) -> bool:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ConnectionError("falha simulada do broker")
        if msg_id in self._seen:
            return False
        self._seen.add(msg_id)
        self.messages.append((subject, envelope))
        for h in self._handlers:
            await h(envelope)
        return True

    async def subscribe(self, durable: str, handler: Handler) -> None:
        self._handlers.append(handler)

    async def healthy(self) -> bool:
        return True
