from __future__ import annotations

import asyncio
import importlib
import inspect
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

api_module = sys.modules.get("api") or types.ModuleType("api")
workflow_engine = types.ModuleType("api.workflow_engine")
workflow_engine.WorkflowContext = object
api_module.workflow_engine = workflow_engine
sys.modules.setdefault("api", api_module)
sys.modules["api.workflow_engine"] = workflow_engine

meeting_automation = importlib.import_module("workflows.meeting_automation")


class FakeClient:
    def __init__(self, cadences, run_result=None, notifications=None):
        self.cadences = cadences
        self.run_result = run_result
        self.notifications = notifications or []
        self.calls = []

    async def authorized_cadences(self, user_id, team_id):
        self.calls.append(("authorized_cadences", user_id, team_id))
        return self.cadences

    async def run_cadence(self, cadence_id, **kwargs):
        self.calls.append(("run_cadence", cadence_id, kwargs))
        return self.run_result

    async def pending_notifications_for_caller(self, user_id, team_id):
        self.calls.append(("pending", user_id, team_id))
        return self.notifications

    async def acknowledge_notification(self, notification_id, **kwargs):
        self.calls.append(("ack", notification_id, kwargs))
        return {"acknowledged": True, "notificationId": notification_id}


class FakeContext:
    def __init__(self):
        self.step_names = []
        self.posts = []

    async def step(self, name, fn, **_kwargs):
        self.step_names.append(name)
        value = fn()
        return await value if inspect.isawaitable(value) else value

    async def post_to_slack(self, channel, text, **_kwargs):
        self.posts.append((channel, text))
        return {"sent": True, "channel": channel}


class RecordingToolContext:
    def __init__(self, result=None):
        self.calls = []
        self.result = [] if result is None else result

    async def call_tool(self, tool, method, args):
        self.calls.append((tool, method, args))
        return self.result


def _input(query="AI Workstream", **overrides):
    values = {
        "cadence_query": query,
        "requester_slack_user_id": "U123",
        "requester_slack_team_id": "TL1HM8UUU",
        "slack_channel_id": "D123456",
        "request_message_id": "1700000000.000001",
        "requester_slack_email": "piotr.piwowarczyk@world.org",
    }
    values.update(overrides)
    return meeting_automation.Input(**values)


def test_tool_client_uses_the_installed_meeting_ops_cli_name():
    context = RecordingToolContext()
    client = meeting_automation.MeetingOpsToolClient(context)

    asyncio.run(client.authorized_cadences("U123", "TL1HM8UUU"))

    assert context.calls == [
        (
            "meeting-ops",
            "authorized_cadences",
            {
                "requester_slack_user_id": "U123",
                "requester_slack_team_id": "TL1HM8UUU",
            },
        )
    ]


def test_tool_client_unwraps_workflow_bridge_output_envelope():
    cadence = {"id": "private-ai", "title": "AI Workstream", "visibility": "private"}
    context = RecordingToolContext({
        "tool": "meeting-ops",
        "method": "authorized_cadences",
        "output": [cadence],
    })
    client = meeting_automation.MeetingOpsToolClient(context)

    result = asyncio.run(client.authorized_cadences("U123", "TL1HM8UUU"))

    assert result == [cadence]


def test_tool_client_preserves_unwrapped_tool_results():
    result = {"meetingId": "private-ai", "docUrl": "https://docs/doc-1"}
    context = RecordingToolContext(result)
    client = meeting_automation.MeetingOpsToolClient(context)

    observed = asyncio.run(client.run_cadence(
        "private-ai",
        requester_slack_user_id="U123",
        requester_slack_team_id="TL1HM8UUU",
    ))

    assert observed == result


def test_private_cadence_delivers_and_acknowledges_only_callers_item(monkeypatch):
    client = FakeClient(
        [{"id": "private-ai", "title": "AI Workstream", "visibility": "private"}],
        run_result={"meetingId": "private-ai", "docUrl": "https://docs/doc-1"},
        notifications=[
            {
                "notificationId": "agenda:private-ai:2026-08-10:U123",
                "meetingId": "private-ai",
                "visibility": "private",
                "recipientSlackUserId": "U123",
                "text": "Agenda ready",
            },
            {
                "notificationId": "agenda:private-ai:2026-08-10:U999",
                "meetingId": "private-ai",
                "visibility": "private",
                "recipientSlackUserId": "U999",
                "text": "Other user's agenda",
            },
            {
                "notificationId": "agenda:other:2026-08-10:U123",
                "meetingId": "other",
                "visibility": "private",
                "recipientSlackUserId": "U123",
                "text": "Unrelated agenda",
            },
        ],
    )
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)
    context = FakeContext()

    result = asyncio.run(meeting_automation.handler(_input("private-ai"), context))

    assert result["visibility"] == "private"
    assert context.posts == [("D123456", "Agenda ready")]
    assert [call[0] for call in client.calls] == [
        "authorized_cadences",
        "run_cadence",
        "pending",
        "ack",
    ]
    assert all("1700000000.000001" in name for name in context.step_names)
    assert context.step_names.index(next(name for name in context.step_names if name.startswith("deliver_private"))) < context.step_names.index(next(name for name in context.step_names if name.startswith("ack_private")))


def test_public_cadence_reports_doc_to_dm_without_reading_or_acknowledging_outbox(monkeypatch):
    client = FakeClient(
        [{"id": "public-ai", "title": "AI Workstream Weekly", "visibility": "public"}],
        run_result={"meetingId": "public-ai", "docUrl": "https://docs/doc-2"},
    )
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)
    context = FakeContext()

    result = asyncio.run(meeting_automation.handler(_input("workstream"), context))

    assert result["visibility"] == "public"
    assert context.posts == [
        ("D123456", "Meeting automation complete for *AI Workstream Weekly*.\nDocument: https://docs/doc-2")
    ]
    assert [call[0] for call in client.calls] == ["authorized_cadences", "run_cadence"]
    assert "deliver_public_result:1700000000.000001:public-ai" in context.step_names


def test_query_prefers_exact_id_or_title_then_unique_case_insensitive_substring():
    cadence = {"id": "weekly-sync", "title": "Weekly Sync", "visibility": "public"}
    assert meeting_automation._resolve_cadence([cadence], "Weekly Sync") is cadence
    assert meeting_automation._resolve_cadence([cadence], "SYNC") is cadence
    with pytest.raises(ValueError, match="no authorized cadence"):
        meeting_automation._resolve_cadence([], "private")


def test_handler_hides_unknown_and_unauthorized_cadence_names(monkeypatch):
    client = FakeClient([])
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)
    context = FakeContext()

    result = asyncio.run(meeting_automation.handler(_input("secret leadership"), context))

    assert result["status"] == "rejected"
    assert [call[0] for call in client.calls] == ["authorized_cadences"]
    assert context.posts == [
        (
            "D123456",
            "I couldn't find one cadence you are allowed to run with that name. "
            "Use its exact cadence ID or title and try again.",
        )
    ]


def test_private_cadence_without_due_notification_reports_noop(monkeypatch):
    client = FakeClient(
        [{"id": "private-ai", "title": "AI Workstream", "visibility": "private"}],
        run_result=None,
        notifications=[],
    )
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)
    context = FakeContext()

    result = asyncio.run(meeting_automation.handler(_input("private-ai"), context))

    assert result["acknowledged"] == []
    assert context.posts == [
        (
            "D123456",
            "Meeting automation ran for *AI Workstream*, but no document was created in the current window.",
        )
    ]


def test_input_requires_world_team_and_dm_channel():
    with pytest.raises(ValueError, match="World Slack team"):
        meeting_automation._validate_input(_input(requester_slack_team_id="TOTHER"))
    with pytest.raises(ValueError, match="DM channel"):
        meeting_automation._validate_input(_input(slack_channel_id="C123456"))
