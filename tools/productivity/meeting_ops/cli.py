"""CLI for the Google Apps Script Meeting Ops worker."""

from __future__ import annotations

import json
from typing import Any

import typer

from . import client

app = typer.Typer(
    name="meeting-ops",
    help="Run approved Meeting Ops functions through Google Apps Script.",
)


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


@app.command("run-cadence")
def run_cadence(
    cadence_id: str = typer.Argument(..., help="Approved cadence identifier"),
    now: str | None = typer.Option(
        None,
        "--now",
        help="Optional ISO-8601 clock used for deterministic retries and tests",
    ),
) -> None:
    """Create or reuse the Google Doc for one cadence occurrence."""

    _print_json(client.run_cadence(cadence_id, now=now))


@app.command("notifications")
def notifications() -> None:
    """List outbox notifications awaiting Orbie Slack delivery."""

    _print_json(client.pending_notifications())


@app.command("acknowledge")
def acknowledge(
    notification_id: str = typer.Argument(
        ...,
        help="Notification identifier returned by the outbox",
    ),
) -> None:
    """Acknowledge an outbox item only after Slack confirms delivery."""

    _print_json(client.acknowledge_notification(notification_id))
