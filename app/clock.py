"""Single source of 'now'. Tests and the simulator can move time forward."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import settings

TZ = ZoneInfo(settings.timezone)
_offset = timedelta(0)


def now() -> datetime:
    """Current local time (naive, in the app timezone). Stored in DB as naive local time."""
    return (datetime.now(TZ) + _offset).replace(tzinfo=None)


def advance(**kwargs) -> None:
    global _offset
    _offset += timedelta(**kwargs)


def reset() -> None:
    global _offset
    _offset = timedelta(0)


def set_to(dt: datetime) -> None:
    global _offset
    _offset = dt - datetime.now(TZ).replace(tzinfo=None)
