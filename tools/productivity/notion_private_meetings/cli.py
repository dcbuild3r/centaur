"""CLI for the purpose-bound private meeting Notion writer."""

from __future__ import annotations

import json
from typing import Any

import typer

from .client import _client

app = typer.Typer(
    name="notion-private-meetings",
    help="Write Orbie meeting notes to pre-authorized private Notion databases",
)


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


@app.command("query-database")
def query_database(
    database_id: str,
    page_size: int = typer.Option(100, min=1, max=100),
) -> None:
    _print(_client().query_database(database_id, page_size=page_size))


@app.command("create-page")
def create_page(payload: str = typer.Argument(..., help="JSON page creation request")) -> None:
    request = json.loads(payload)
    _print(_client().create_page(**request))
