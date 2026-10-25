"""Slug helpers."""

import re
from uuid import uuid4


def make_slug(name: str, fallback: str = "tenant") -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or fallback
    return f"{base[:40]}-{uuid4().hex[:8]}"
