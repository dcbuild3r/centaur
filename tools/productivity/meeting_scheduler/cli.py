"""CLI for governed Orbie meeting scheduling."""

from __future__ import annotations

import json
from typing import Any

import typer

from .client import _client

app = typer.Typer(name="meeting-scheduler", help="Governed Orbie Calendar and Zoom scheduling")


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


@app.command("availability")
def availability(payload: str = typer.Argument(..., help="JSON availability request")) -> None:
    _print(_client().find_availability(**json.loads(payload)))


@app.command("book")
def book(payload: str = typer.Argument(..., help="JSON booking request")) -> None:
    _print(_client().book_meeting(**json.loads(payload)))


@app.command("reschedule")
def reschedule(payload: str = typer.Argument(..., help="JSON reschedule request")) -> None:
    _print(_client().reschedule_meeting(**json.loads(payload)))


@app.command("cancel")
def cancel(payload: str = typer.Argument(..., help="JSON cancellation request")) -> None:
    _print(_client().cancel_meeting(**json.loads(payload)))


@app.command("get")
def get(payload: str = typer.Argument(..., help="JSON reconciliation request")) -> None:
    _print(_client().get_or_reconcile_meeting(**json.loads(payload)))
