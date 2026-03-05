from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import toml as tomllib  # type: ignore[no-redef]


DEFAULT_CONFIG_PATH = Path("~/.pwnbox/mythic.toml").expanduser()
DEFAULT_CONFIG_TEMPLATE = """[mythic]
url = "https://127.0.0.1:7443"
username = "operator"
password = "changeme"
ssl_verify = false
"""


@dataclass(frozen=True)
class MythicConfig:
    url: str
    username: str
    password: str
    ssl_verify: bool = False


def _read_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f)
    return data.get("mythic", {}) if isinstance(data, dict) else {}


def build_config(url: str | None, username: str | None, password: str | None) -> MythicConfig:
    file_cfg = _read_config()
    final_url = url or os.getenv("MYTHIC_URL") or file_cfg.get("url") or "https://127.0.0.1:7443"
    final_user = username or os.getenv("MYTHIC_USER") or file_cfg.get("username") or "operator"
    final_pass = password or os.getenv("MYTHIC_PASS") or file_cfg.get("password") or ""
    final_ssl = bool(file_cfg.get("ssl_verify", False))

    if not final_pass:
        raise ValueError("Mythic password is required (config, env MYTHIC_PASS, or --password)")

    return MythicConfig(
        url=str(final_url),
        username=str(final_user),
        password=str(final_pass),
        ssl_verify=final_ssl,
    )


def create_config_file(path: Path = DEFAULT_CONFIG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
    return path
