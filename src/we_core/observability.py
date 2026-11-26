"""Observabilidade: logs JSON estruturados com redação, métricas Prometheus e traces OpenTelemetry."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from types import SimpleNamespace
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

correlation_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
tenant_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)

_REDACT_PATTERNS = [
    (re.compile(r"(?i)(authorization|password|passwd|secret|token|api[_-]?key)(\"?\s*[:=]\s*\"?)[^\s\",]+"),
     r"\1\2[REDACTED]"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"), "[JWT]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    (re.compile(r"\bPT50\d{21}\b"), "[IBAN]"),
    (re.compile(r"postgres(?:ql)?://[^\s]+"), "postgresql://[REDACTED]"),
]  # fmt: skip


def redact(text: str) -> str:
    for rx, rep in _REDACT_PATTERNS:
        text = rx.sub(rep, text)
    return text


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "msg": redact(record.getMessage()),
            "correlation_id": correlation_var.get(),
            "tenant_id": tenant_var.get(),
        }
        try:
            from opentelemetry import trace

            span = trace.get_current_span().get_span_context()
            if span.is_valid:
                out["trace_id"] = format(span.trace_id, "032x")
        except Exception:  # noqa: BLE001,S110 - telemetria nunca derruba o logging
            pass
        if record.exc_info:
            out["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(out, ensure_ascii=False)


def setup_logging(service: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("botocore", "urllib3", "psycopg.pool"):
        logging.getLogger(noisy).setLevel("WARNING")


def setup_tracing(service: str, endpoint: str | None) -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider(resource=Resource.create({"service.name": service, "service.namespace": "we"}))
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")))
    trace.set_tracer_provider(provider)


metrics = SimpleNamespace(
    http_requests=Counter("we_http_requests_total", "Pedidos HTTP", ["method", "route", "status"]),
    http_latency=Histogram("we_http_request_seconds", "Latência HTTP", ["method", "route"]),
    events_appended=Counter("we_events_appended_total", "Eventos gravados no Event Store"),
    policy_denials=Counter("we_policy_denials_total", "Negações de autorização/política", ["code"]),
    evidence_uploads=Counter("we_evidence_uploads_total", "Evidências recebidas"),
    integrity_failures=Counter("we_integrity_failures_total", "Falhas de integridade detetadas", ["kind"]),
    outbox_published=Counter("we_outbox_published_total", "Mensagens publicadas a partir da outbox"),
    outbox_retries=Counter("we_outbox_retries_total", "Tentativas falhadas de publicação"),
    outbox_dead=Counter("we_outbox_dead_total", "Mensagens movidas para DLQ"),
    outbox_pending=Gauge("we_outbox_pending", "Mensagens pendentes na outbox"),
    outbox_lag_seconds=Gauge("we_outbox_lag_seconds", "Idade da mensagem pendente mais antiga"),
    outbox_dlq=Gauge("we_outbox_dlq", "Mensagens em DLQ"),
    consumer_processed=Counter(
        "we_consumer_processed_total", "Eventos aplicados a projeções", ["projection"]
    ),
    consumer_duplicates=Counter(
        "we_consumer_duplicates_total", "Eventos duplicados ignorados", ["projection"]
    ),
    decisions_pending=Gauge(
        "we_decisions_pending", "Decisões a aguardar aprovação humana (todos os tenants)"
    ),
)
