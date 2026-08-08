import json

from typer.testing import CliRunner

from meeting_ops import client
from meeting_ops.cli import app

runner = CliRunner()


def test_run_cadence_outputs_machine_readable_result(monkeypatch):
    monkeypatch.setattr(
        client,
        "run_cadence",
        lambda cadence_id, now=None: {
            "meetingId": cadence_id,
            "occurrenceAt": now,
            "docUrl": "https://docs.google.com/document/d/doc-123/edit",
        },
    )

    result = runner.invoke(
        app,
        ["run-cadence", "private-weekly", "--now", "2026-08-07T12:00:00Z"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "meetingId": "private-weekly",
        "occurrenceAt": "2026-08-07T12:00:00Z",
        "docUrl": "https://docs.google.com/document/d/doc-123/edit",
    }


def test_notifications_and_acknowledgement_are_separate_commands(monkeypatch):
    monkeypatch.setattr(
        client,
        "pending_notifications",
        lambda: [{"notificationId": "notification-123", "text": "Agenda ready"}],
    )
    monkeypatch.setattr(
        client,
        "acknowledge_notification",
        lambda notification_id: {
            "acknowledged": True,
            "notificationId": notification_id,
        },
    )

    pending = runner.invoke(app, ["notifications"])
    acknowledged = runner.invoke(app, ["acknowledge", "notification-123"])

    assert pending.exit_code == 0
    assert json.loads(pending.output)[0]["notificationId"] == "notification-123"
    assert acknowledged.exit_code == 0
    assert json.loads(acknowledged.output) == {
        "acknowledged": True,
        "notificationId": "notification-123",
    }
