from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Timezone-aware UTC for DB columns and business logic."""
    return datetime.now(timezone.utc)
