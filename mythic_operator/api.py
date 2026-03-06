from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import inspect
import time
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


def _ensure_beacon_list(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("callbacks", "results", "response"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


async def find_beacon(session, selector: str):
    beacons = _ensure_beacon_list(await list_beacons(session))
    for beacon in beacons:
        row = beacon_to_row(beacon)
        if selector in {row["id"], row["name"]}:
            return beacon
    selector_lower = selector.lower()
    for beacon in beacons:
        row = beacon_to_row(beacon)
        if selector_lower in row["name"].lower():
            return beacon
    raise ValueError(f"Beacon '{selector}' was not found")


def extract_task_id(task_response) -> str:
    task_id = _extract(task_response, "id", "task_id", "display_id", "task_display_id", default="")
    if not task_id:
        raise RuntimeError("Task submission succeeded but no task id was returned")
    return str(task_id)


async def _invoke_with_supported_kwargs(func, kwargs: dict):
    signature = inspect.signature(func)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()):
        return await func(**kwargs)
    supported = {k: v for k, v in kwargs.items() if k in signature.parameters}
    return await func(**supported)


async def create_task(
    session,
    beacon_id: str,
    command_name: str,
    params: str,
    callback_display_id: str | None = None,
    callback_numeric_id: int | None = None,
    wait_for_complete: bool = False,
):
    attempts = ("create_callback_task", "create_task", "issue_task", "task_create")
    value_map = {
        "mythic": session,
        "callback_id": callback_numeric_id if callback_numeric_id is not None else beacon_id,
        "callback_display_id": (
            callback_numeric_id
            if callback_numeric_id is not None
            else (callback_display_id or beacon_id)
        ),
        "command": command_name,
        "command_name": command_name,
        "params": params,
        "parameters": params,
        "parameter": params,
        "wait_for_complete": wait_for_complete,
    }
    signature_errors = []
    for function_name in attempts:
        func = getattr(mythic, function_name, None)
        if func is None:
            continue
        signature = inspect.signature(func)
        kwargs = {}
        for param_name in signature.parameters:
            if param_name in value_map:
                kwargs[param_name] = value_map[param_name]
        try:
            return await func(**kwargs)
        except TypeError as exc:
            signature_errors.append(f"{function_name}: {exc}")
            continue
    details = "; ".join(signature_errors) if signature_errors else "no compatible task API found"
    raise RuntimeError(f"Unable to submit task '{command_name}' ({details})")


def _extract_output_text(payload) -> str:
    chunks = []
    entries = payload if isinstance(payload, list) else _ensure_beacon_list(payload)
    for entry in entries:
        text = _extract(entry, "response", "output", "stdout", "user_output", "message", default="")
        if text:
            chunks.append(str(text))
    return "\n".join(chunks).strip()


async def poll_task_output(session, task_id: str, timeout: int = 180, poll_interval: int = 2) -> str:
    response_calls = (
        ("get_task_responses", {"mythic": session, "task_id": task_id}),
        ("get_responses", {"mythic": session, "task_id": task_id}),
        ("get_all_responses_for_task", {"mythic": session, "task_id": task_id}),
    )
    started = time.time()
    while time.time() - started < timeout:
        for function_name, kwargs in response_calls:
            func = getattr(mythic, function_name, None)
            if func is None:
                continue
            try:
                payload = await _invoke_with_supported_kwargs(func, kwargs)
            except TypeError:
                continue
            output = _extract_output_text(payload)
            if output:
                return output
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"Timed out waiting for task output (task_id={task_id})")


async def list_mythic_files(session) -> list[dict]:
    """Return all non-agent-download files registered in Mythic."""
    from mythic import mythic_utilities
    query = """
    query ListMythicFiles {
        filemeta(where: {is_download_from_agent: {_eq: false}, is_screenshot: {_eq: false}},
                 order_by: {id: desc}) {
            agent_file_id
            filename_utf8
            complete
            md5
            size
        }
    }
    """
    try:
        result = await mythic_utilities.graphql_post(mythic=session, query=query)
        return result.get("filemeta", [])
    except Exception:
        return []


async def find_mythic_file(session, filename: str) -> str | None:
    """Return the agent_file_id UUID of an already-registered file by name, or None."""
    from mythic import mythic_utilities
    query = f"""
    query FindMythicFile {{
        filemeta(where: {{filename_utf8: {{_eq: "{filename}"}}, complete: {{_eq: true}}, is_download_from_agent: {{_eq: false}}}}, limit: 1, order_by: {{id: desc}}) {{
            agent_file_id
        }}
    }}
    """
    try:
        result = await mythic_utilities.graphql_post(mythic=session, query=query)
        entries = result.get("filemeta", [])
        if entries:
            return entries[0]["agent_file_id"]
    except Exception:
        pass
    # Fallback: use library methods if available
    for func_name in ("get_all_files", "get_files", "get_file_list"):
        func = getattr(mythic, func_name, None)
        if func is None:
            continue
        try:
            result = await _invoke_with_supported_kwargs(func, {"mythic": session})
        except Exception:
            continue
        entries = result if isinstance(result, list) else _ensure_beacon_list(result)
        for entry in entries:
            name = _extract(entry, "filename_utf8", "filename", "file_name", "name")
            if str(name).lower() == filename.lower():
                file_id = _extract(entry, "agent_file_id", "file_id", "id", "uuid")
                return str(file_id) if file_id else None
    return None


async def upload_file_to_mythic(session, local_path, filename_override: str | None = None) -> str:
    """Upload a local file to Mythic and return its agent_file_id UUID."""
    from pathlib import Path as _Path
    path = _Path(local_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found at {path}")
    contents = path.read_bytes()
    upload_name = filename_override or path.name
    func = getattr(mythic, "register_file", None)
    if func is None:
        raise RuntimeError("mythic.register_file is not available in this library version")
    result = await func(mythic=session, filename=upload_name, contents=contents)
    if isinstance(result, (str, bytes)):
        return str(result).strip()
    file_id = _extract(result, "agent_file_id", "file_id", "id", "uuid")
    if not file_id:
        raise RuntimeError(f"register_file succeeded but returned no file_id: {result!r}")
    return str(file_id)


async def issue_task_and_wait_output(
    session,
    callback_display_id: int,
    command_name: str,
    parameters: str,
    timeout: int = 240,
) -> str:
    func = getattr(mythic, "issue_task_and_waitfor_task_output", None)
    if func is None:
        raise RuntimeError("issue_task_and_waitfor_task_output is unavailable in this mythic library")
    result = await func(
        mythic=session,
        command_name=command_name,
        parameters=parameters,
        callback_display_id=callback_display_id,
        timeout=timeout,
    )
    if isinstance(result, bytes):
        return result.decode("utf-8", errors="replace").strip()
    return str(result).strip()
