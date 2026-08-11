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
        requester_slack_user_id="U123",
        requester_slack_team_id="TL1HM8UUU",
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
                        "requesterSlackUserId": "U123",
                        "requesterSlackTeamId": "TL1HM8UUU",
                    }
                ],
                "devMode": False,
            },
        }
    ]


def test_run_cadence_forwards_custom_instructions_to_apps_script(monkeypatch):
    service = _Service({"done": True, "response": {"result": {"meetingId": "private-weekly"}}})
    monkeypatch.setattr(client, "get_script_service", lambda: service)
    monkeypatch.setattr(client, "secret", lambda name: "script-123")

    client.run_cadence(
        "private-weekly",
        requester_slack_user_id="U123",
        requester_slack_team_id="TL1HM8UUU",
        custom_instructions="focus on decisions",
    )

    assert service.scripts_api.calls[0]["body"]["parameters"] == [{
        "cadenceId": "private-weekly",
        "customInstructions": "focus on decisions",
        "requesterSlackTeamId": "TL1HM8UUU",
        "requesterSlackUserId": "U123",
    }]


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


def test_authorized_cadences_passes_the_caller_to_apps_script(monkeypatch):
    cadences = [{"id": "public", "visibility": "public"}]
    service = _Service({"done": True, "response": {"result": cadences}})
    monkeypatch.setattr(client, "get_script_service", lambda: service)
    monkeypatch.setattr(client, "secret", lambda name: "script-123")

    assert client.authorized_cadences("U123", "TL1HM8UUU") == cadences
    assert service.scripts_api.calls[0]["body"] == {
        "function": "getAuthorizedCadences",
        "parameters": [{
            "requesterSlackUserId": "U123",
            "requesterSlackTeamId": "TL1HM8UUU",
        }],
        "devMode": False,
    }


def test_pending_notifications_invokes_caller_scoped_outbox_function(monkeypatch):
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

    assert client.pending_notifications_for_caller("U123", "TL1HM8UUU") == notifications
    assert service.scripts_api.calls == [
        {
            "scriptId": "script-123",
            "body": {
                "function": "getPendingOrbieNotificationsForCaller",
                "parameters": [{
                    "requesterSlackUserId": "U123",
                    "requesterSlackTeamId": "TL1HM8UUU",
                }],
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
        requester_slack_user_id="U123",
        requester_slack_team_id="TL1HM8UUU",
    )

    assert result["acknowledged"] is True
    assert service.scripts_api.calls == [
        {
            "scriptId": "script-123",
            "body": {
                "function": "acknowledgeOrbieNotificationForCaller",
                "parameters": [{
                    "notificationId": "private-weekly:2026-08-07:agenda",
                    "requesterSlackUserId": "U123",
                    "requesterSlackTeamId": "TL1HM8UUU",
                }],
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
        client.authorized_cadences,
        client.pending_notifications_for_caller,
        client.acknowledge_notification,
    ):
        assert "script_id" not in inspect.signature(function).parameters
