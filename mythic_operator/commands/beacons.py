from __future__ import annotations

import json

from rich.console import Console
from rich.table import Table

from mythic_operator.api import beacon_to_row


def render_beacons(beacons, as_json: bool = False) -> None:
    rows = [beacon_to_row(b) for b in beacons]
    if as_json:
        print(json.dumps(rows, indent=2))
        return

    table = Table(show_header=True, header_style="bold")
    columns = ["id", "name", "host", "user", "os", "pid", "last_seen", "ip"]
    for column in columns:
        table.add_column(column.upper())
    for row in rows:
        table.add_row(*(row[col] for col in columns))
    Console().print(table)
