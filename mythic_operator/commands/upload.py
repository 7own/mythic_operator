from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mythic_operator.api import find_mythic_file, list_mythic_files, upload_file_to_mythic

_console = Console()


def _render_files(files: list[dict]) -> None:
    if not files:
        _console.print("[yellow]No files registered in Mythic.[/yellow]")
        return
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("AGENT_FILE_ID", style="dim")
    table.add_column("FILENAME")
    table.add_column("SIZE", justify="right")
    table.add_column("COMPLETE")
    for f in files:
        size = str(f.get("size") or "")
        complete = "[green]yes[/green]" if f.get("complete") else "[red]no[/red]"
        table.add_row(
            str(f.get("agent_file_id", "")),
            str(f.get("filename_utf8", "")),
            size,
            complete,
        )
    _console.print(table)


async def run_upload(
    session,
    file_path: Path | None,
    name_override: str | None,
    list_files: bool,
    force: bool,
) -> None:
    if list_files:
        files = await list_mythic_files(session)
        _render_files(files)
        return

    if file_path is None:
        raise ValueError("--file is required when not using --list")

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    upload_name = name_override or file_path.name

    if not force:
        existing = await find_mythic_file(session, upload_name)
        if existing:
            print(f"[*] {upload_name!r} already in Mythic (id={existing}) — skipping. Use --force to re-upload.")
            return

    print(f"[*] Uploading {file_path} as {upload_name!r} ...")
    file_id = await upload_file_to_mythic(session, file_path, filename_override=upload_name)
    print(f"[+] Uploaded {upload_name!r} → id={file_id}")
