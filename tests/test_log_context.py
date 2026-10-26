"""Trace-aware logging tests."""

import logging

from opentelemetry.sdk.trace import TracerProvider
from rag.core.logger import TraceContextFilter


def make_record() -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, "msg", None, None)


def test_trace_id_is_dash_without_span():
    record = make_record()
    assert TraceContextFilter().filter(record)
    assert record.trace_id == "-"


def test_trace_id_matches_current_span():
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("work") as span:
        record = make_record()
        TraceContextFilter().filter(record)
        assert record.trace_id == format(span.get_span_context().trace_id, "032x")
