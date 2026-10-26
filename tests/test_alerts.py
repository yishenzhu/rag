"""Prometheus alert rule tests."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "observability" / "alerts.yml"
METRICS = ROOT / "infrastructure" / "observability" / "metrics.py"


def known_metrics() -> set[str]:
    source = METRICS.read_text()
    names = set(re.findall(r'(?:Counter|Gauge|Histogram)\(\s*"([a-z0-9_]+)"', source))
    return names | {"up"}


def test_alert_rules_are_well_formed():
    doc = yaml.safe_load(RULES.read_text())
    known = known_metrics()
    alerts = set()
    for group in doc["groups"]:
        for rule in group["rules"]:
            assert rule["alert"] not in alerts
            alerts.add(rule["alert"])
            assert rule["for"]
            assert rule["labels"]["severity"] in {"critical", "warning", "info"}
            assert rule["annotations"]["summary"]
            assert any(name in rule["expr"] for name in known), rule["alert"]
    assert {"RagApiDown", "RagOutboxStale"} <= alerts
