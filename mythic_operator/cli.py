from __future__ import annotations

import asyncio

import click

from mythic_operator.api import is_active, list_beacons, login
from mythic_operator.commands.beacons import render_beacons
from mythic_operator.config import build_config


@click.group()
@click.option("--url", help="Mythic server URL")
@click.option("--username", help="Operator username")
@click.option("--password", help="Operator password")
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


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
