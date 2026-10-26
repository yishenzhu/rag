"""Kubernetes manifest tests."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "deploy" / "k8s" / "app.yaml"


def load_docs():
    return [doc for doc in yaml.safe_load_all(MANIFESTS.read_text()) if doc]


def test_manifests_have_unique_identifiers():
    docs = load_docs()
    keys = {(doc["kind"], doc["metadata"]["name"]) for doc in docs}
    assert len(keys) == len(docs)
    assert ("Namespace", "rag") in keys
    assert ("Deployment", "rag-api") in keys
    assert ("Deployment", "rag-worker") in keys
    assert ("Job", "rag-migrate") in keys


def test_api_deployment_has_probes_and_limits():
    api = next(
        doc
        for doc in load_docs()
        if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "rag-api"
    )
    container = api["spec"]["template"]["spec"]["containers"][0]
    assert container["readinessProbe"]
    assert container["livenessProbe"]
    assert container["resources"]["limits"]
    assert len(container["envFrom"]) == 2
