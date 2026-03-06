from __future__ import annotations

import asyncio

import click

from mythic_operator.api import is_active, list_beacons, login
from mythic_operator.commands.beacons import render_beacons
from mythic_operator.commands.chisel import DEFAULT_CHISEL_PATH, run_chisel
from mythic_operator.commands.mimikatz import run_mimikatz
from mythic_operator.commands.socks import run_socks
from mythic_operator.commands.upload import run_upload
from mythic_operator.config import build_config, create_config_file


def _config_flag_callback(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    path = create_config_file()
    click.echo(f"[+] Config file ready at {path}. Please edit it before use.")
    ctx.exit(0)


@click.group()
@click.option("--url", help="Mythic server URL")
@click.option("--username", help="Operator username")
@click.option("--password", help="Operator password")
@click.option(
    "--config",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_config_flag_callback,
    help="Create ~/.pwnbox/mythic.toml template and exit",
)
@click.pass_context
def cli(ctx: click.Context, url: str | None, username: str | None, password: str | None) -> None:
    """Mythic operator CLI."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = build_config(url=url, username=username, password=password)


@cli.command("list-beacons")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--active-only/--all", default=True, help="Only show beacons active in the last 60s")
@click.pass_context
def list_beacons_cmd(ctx: click.Context, as_json: bool, active_only: bool) -> None:
    """List active beacons."""
    config = ctx.obj["config"]

    async def _run():
        session = await login(config)
        beacons = await list_beacons(session)
        if active_only:
            return [b for b in beacons if is_active(b, seconds=60)]
        return beacons

    beacons = asyncio.run(_run())
    render_beacons(beacons, as_json=as_json)


@cli.command("mimikatz")
@click.option("--beacon", required=True, help="Beacon ID or name")
@click.option("--commands", help="Comma-separated Mimikatz commands")
@click.option("--ingest", is_flag=True, help="Ingest output via credops")
@click.option("--tag", help="Credops ingest tag")
@click.option("--save", help="Save raw output to a file")
@click.option("--dry-run", is_flag=True, help="Show command and exit")
@click.pass_context
def mimikatz_cmd(
    ctx: click.Context,
    beacon: str,
    commands: str | None,
    ingest: bool,
    tag: str | None,
    save: str | None,
    dry_run: bool,
) -> None:
    """Run Mimikatz on a beacon."""
    config = ctx.obj["config"]

    async def _run():
        session = None if dry_run else await login(config)
        await run_mimikatz(
            session=session,
            beacon_selector=beacon,
            commands_value=commands,
            ingest=ingest,
            tag=tag,
            save=save,
            dry_run=dry_run,
        )

    asyncio.run(_run())


@cli.command("socks")
@click.option("--beacon", required=True, help="Beacon ID or name")
@click.option("--port", default=7000, show_default=True, type=int, help="Local SOCKS5 port")
@click.option("--stop", is_flag=True, help="Stop the existing SOCKS proxy on the beacon")
@click.pass_context
def socks_cmd(ctx: click.Context, beacon: str, port: int, stop: bool) -> None:
    """Set up a Mythic built-in SOCKS5 proxy on a beacon."""
    config = ctx.obj["config"]

    async def _run():
        session = await login(config)
        await run_socks(session=session, beacon_selector=beacon, port=port, stop=stop)

    asyncio.run(_run())


@cli.command("upload")
@click.option("--file", "file_path", type=click.Path(), default=None, help="Local file to upload")
@click.option("--name", "name_override", default=None, help="Override filename in Mythic")
@click.option("--list", "list_files", is_flag=True, help="List all registered files in Mythic")
@click.option("--force", is_flag=True, help="Re-upload even if file already exists")
@click.pass_context
def upload_cmd(
    ctx: click.Context,
    file_path: str | None,
    name_override: str | None,
    list_files: bool,
    force: bool,
) -> None:
    """Upload a file to Mythic or list registered files."""
    config = ctx.obj["config"]

    async def _run():
        from pathlib import Path
        session = await login(config)
        await run_upload(
            session=session,
            file_path=Path(file_path).expanduser() if file_path else None,
            name_override=name_override,
            list_files=list_files,
            force=force,
        )

    asyncio.run(_run())


@cli.command("chisel")
@click.option("--beacon", required=True, help="Beacon ID or name")
@click.option("--lhost", required=True, help="Chisel server IP (your machine)")
@click.option("--lport", default=8000, show_default=True, type=int, help="Chisel server port")
@click.option("--sport", default=1080, show_default=True, type=int, help="Local SOCKS5 port")
@click.option(
    "--chisel-path",
    default=str(DEFAULT_CHISEL_PATH),
    show_default=True,
    help="Local path to chisel.exe",
)
@click.option("--stop", is_flag=True, help="Kill chisel on the beacon")
@click.pass_context
def chisel_cmd(
    ctx: click.Context,
    beacon: str,
    lhost: str,
    lport: int,
    sport: int,
    chisel_path: str,
    stop: bool,
) -> None:
    """Set up a Chisel SOCKS5 reverse proxy on a beacon."""
    config = ctx.obj["config"]

    async def _run():
        from pathlib import Path
        session = await login(config)
        await run_chisel(
            session=session,
            beacon_selector=beacon,
            lhost=lhost,
            lport=lport,
            sport=sport,
            chisel_path=Path(chisel_path).expanduser(),
            stop=stop,
        )

    asyncio.run(_run())


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
