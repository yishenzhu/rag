"""Tracing configuration tests."""

from rag.infrastructure.observability.tracing import traces_endpoint


def test_traces_endpoint_normalizes_base_url():
    assert traces_endpoint("http://jaeger:4318") == "http://jaeger:4318/v1/traces"
    assert traces_endpoint("http://jaeger:4318/") == "http://jaeger:4318/v1/traces"
    assert (
        traces_endpoint("http://jaeger:4318/v1/traces")
        == "http://jaeger:4318/v1/traces"
    )
