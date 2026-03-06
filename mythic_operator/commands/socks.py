from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from mythic_operator.api import (
    beacon_to_row,
    find_beacon,
    issue_task_and_wait_output,
    create_task,
    extract_task_id,
    poll_task_output,
)

PROXY_DIR = Path.home() / "PROXY"
PROXYCHAINS_SRC = Path("/etc/proxychains.conf")
PROXY_ALIASES_FILE = Path.home() / ".proxy_aliases"

# Shell rc files to auto-inject the source line into (posix-compatible shells)
_RC_FILES = [
    Path.home() / ".bashrc",
    Path.home() / ".zshrc",
    Path.home() / ".bash_profile",
    Path.home() / ".profile",
]
_FISH_CONFIG = Path.home() / ".config" / "fish" / "config.fish"
_SOURCE_MARKER = "# proxy aliases (mythic-operator)"


def _to_int(value: str) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _build_params(port: int, stop: bool) -> str:
    if stop:
        return json.dumps({"action": "stop", "port": port})
    return json.dumps({"action": "start", "port": port})


def _setup_proxychains(beacon_name: str, port: int) -> Path:
    PROXY_DIR.mkdir(parents=True, exist_ok=True)
    dest = PROXY_DIR / f"{beacon_name}.conf"

    if PROXYCHAINS_SRC.exists():
        shutil.copy2(PROXYCHAINS_SRC, dest)
        content = dest.read_text(encoding="utf-8")
        # Remove any existing socks4/socks5 lines at the end of [ProxyList]
        content = re.sub(r"^\s*socks[45]\s+.*$", "", content, flags=re.MULTILINE)
        content = content.rstrip() + f"\nsocks5 127.0.0.1 {port}\n"
        dest.write_text(content, encoding="utf-8")
    else:
        dest.write_text(
            f"strict_chain\nproxy_dns\n[ProxyList]\nsocks5 127.0.0.1 {port}\n",
            encoding="utf-8",
        )

    return dest


def _register_alias(beacon_name: str, conf_path: Path) -> str:
    """Write alias to ~/.proxy_aliases and inject source line into all rc files."""
    alias_name = f"p_{beacon_name}"
    alias_line = f"alias {alias_name}='proxychains4 -f {conf_path}'"

    # Create / update ~/.proxy_aliases
    if PROXY_ALIASES_FILE.exists():
        content = PROXY_ALIASES_FILE.read_text(encoding="utf-8")
        # Replace existing alias for this beacon, or append
        pattern = rf"^alias {re.escape(alias_name)}=.*$"
        if re.search(pattern, content, flags=re.MULTILINE):
            content = re.sub(pattern, alias_line, content, flags=re.MULTILINE)
        else:
            content = content.rstrip() + f"\n{alias_line}\n"
        PROXY_ALIASES_FILE.write_text(content, encoding="utf-8")
    else:
        PROXY_ALIASES_FILE.write_text(f"{alias_line}\n", encoding="utf-8")

    # Inject source line into posix rc files that exist
    source_line = f'{_SOURCE_MARKER}\n[ -f "{PROXY_ALIASES_FILE}" ] && source "{PROXY_ALIASES_FILE}"'
    for rc in _RC_FILES:
        if not rc.exists():
            continue
        text = rc.read_text(encoding="utf-8")
        if str(PROXY_ALIASES_FILE) not in text:
            rc.write_text(text.rstrip() + f"\n{source_line}\n", encoding="utf-8")

    # Fish shell uses a different syntax
    if _FISH_CONFIG.exists():
        fish_source = f"{_SOURCE_MARKER}\nif test -f {PROXY_ALIASES_FILE}\n    source {PROXY_ALIASES_FILE}\nend"
        text = _FISH_CONFIG.read_text(encoding="utf-8")
        if str(PROXY_ALIASES_FILE) not in text:
            _FISH_CONFIG.write_text(text.rstrip() + f"\n{fish_source}\n", encoding="utf-8")

    return alias_name


async def run_socks(
    session,
    beacon_selector: str,
    port: int,
    stop: bool,
) -> None:
    beacon = await find_beacon(session, beacon_selector)
    beacon_row = beacon_to_row(beacon)
    beacon_id = beacon_row["id"]
    beacon_name = beacon_row["host"] or beacon_row["name"] or beacon_selector
    callback_numeric_id = _to_int(beacon_row["name"]) or _to_int(beacon_id)

    if callback_numeric_id is None:
        raise RuntimeError(
            f"Beacon '{beacon_selector}' does not have a numeric display id required by Mythic"
        )

    params = _build_params(port, stop)
    action_label = "stop" if stop else "start"
    print(f"[*] Issuing socks {action_label} (port={port}) on beacon {beacon_name!r} ...")

    output = ""
    task_response = None
    try:
        output = await issue_task_and_wait_output(
            session=session,
            callback_display_id=callback_numeric_id,
            command_name="socks",
            parameters=params,
            timeout=60,
        )
    except Exception:
        try:
            task_response = await create_task(
                session,
                beacon_id=beacon_id,
                callback_display_id=beacon_row["name"],
                callback_numeric_id=callback_numeric_id,
                command_name="socks",
                params=params,
                wait_for_complete=True,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to issue socks task: {exc}") from exc

    if task_response is not None and not output:
        task_id = extract_task_id(task_response)
        print(f"[*] Waiting for task output (task_id={task_id}) ...")
        try:
            output = await poll_task_output(session, task_id=task_id, timeout=60, poll_interval=2)
        except TimeoutError:
            pass  # socks tasks often return no output on success

    if output:
        print(output)

    if stop:
        print(f"[+] SOCKS5 proxy stopped on beacon {beacon_name!r}")
        return

    print(f"[+] SOCKS5 proxy started on 127.0.0.1:{port} via beacon {beacon_name!r}")

    conf_path = _setup_proxychains(beacon_name, port)
    print(f"[+] proxychains config written to {conf_path}")

    alias_name = _register_alias(beacon_name, conf_path)
    print(f"[+] alias registered: {alias_name}='proxychains4 -f {conf_path}'")
    print(f"[*] Run in current shell: source {PROXY_ALIASES_FILE}")

