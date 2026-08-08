import inspect
from types import SimpleNamespace

import pytest
from googleapiclient.errors import HttpError

from meeting_ops import client


class _Request:
    def __init__(self, result: dict):
        self.result = result

    def execute(self) -> dict:
        return self.result


class _Scripts:
    def __init__(self, result: dict):
        self.result = result
        self.calls: list[dict] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return _Request(self.result)


class _Service:
    def __init__(self, result: dict):
        self.scripts_api = _Scripts(result)

    def scripts(self):
        return self.scripts_api


def test_run_cadence_invokes_only_the_worker_entrypoint(monkeypatch):
    service = _Service(
        {
            "done": True,
            "response": {
                "result": {
                    "meetingId": "private-weekly",
                    "docUrl": "https://docs.google.com/document/d/doc-123/edit",
                }
            },
        }
    )
    monkeypatch.setattr(client, "get_script_service", lambda: service)
    monkeypatch.setattr(client, "secret", lambda name: "script-123")

    result = client.run_cadence(
        "private-weekly",
        now="2026-08-07T12:00:00Z",
    )

    assert result["meetingId"] == "private-weekly"
    assert service.scripts_api.calls == [
        {
            "scriptId": "script-123",
            "body": {
                "function": "runCadenceJob",
                "parameters": [
                    {
                        "cadenceId": "private-weekly",
                        "now": "2026-08-07T12:00:00Z",
                    }
                ],
                "devMode": False,
            },
        }
    ]


def test_execution_error_surfaces_apps_script_message(monkeypatch):
    service = _Service(
        {
            "done": True,
            "error": {
                "message": "ScriptError",
                "details": [{"errorMessage": "Unknown cadence private-weekly"}],
            },
        }
    )
    monkeypatch.setattr(client, "get_script_service", lambda: service)
    monkeypatch.setattr(client, "secret", lambda name: "script-123")

    with pytest.raises(client.MeetingOpsError, match="Unknown cadence private-weekly"):
        client.run_cadence("private-weekly")


def test_google_http_error_is_sanitized(monkeypatch):
    class _FailingRequest:
        def execute(self):
            raise HttpError(
                SimpleNamespace(status=403, reason="Forbidden"),
                b'{"error":{"message":"sensitive internal request details"}}',
                uri="https://script.googleapis.com/v1/scripts/private-script-id:run",
            )

    service = _Service({})
    monkeypatch.setattr(service.scripts_api, "run", lambda **kwargs: _FailingRequest())
    monkeypatch.setattr(client, "get_script_service", lambda: service)
    monkeypatch.setattr(client, "secret", lambda name: "script-123")

    with pytest.raises(
        client.MeetingOpsError,
        match=r"^Google Apps Script request failed \(HTTP 403\)$",
    ) as raised:
        client.run_cadence("private-weekly")

    assert "private-script-id" not in str(raised.value)
    assert "sensitive" not in str(raised.value)


def test_pending_notifications_invokes_read_only_outbox_function(monkeypatch):
    notifications = [
        {
            "notificationId": "private-weekly:2026-08-07:agenda",
            "recipientSlackUserIds": ["U123"],
            "text": "Agenda ready",
        }
    ]
    service = _Service({"done": True, "response": {"result": notifications}})
    monkeypatch.setattr(client, "get_script_service", lambda: service)
    monkeypatch.setattr(client, "secret", lambda name: "script-123")

    assert client.pending_notifications() == notifications
    assert service.scripts_api.calls == [
        {
            "scriptId": "script-123",
            "body": {
                "function": "getPendingOrbieNotifications",
                "devMode": False,
            },
        }
    ]


def test_acknowledge_notification_passes_only_the_notification_id(monkeypatch):
    service = _Service(
        {
            "done": True,
            "response": {
                "result": {
                    "acknowledged": True,
                    "notificationId": "private-weekly:2026-08-07:agenda",
                }
            },
        }
    )
    monkeypatch.setattr(client, "get_script_service", lambda: service)
    monkeypatch.setattr(client, "secret", lambda name: "script-123")

    result = client.acknowledge_notification(
        "private-weekly:2026-08-07:agenda",
    )

    assert result["acknowledged"] is True
    assert service.scripts_api.calls == [
        {
            "scriptId": "script-123",
            "body": {
                "function": "acknowledgeOrbieNotification",
                "parameters": ["private-weekly:2026-08-07:agenda"],
                "devMode": False,
            },
        }
    ]


def test_missing_fixed_script_id_fails_before_calling_google(monkeypatch):
    monkeypatch.setattr(client, "secret", lambda name: "")

    with pytest.raises(client.MeetingOpsError, match="Missing MEETING_OPS_SCRIPT_ID"):
        client.run_cadence("private-weekly")


def test_public_methods_do_not_allow_callers_to_select_another_script():
    for function in (
        client.run_cadence,
        client.pending_notifications,
        client.acknowledge_notification,
    ):
        assert "script_id" not in inspect.signature(function).parameters
