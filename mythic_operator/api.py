from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from mythic import mythic

from mythic_operator.config import MythicConfig


def _parse_url(url: str) -> tuple[str, int]:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 7443
    return host, port


async def login(config: MythicConfig):
    host, port = _parse_url(config.url)
    return await mythic.login(
        username=config.username,
        password=config.password,
        server_ip=host,
        server_port=port,
        timeout=-1,
    )


async def list_beacons(session):
    if hasattr(mythic, "get_all_callbacks"):
        return await mythic.get_all_callbacks(mythic=session)
    if hasattr(mythic, "get_callbacks"):
        return await mythic.get_callbacks(mythic=session)
    raise RuntimeError("Installed mythic library does not expose callback listing methods")


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def is_active(beacon, seconds: int = 60) -> bool:
    now = datetime.now(timezone.utc)
    last_checkin = _extract(beacon, "last_checkin", "last_checkin_time", "last_seen", "timestamp")
    seen_at = _to_datetime(last_checkin)
    if seen_at is None:
        return True
    return (now - seen_at).total_seconds() <= seconds


def _extract(beacon, *keys, default: str = ""):
    if isinstance(beacon, dict):
        for key in keys:
            if key in beacon and beacon[key] not in (None, ""):
                return beacon[key]
        return default
    for key in keys:
        value = getattr(beacon, key, None)
        if value not in (None, ""):
            return value
    return default


def beacon_to_row(beacon) -> dict[str, str]:
    return {
        "id": str(_extract(beacon, "id", "agent_callback_id", "callback_id")),
        "name": str(_extract(beacon, "display_id", "description", "payload_type", "name")),
        "host": str(_extract(beacon, "host", "host_name", "hostname")),
        "user": str(_extract(beacon, "user", "username")),
        "os": str(_extract(beacon, "os", "os_type")),
        "pid": str(_extract(beacon, "pid", "process_id")),
        "last_seen": str(_extract(beacon, "last_checkin", "last_seen", "timestamp")),
        "ip": str(_extract(beacon, "ip", "ip_address", "external_ip")),
    }
