"""Heure de Paris et créneaux horaires (module léger, sans dépendance lourde)."""
from __future__ import annotations

from datetime import datetime, timezone

from .config import fuseau


def heure_paris(d: datetime | None = None) -> datetime:
    return (d or datetime.now(timezone.utc)).astimezone(fuseau())


def _hhmm(s: str) -> tuple[int, int]:
    h, m = str(s).split(":")
    return int(h), int(m)
