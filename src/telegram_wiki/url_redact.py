from __future__ import annotations

import re


def redact_database_url(url: str) -> str:
    """Mask password in typical SQLAlchemy / JDBC-style URLs for safe HTML display."""
    if not url:
        return url
    # user:password@host — redact password only (keep username for debugging).
    return re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^:/@]+):([^@]+)(@)", r"\1:***\3", url, count=1)
