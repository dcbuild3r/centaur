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
    requester_slack_user_id: str = typer.Option(..., "--requester-slack-user-id"),
    requester_slack_team_id: str = typer.Option(..., "--requester-slack-team-id"),
) -> None:
    """Create or reuse the Google Doc for one cadence occurrence."""

    _print_json(client.run_cadence(
        cadence_id,
        now=now,
        requester_slack_user_id=requester_slack_user_id,
        requester_slack_team_id=requester_slack_team_id,
    ))


@app.command("cadences")
def cadences(
    requester_slack_user_id: str = typer.Option(..., "--requester-slack-user-id"),
    requester_slack_team_id: str = typer.Option(..., "--requester-slack-team-id"),
) -> None:
    """List active cadences the Slack caller may use."""

    _print_json(client.authorized_cadences(
        requester_slack_user_id,
        requester_slack_team_id,
    ))


@app.command("notifications")
def notifications(
    requester_slack_user_id: str = typer.Option(..., "--requester-slack-user-id"),
    requester_slack_team_id: str = typer.Option(..., "--requester-slack-team-id"),
) -> None:
    """List private notifications addressed to one Slack caller."""

    _print_json(client.pending_notifications_for_caller(
        requester_slack_user_id,
        requester_slack_team_id,
    ))


@app.command("acknowledge")
def acknowledge(
    notification_id: str = typer.Argument(
        ...,
        help="Notification identifier returned by the outbox",
    ),
    requester_slack_user_id: str = typer.Option(..., "--requester-slack-user-id"),
    requester_slack_team_id: str = typer.Option(..., "--requester-slack-team-id"),
) -> None:
    """Acknowledge the caller's item only after Slack confirms delivery."""

    _print_json(client.acknowledge_notification(
        notification_id,
        requester_slack_user_id=requester_slack_user_id,
        requester_slack_team_id=requester_slack_team_id,
    ))
