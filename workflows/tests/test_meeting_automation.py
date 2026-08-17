from __future__ import annotations

import asyncio
import datetime as dt
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
    def __init__(
        self,
        cadences,
        run_result=None,
        notifications=None,
        slack_users=None,
        channel_members=None,
    ):
        self.cadences = cadences
        self.run_result = run_result
        self.notifications = notifications or []
        self.slack_user_data = slack_users or [
            {
                "id": "U123",
                "email": "piotr.piwowarczyk@world.org",
                "team_id": "TL1HM8UUU",
                "is_bot": False,
            }
        ]
        self.channel_member_data = channel_members or [
            {
                "id": "U123",
                "email": "piotr.piwowarczyk@world.org",
                "team_id": "TL1HM8UUU",
                "is_bot": False,
            }
        ]
        self.calls = []
        self.sent = []
        self.drive_permissions = []

    async def authorized_cadences(self, user_id, team_id):
        self.calls.append(("authorized_cadences", user_id, team_id))
        return self.cadences

    async def run_cadence(self, cadence_id, **kwargs):
        self.calls.append(("run_cadence", cadence_id, kwargs))
        return self.run_result

    async def run_scheduled_cadence(self, cadence, occurrence_at, **kwargs):
        self.calls.append(("run_scheduled_cadence", cadence, occurrence_at, kwargs))
        return self.run_result

    async def notion_cadences(self):
        return []

    async def notion_users(self):
        return []

    async def pending_notifications_for_caller(self, user_id, team_id):
        self.calls.append(("pending", user_id, team_id))
        return self.notifications

    async def pending_notifications(self):
        self.calls.append(("pending_all",))
        return self.notifications

    async def acknowledge_notification(self, notification_id, **kwargs):
        self.calls.append(("ack", notification_id, kwargs))
        return {"acknowledged": True, "notificationId": notification_id}

    async def acknowledge_notification_unscoped(self, notification_id):
        self.calls.append(("ack_all", notification_id))
        return {"acknowledged": True, "notificationId": notification_id}

    async def send_slack_message(self, channel, text, **kwargs):
        self.calls.append(("send", channel, text, kwargs))
        self.sent.append((channel, text, kwargs))
        return {"sent": True, "ts": "1785153461.533159"}

    async def slack_users(self):
        self.calls.append(("slack_users",))
        return self.slack_user_data

    async def slack_channel_members(self, channel_id):
        self.calls.append(("channel_members", channel_id))
        return self.channel_member_data

    async def share_drive_file(self, file_id, email):
        self.calls.append(("drive_share", file_id, email))
        self.drive_permissions.append({"email": email, "role": "writer"})
        return {"email": email, "role": "writer"}

    async def drive_file_permissions(self, file_id):
        self.calls.append(("drive_permissions", file_id))
        return list(self.drive_permissions)


class MalformedAcknowledgementClient(FakeClient):
    async def acknowledge_notification(self, notification_id, **kwargs):
        self.calls.append(("ack", notification_id, kwargs))
        return {}


class MissingMpimScopeClient(FakeClient):
    async def slack_channel_members(self, channel_id):
        self.calls.append(("channel_members", channel_id))
        raise RuntimeError(
            "Slack API conversations.members failed: missing_scope; needed mpim:read"
        )


class UnverifiedDriveClient(FakeClient):
    async def share_drive_file(self, file_id, email):
        self.calls.append(("drive_share", file_id, email))
        return {"email": email, "role": "writer"}


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


class NotionDatabaseDiscoveryContext:
    def __init__(self):
        self.calls = []

    async def call_tool(self, tool, method, args):
        self.calls.append((tool, method, args))
        if method == "search":
            return {
                "results": [
                    {
                        "object": "database",
                        "id": "private-db",
                        "title": [{"plain_text": "Personal Meetings"}],
                        "description": [
                            {
                                "plain_text": meeting_automation.PRIVATE_CADENCE_TEMPLATE_MARKER
                            }
                        ],
                    },
                    {
                        "object": "database",
                        "id": "unrelated-db",
                        "title": [{"plain_text": "Tasks"}],
                        "description": [],
                    },
                ],
                "has_more": False,
            }
        database_id = args["database_id"]
        return {
            "results": [{"id": f"row-{database_id}", "properties": {}}],
            "has_more": False,
        }


class SchedulingFakeClient:
    def __init__(self, result):
        self.result = result
        self.cadence_rows = [
            {
                "id": "notion-page-1",
                "properties": {
                    "Automation ID": {
                        "type": "rich_text",
                        "rich_text": [{"plain_text": "weekly-sync"}],
                    },
                    "Owner / DRI": {
                        "type": "people",
                        "people": [{"id": "owner-1"}],
                    },
                },
            }
        ]
        self.calls = []
        self.booking_updates = []

    async def scheduling_operation(self, operation, args):
        self.calls.append(("scheduling", operation, args))
        return self.result

    async def notion_cadences(self):
        self.calls.append(("notion_cadences",))
        return self.cadence_rows

    async def notion_users(self):
        self.calls.append(("notion_users",))
        return [{"id": "owner-1", "person": {"email": "piotr.piwowarczyk@world.org"}}]

    async def slack_users(self):
        self.calls.append(("slack_users",))
        return [
            {
                "id": "U123",
                "email": "piotr.piwowarczyk@world.org",
                "team_id": "TL1HM8UUU",
                "is_bot": False,
            }
        ]

    async def update_notion_booking(self, page_id, status, **kwargs):
        self.booking_updates.append((page_id, status, kwargs))
        return {"id": page_id}


def test_notion_tool_client_discovers_marked_private_cadence_databases():
    async def run():
        context = NotionDatabaseDiscoveryContext()
        client = meeting_automation.MeetingOpsToolClient(context)
        rows = await client.notion_cadences()
        return context, rows

    context, rows = asyncio.run(run())
    assert [row["id"] for row in rows] == [
        f"row-{meeting_automation.CADENCES_DATABASE_ID}",
        "row-private-db",
    ]
    assert rows[1]["_cadence_database_id"] == "private-db"
    assert not any(args.get("database_id") == "unrelated-db" for _, _, args in context.calls)


def _input(query="AI Workstream", **overrides):
    values = {
        "cadence_query": query,
        "requester_slack_user_id": "U123",
        "requester_slack_team_id": "TL1HM8UUU",
        "slack_channel_id": "D123456",
        "slack_conversation_kind": "dm",
        "request_message_id": "1700000000.000001",
        "requester_slack_email": "piotr.piwowarczyk@world.org",
    }
    values.update(overrides)
    if not values["slack_channel_id"].startswith("D"):
        values.setdefault("slack_thread_ts", values["request_message_id"])
    return meeting_automation.Input(**values)


def test_scheduler_uses_a_durable_cron_tick():
    assert meeting_automation.SCHEDULE["schedule_id"] == "meeting_automation_scheduler"
    assert meeting_automation.SCHEDULE["cron"] == "*/15 * * * *"
    assert meeting_automation.SCHEDULE["enabled"] is False
    assert meeting_automation.SCHEDULE["no_delivery"] is True


def test_scheduler_feature_flag_preserves_disabled_default(monkeypatch):
    monkeypatch.delenv("MEETING_OPS_SCHEDULER_ENABLED", raising=False)

    assert meeting_automation._env_flag("MEETING_OPS_SCHEDULER_ENABLED") is False
    assert (
        meeting_automation._env_flag("MEETING_OPS_SCHEDULER_ENABLED", default=True)
        is True
    )


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


def test_tool_client_fetches_a_full_slack_user_page_for_email_resolution():
    context = RecordingToolContext([])
    client = meeting_automation.MeetingOpsToolClient(context)

    asyncio.run(client.slack_users())

    assert context.calls == [("slack", "list_users", {"limit": 10000})]


def test_tool_client_uses_gsuite_for_drive_acl_changes_and_readback():
    context = RecordingToolContext([])
    client = meeting_automation.MeetingOpsToolClient(context)

    asyncio.run(client.share_drive_file("doc-1", "dc.builder@world.org"))
    asyncio.run(client.drive_file_permissions("doc-1"))

    assert context.calls == [
        (
            "gsuite",
            "drive_share",
            {
                "file_id": "doc-1",
                "email": "dc.builder@world.org",
                "role": "writer",
                "send_notification": False,
            },
        ),
        ("gsuite", "drive_list_permissions", {"file_id": "doc-1"}),
    ]


def test_tool_client_unwraps_workflow_bridge_output_envelope():
    cadence = {"id": "private-ai", "title": "AI Workstream", "visibility": "private"}
    context = RecordingToolContext(
        {
            "tool": "meeting-ops",
            "method": "authorized_cadences",
            "output": [cadence],
        }
    )
    client = meeting_automation.MeetingOpsToolClient(context)

    result = asyncio.run(client.authorized_cadences("U123", "TL1HM8UUU"))

    assert result == [cadence]


@pytest.mark.parametrize(
    "wrapped",
    [
        {
            "tool": "meeting-ops",
            "method": "authorized_cadences",
            "output": {"ok": True, "result": [{"id": "private-ai"}]},
        },
        {
            "content": [
                {
                    "type": "text",
                    "text": '[{"id":"private-ai"}]',
                }
            ],
        },
        {
            "structuredContent": {
                "result": [{"id": "private-ai"}],
            },
        },
        {
            "ok": True,
            "output": [{"id": "private-ai"}],
        },
        {
            "status": "success",
            "data": [{"id": "private-ai"}],
        },
    ],
)
def test_tool_client_unwraps_nested_and_mcp_compatible_results(wrapped):
    context = RecordingToolContext(wrapped)
    client = meeting_automation.MeetingOpsToolClient(context)

    result = asyncio.run(client.authorized_cadences("U123", "TL1HM8UUU"))

    assert result == [{"id": "private-ai"}]


def test_tool_client_preserves_unwrapped_tool_results():
    result = {
        "meetingId": "private-ai",
        "docUrl": "https://docs.google.com/document/d/doc-1/edit",
    }
    context = RecordingToolContext(result)
    client = meeting_automation.MeetingOpsToolClient(context)

    observed = asyncio.run(
        client.run_cadence(
            "private-ai",
            requester_slack_user_id="U123",
            requester_slack_team_id="TL1HM8UUU",
        )
    )

    assert observed == result


def test_scheduling_args_reject_unknown_provider_fields():
    with pytest.raises(ValueError, match="unsupported arguments: calendar_id"):
        meeting_automation._scheduling_args(
            _input(
                scheduling_operation="find_availability",
                scheduling_args={
                    "organizer_calendar_key": "wf-main",
                    "attendee_emails": ["person@world.org"],
                    "time_min": "2099-08-17T09:00:00Z",
                    "time_max": "2099-08-17T10:00:00Z",
                    "duration_minutes": 30,
                    "calendar_id": "primary",
                },
            )
        )


def test_reschedule_updates_the_existing_notion_cadence_booking(monkeypatch):
    client = SchedulingFakeClient(
        {
            "status": "booked",
            "cadence_id": "weekly-sync",
            "actualStart": "2026-08-24T09:00:00Z",
            "zoomJoinUrl": "https://zoom.us/j/123",
        }
    )
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)

    result = asyncio.run(
        meeting_automation.handler(
            _input(
                slack_channel_id="",
                scheduling_operation="reschedule_meeting",
                scheduling_args={
                    "occurrence_key": "weekly-sync:2026-08-24",
                    "start": "2026-08-24T09:00:00Z",
                    "expected_version": 2,
                    "organizer_calendar_key": "wf-main",
                    "confirmation_token": "confirmed",
                },
            ),
            FakeContext(),
        )
    )

    assert result["cadenceUpdate"] == {"id": "notion-page-1"}
    assert client.booking_updates == [
        (
            "notion-page-1",
            "Booked",
            {
                "booked_start": "2026-08-24T09:00:00Z",
                "meeting_url": "https://zoom.us/j/123",
            },
        )
    ]


def test_cancel_clears_the_existing_notion_cadence_booking(monkeypatch):
    client = SchedulingFakeClient({"status": "cancelled", "cadence_id": "weekly-sync"})
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)

    result = asyncio.run(
        meeting_automation.handler(
            _input(
                slack_channel_id="",
                scheduling_operation="cancel_meeting",
                scheduling_args={
                    "occurrence_key": "weekly-sync:2026-08-24",
                    "organizer_calendar_key": "wf-main",
                    "confirmation_token": "confirmed",
                },
            ),
            FakeContext(),
        )
    )

    assert result["cadenceUpdate"] == {"id": "notion-page-1"}
    assert client.booking_updates == [
        ("notion-page-1", "Not booked", {"clear_booking": True})
    ]


def test_cadence_meeting_mutation_requires_an_authorized_requester(monkeypatch):
    client = SchedulingFakeClient(
        {
            "status": "booked",
            "cadence_id": "weekly-sync",
            "actualStart": "2026-08-24T09:00:00Z",
            "zoomJoinUrl": "https://zoom.us/j/123",
        }
    )
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)

    with pytest.raises(ValueError, match="not authorized"):
        asyncio.run(
            meeting_automation.handler(
                _input(
                    requester_slack_user_id="U999",
                    slack_channel_id="",
                    scheduling_operation="cancel_meeting",
                    scheduling_args={
                        "occurrence_key": "weekly-sync:2026-08-24",
                        "organizer_calendar_key": "wf-main",
                        "confirmation_token": "confirmed",
                    },
                ),
                FakeContext(),
            )
        )

    assert [call[1] for call in client.calls if call[0] == "scheduling"] == [
        "get_or_reconcile_meeting"
    ]
    assert client.booking_updates == []


def test_tool_client_forwards_custom_instructions_only_when_present():
    context = RecordingToolContext({"meetingId": "private-ai"})
    client = meeting_automation.MeetingOpsToolClient(context)

    asyncio.run(
        client.run_cadence(
            "private-ai",
            requester_slack_user_id="U123",
            requester_slack_team_id="TL1HM8UUU",
            custom_instructions="focus on decisions",
        )
    )

    assert context.calls == [
        (
            "meeting-ops",
            "run_cadence",
            {
                "cadence_id": "private-ai",
                "custom_instructions": "focus on decisions",
                "requester_slack_user_id": "U123",
                "requester_slack_team_id": "TL1HM8UUU",
            },
        )
    ]


def test_tool_client_forwards_document_editor_emails_to_apps_script():
    context = RecordingToolContext({"meetingId": "public-ai"})
    client = meeting_automation.MeetingOpsToolClient(context)

    asyncio.run(
        client.run_cadence(
            "public-ai",
            requester_slack_user_id="U123",
            requester_slack_team_id="TL1HM8UUU",
            document_editor_emails=["piotr.piwowarczyk@world.org"],
        )
    )

    assert context.calls[0][2]["document_editor_emails"] == [
        "piotr.piwowarczyk@world.org"
    ]


def test_private_cadence_delivers_and_acknowledges_only_callers_item(monkeypatch):
    client = FakeClient(
        [{"id": "private-ai", "title": "AI Workstream", "visibility": "private"}],
        run_result={
            "meetingId": "private-ai",
            "docUrl": "https://docs.google.com/document/d/doc-1/edit",
        },
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
        "slack_users",
        "run_cadence",
        "drive_permissions",
        "drive_share",
        "drive_permissions",
        "pending",
        "ack",
    ]
    assert all("1700000000.000001" in name for name in context.step_names)
    assert context.step_names.index(
        next(name for name in context.step_names if name.startswith("deliver_private"))
    ) < context.step_names.index(
        next(name for name in context.step_names if name.startswith("ack_private"))
    )


def test_private_mpim_shares_document_with_all_active_human_members(monkeypatch):
    client = FakeClient(
        [{"id": "private-ai", "title": "AI Workstream", "visibility": "private"}],
        run_result={
            "meetingId": "private-ai",
            "docUrl": "https://docs.google.com/document/d/doc-1/edit",
        },
        slack_users=[
            {
                "id": "U123",
                "email": "requester@world.org",
                "team_id": "TL1HM8UUU",
                "is_bot": False,
            },
            {
                "id": "UPIOTR",
                "email": "piotr.piwowarczyk@world.org",
                "team_id": "TL1HM8UUU",
                "is_bot": False,
            },
            {
                "id": "UBOT",
                "email": "orbie@world.org",
                "team_id": "TL1HM8UUU",
                "is_bot": True,
            },
        ],
        channel_members=[
            {"id": "U123"},
            {"id": "UPIOTR"},
            {"id": "UBOT"},
        ],
    )
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)

    asyncio.run(
        meeting_automation.handler(
            _input(
                "private-ai",
                slack_channel_id="C0BM12ZNSTT",
                slack_conversation_kind="mpim",
            ),
            FakeContext(),
        )
    )

    assert [call[2] for call in client.calls if call[0] == "drive_share"] == [
        "requester@world.org",
        "piotr.piwowarczyk@world.org",
    ]
    assert ("channel_members", "C0BM12ZNSTT") in client.calls


def test_public_mpim_uses_triggering_group_before_configured_channel(monkeypatch):
    client = FakeClient(
        [
            {
                "id": "public-ai",
                "title": "Weekly Sync",
                "visibility": "public",
                "notifyChannel": "C0B5Y44QRED",
                "notificationRecipients": ["UPIOTR"],
            }
        ],
        run_result={
            "meetingId": "public-ai",
            "docUrl": "https://docs.google.com/document/d/doc-1/edit",
        },
        slack_users=[
            {
                "id": "U123",
                "email": "requester@world.org",
                "team_id": "TL1HM8UUU",
                "is_bot": False,
            },
            {
                "id": "UPIOTR",
                "email": "piotr.piwowarczyk@world.org",
                "team_id": "TL1HM8UUU",
                "is_bot": False,
            },
        ],
        channel_members=[{"id": "U123"}, {"id": "UPIOTR"}],
    )
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)

    asyncio.run(
        meeting_automation.handler(
            _input(
                "public-ai",
                requester_slack_email="requester@world.org",
                slack_channel_id="C0BM12ZNSTT",
                slack_conversation_kind="mpim",
            ),
            FakeContext(),
        )
    )

    assert [call[2] for call in client.calls if call[0] == "drive_share"] == [
        "requester@world.org",
        "piotr.piwowarczyk@world.org",
    ]
    assert ("channel_members", "C0BM12ZNSTT") in client.calls
    assert ("channel_members", "C0B5Y44QRED") not in client.calls


def test_mpim_missing_scope_falls_back_to_requester_and_configured_recipient(
    monkeypatch,
):
    client = MissingMpimScopeClient(
        [
            {
                "id": "public-ai",
                "title": "Weekly Sync",
                "visibility": "public",
                "notifyChannel": "C0B5Y44QRED",
                "notificationRecipients": ["UPIOTR"],
            }
        ],
        run_result={
            "meetingId": "public-ai",
            "docUrl": "https://docs.google.com/document/d/doc-1/edit",
        },
        slack_users=[
            {
                "id": "U123",
                "email": "requester@world.org",
                "team_id": "TL1HM8UUU",
                "is_bot": False,
            },
            {
                "id": "UPIOTR",
                "email": "piotr.piwowarczyk@world.org",
                "team_id": "TL1HM8UUU",
                "is_bot": False,
            },
        ],
    )
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)

    asyncio.run(
        meeting_automation.handler(
            _input(
                "public-ai",
                requester_slack_email="requester@world.org",
                slack_channel_id="C0BM12ZNSTT",
                slack_conversation_kind="mpim",
            ),
            FakeContext(),
        )
    )

    assert [call[2] for call in client.calls if call[0] == "drive_share"] == [
        "requester@world.org",
        "piotr.piwowarczyk@world.org",
    ]


def test_private_one_to_one_dm_grants_requester_editor_access(monkeypatch):
    client = FakeClient(
        [{"id": "private-ai", "title": "AI Workstream", "visibility": "private"}],
        run_result={
            "meetingId": "private-ai",
            "docUrl": "https://docs.google.com/document/d/doc-1/edit",
        },
    )
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)

    asyncio.run(meeting_automation.handler(_input("private-ai"), FakeContext()))

    run_call = next(call for call in client.calls if call[0] == "run_cadence")
    assert "document_editor_emails" not in run_call[2]
    assert ("drive_share", "doc-1", "piotr.piwowarczyk@world.org") in client.calls


def test_unverified_editor_grant_prevents_success_delivery(monkeypatch):
    client = UnverifiedDriveClient(
        [{"id": "private-ai", "title": "AI Workstream", "visibility": "private"}],
        run_result={
            "meetingId": "private-ai",
            "docUrl": "https://docs.google.com/document/d/doc-1/edit",
        },
    )
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)
    context = FakeContext()

    with pytest.raises(ValueError, match="did not verify Editor access"):
        asyncio.run(meeting_automation.handler(_input("private-ai"), context))

    assert context.posts == []


def test_manual_private_delivery_rejects_malformed_acknowledgement(monkeypatch):
    client = MalformedAcknowledgementClient(
        [{"id": "private-ai", "title": "AI Workstream", "visibility": "private"}],
        run_result={
            "meetingId": "private-ai",
            "docUrl": "https://docs.google.com/document/d/doc-1/edit",
        },
        notifications=[
            {
                "notificationId": "agenda:private-ai:2026-08-10:U123",
                "meetingId": "private-ai",
                "visibility": "private",
                "recipientSlackUserId": "U123",
                "text": "Agenda ready",
            }
        ],
    )
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)

    with pytest.raises(ValueError, match="was not acknowledged"):
        asyncio.run(meeting_automation.handler(_input("private-ai"), FakeContext()))


def test_private_cadence_propagates_custom_instructions(monkeypatch):
    client = FakeClient(
        [{"id": "private-ai", "title": "AI Workstream", "visibility": "private"}],
        run_result={
            "meetingId": "private-ai",
            "docUrl": "https://docs.google.com/document/d/doc-1/edit",
        },
    )
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)

    asyncio.run(
        meeting_automation.handler(
            _input("private-ai", custom_instructions="focus on decisions"),
            FakeContext(),
        )
    )

    run_call = next(call for call in client.calls if call[0] == "run_cadence")
    assert run_call == (
        "run_cadence",
        "private-ai",
        {
            "custom_instructions": "focus on decisions",
            "requester_slack_team_id": "TL1HM8UUU",
            "requester_slack_user_id": "U123",
        },
    )


def test_public_cadence_posts_one_mrkdwn_notification_to_configured_channel(
    monkeypatch,
):
    client = FakeClient(
        [
            {
                "id": "public-ai",
                "title": "AI Workstream Weekly",
                "visibility": "public",
                "notifyChannel": "C0B5Y44QRED",
                "notifyChannelName": "#ai-agents",
            }
        ],
        run_result={
            "meetingId": "public-ai",
            "docUrl": "https://docs.google.com/document/d/doc-2/edit",
        },
        notifications=[
            {
                "notificationId": "agenda:public-ai:2026-08-10:channel",
                "meetingId": "public-ai",
                "visibility": "public",
                "channelId": "C0B5Y44QRED",
                "recipientSlackUserId": None,
                "docUrl": "https://docs/doc-2",
                "occurrenceAt": "2026-08-10T08:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)
    context = FakeContext()

    result = asyncio.run(meeting_automation.handler(_input("workstream"), context))

    assert result["visibility"] == "public"
    assert client.sent[0][0] == "C0B5Y44QRED"
    assert "<https://docs/doc-2|Open document>" in client.sent[0][1]
    assert context.posts == [
        (
            "D123456",
            "Meeting automation complete for *AI Workstream Weekly*.\nDocument: <https://docs.google.com/document/d/doc-2/edit|Open document>",
        )
    ]
    assert [call[0] for call in client.calls] == [
        "authorized_cadences",
        "slack_users",
        "channel_members",
        "run_cadence",
        "drive_permissions",
        "drive_share",
        "drive_permissions",
        "pending_all",
        "send",
        "ack_all",
    ]
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

    result = asyncio.run(
        meeting_automation.handler(_input("secret leadership"), context)
    )

    assert result["status"] == "rejected"
    assert [call[0] for call in client.calls] == ["authorized_cadences"]
    assert context.posts == [
        (
            "D123456",
            "I couldn't find one cadence you are allowed to run with that name. "
            + "Use its exact cadence ID or title and try again.",
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
            "Meeting automation ran for *AI Workstream*, but no document was created.",
        )
    ]


def test_input_requires_world_team_and_slack_conversation():
    with pytest.raises(ValueError, match="World Slack team"):
        meeting_automation._validate_input(_input(requester_slack_team_id="TOTHER"))
    meeting_automation._validate_input(
        _input(slack_channel_id="C123456", slack_conversation_kind="mpim")
    )
    meeting_automation._validate_input(_input(slack_channel_id="G123456"))
    with pytest.raises(ValueError, match="Slack conversation"):
        meeting_automation._validate_input(_input(slack_channel_id="X123456"))


def test_input_rejects_oversized_or_control_character_instructions():
    with pytest.raises(ValueError, match="custom_instructions"):
        meeting_automation._validate_input(
            _input(
                custom_instructions="x"
                * (meeting_automation.MAX_CUSTOM_INSTRUCTIONS_CHARS + 1)
            )
        )
    with pytest.raises(ValueError, match="custom_instructions"):
        meeting_automation._validate_input(_input(custom_instructions="focus\x07"))


def _published_row(**overrides):
    row = {
        "id": "notion-page-1",
        "Ritual": "Weekly Sync",
        "Automation ID": "weekly-sync",
        "Automation status": "Published",
        "Frequency": "Weekly",
        "Next date": "2026-08-17",
        "Time zone": "Europe/Prague",
        "Meeting time": "10:00",
        "Notification time": "09:15",
        "Preparation lead (business days)": 1,
        "Owner / DRI": '["user://owner-1"]',
        "Notification emails": "",
        "Google template URL": "template-1",
        "Google output folder URL": "folder-1",
        "Slack channel ID": "C069VHQEJEQ",
        "Slack channel name": "#wf-all",
        "Participants": "Everyone",
    }
    row.update(overrides)
    return row


def _notion_users():
    return [{"id": "owner-1", "person": {"email": "mandy.payne@world.org"}}]


def _slack_users():
    return [
        {
            "id": "U0BEQ8M7QSK",
            "email": "mandy.payne@world.org",
            "team_id": "TL1HM8UUU",
            "is_bot": False,
            "deleted": False,
        }
    ]


def test_notion_cadence_uses_friday_for_a_one_business_day_monday_prep():
    cadence = meeting_automation.normalize_notion_cadence(
        _published_row(), _notion_users(), _slack_users()
    )

    assert cadence["_preparation_at"].isoformat() == "2026-08-14T09:15:00+02:00"
    assert cadence["_occurrence_local"].isoformat() == "2026-08-17T10:00:00+02:00"
    assert cadence["notificationRecipients"] == ["U0BEQ8M7QSK"]


def test_public_notion_cadence_resolves_channel_members_for_doc_editors():
    members = [
        *_slack_users(),
        {
            "id": "UBOT",
            "email": "orbie@world.org",
            "team_id": "TL1HM8UUU",
            "is_bot": True,
        },
    ]
    cadence = meeting_automation.normalize_notion_cadence(
        _published_row(), _notion_users(), _slack_users(), members
    )

    assert cadence["documentEditorEmails"] == ["mandy.payne@world.org"]


def test_all_world_access_includes_only_active_world_humans():
    users = [
        *_slack_users(),
        {"id": "UDC", "email": "dc.builder@world.org", "team_id": "TL1HM8UUU"},
        {
            "id": "UBOT",
            "email": "bot@world.org",
            "team_id": "TL1HM8UUU",
            "is_bot": True,
        },
        {
            "id": "UDELETED",
            "email": "old@world.org",
            "team_id": "TL1HM8UUU",
            "deleted": True,
        },
        {"id": "UEXTERNAL", "email": "person@example.org", "team_id": "TL1HM8UUU"},
    ]
    cadence = meeting_automation.normalize_notion_cadence(
        _published_row(**{"Document access": "All World members"}),
        _notion_users(),
        users,
        users,
    )

    assert cadence["documentEditorEmails"] == [
        "mandy.payne@world.org",
        "dc.builder@world.org",
    ]


def test_notion_cadence_reads_next_date_from_data_source_sql_shape():
    row = _published_row()
    row.pop("Next date")
    row["date:Next date:start"] = "2026-08-17"

    cadence = meeting_automation.normalize_notion_cadence(
        row, _notion_users(), _slack_users()
    )

    assert cadence["_occurrence_local"].date() == dt.date(2026, 8, 17)
    assert cadence["_date_only"] is True


def test_notion_cadence_uses_thursday_for_a_two_business_day_monday_prep():
    cadence = meeting_automation.normalize_notion_cadence(
        _published_row(**{"Preparation lead (business days)": 2}),
        _notion_users(),
        _slack_users(),
    )

    assert cadence["_preparation_at"].isoformat() == "2026-08-13T09:15:00+02:00"


def test_notion_cadence_rejects_missing_or_ambiguous_exact_slack_email_match():
    with pytest.raises(ValueError, match="exactly one active user"):
        meeting_automation.normalize_notion_cadence(
            _published_row(**{"Notification emails": "missing@world.org"}),
            _notion_users(),
            _slack_users(),
        )


def test_public_channel_cadence_can_omit_recipients():
    cadence = meeting_automation.normalize_notion_cadence(
        _published_row(
            **{
                "Owner / DRI": "",
                "Notification recipients": "",
                "Notification emails": "",
            }
        ),
        [],
        _slack_users(),
        _slack_users(),
    )

    assert cadence["visibility"] == "public"
    assert cadence["notificationRecipients"] == []
    assert cadence["ownerSlackUserId"] is None

    ambiguous = [
        *_slack_users(),
        {
            "id": "UOTHER",
            "email": "mandy.payne@world.org",
            "team_id": "TL1HM8UUU",
            "is_bot": False,
            "deleted": False,
        },
    ]
    with pytest.raises(ValueError, match="exactly one active user"):
        meeting_automation.normalize_notion_cadence(
            _published_row(), _notion_users(), ambiguous
        )


def test_private_cadence_can_target_a_private_slack_channel():
    cadence = meeting_automation.normalize_notion_cadence(
        _published_row(
            **{
                "Document access": "Cadence members",
                "Slack channel ID": "G123456",
                "Slack channel name": "private-sync",
            }
        ),
        _notion_users(),
        _slack_users(),
        _slack_users(),
    )

    assert cadence["visibility"] == "private"
    assert cadence["notifyChannel"] == "G123456"
    assert cadence["documentEditorEmails"] == ["mandy.payne@world.org"]


def test_private_cadence_requires_an_explicit_owner():
    with pytest.raises(ValueError, match="Owner / DRI"):
        meeting_automation.normalize_notion_cadence(
            _published_row(
                **{
                    "Slack channel ID": "",
                    "Slack channel name": "",
                    "Owner / DRI": "",
                    "Notification emails": "mandy.payne@world.org",
                }
            ),
            _notion_users(),
            _slack_users(),
        )


def test_notion_cadence_uses_calendar_month_and_quarter_recurrence():
    monthly = meeting_automation.normalize_notion_cadence(
        _published_row(
            **{
                "Frequency": "Monthly",
                "Next date": "2026-01-31",
            }
        ),
        _notion_users(),
        _slack_users(),
    )
    quarterly = meeting_automation.normalize_notion_cadence(
        _published_row(
            **{
                "Frequency": "Quarterly",
                "Next date": "2026-01-31",
            }
        ),
        _notion_users(),
        _slack_users(),
    )

    assert meeting_automation._next_occurrence(
        monthly["_occurrence_local"], "monthly"
    ).date() == dt.date(2026, 2, 28)
    assert meeting_automation._next_occurrence(
        meeting_automation._next_occurrence(monthly["_occurrence_local"], "monthly"),
        "monthly",
    ).date() == dt.date(2026, 3, 31)
    assert meeting_automation._next_occurrence(
        quarterly["_occurrence_local"], "quarterly"
    ).date() == dt.date(2026, 4, 30)
    assert meeting_automation._next_occurrence(
        meeting_automation._next_occurrence(
            quarterly["_occurrence_local"], "quarterly"
        ),
        "quarterly",
    ).date() == dt.date(2026, 7, 31)


class ScheduledFakeClient:
    def __init__(self, row, notion_users=None, slack_users=None):
        self.row = row
        self.notion_user_data = notion_users or _notion_users()
        self.slack_user_data = slack_users or _slack_users()
        self.notifications = []
        self.sent = []
        self.advanced = []
        self.drive_permissions = []
        self.bookings = []
        self.booking_updates = []

    async def notion_cadences(self):
        return [self.row]

    async def notion_users(self):
        return self.notion_user_data

    async def slack_users(self):
        return self.slack_user_data

    async def slack_channel_members(self, channel_id):
        return self.slack_user_data

    async def run_scheduled_cadence(self, cadence, occurrence_at, **_kwargs):
        recipients = (
            cadence["notificationRecipients"]
            if cadence["visibility"] == "private"
            else [None]
        )
        self.notifications = [
            {
                "notificationId": f"agenda:weekly-sync:2026-08-17:{recipient or 'channel'}",
                "kind": "agenda",
                "meetingId": cadence["id"],
                "visibility": cadence["visibility"],
                "channelId": cadence["notifyChannel"],
                "recipientSlackUserId": recipient,
                "docUrl": "https://docs.google.com/document/d/weekly-sync-2026-08-17/edit",
                "occurrenceAt": occurrence_at,
            }
            for recipient in recipients
        ]
        return {
            "meetingId": cadence["id"],
            "docUrl": "https://docs.google.com/document/d/weekly-sync-2026-08-17/edit",
            "occurrenceAt": occurrence_at,
        }

    async def book_scheduled_meeting(self, cadence, occurrence_at):
        self.bookings.append((cadence["id"], occurrence_at))
        return {
            "status": "booked",
            "actualStart": "2026-08-17T08:00:00+00:00",
            "zoomJoinUrl": "https://zoom.us/j/123",
        }

    async def run_scheduled_notifications(self, cadence, **_kwargs):
        return {"status": "notifications-processed", "meetingId": cadence["id"]}

    async def pending_notifications(self):
        return self.notifications

    async def acknowledge_notification_unscoped(self, notification_id):
        self.notifications = [
            item
            for item in self.notifications
            if item["notificationId"] != notification_id
        ]
        return {"acknowledged": True, "notificationId": notification_id}

    async def send_slack_message(self, channel, text, **kwargs):
        self.sent.append(("channel", channel, text, kwargs))
        return {"sent": True, "ts": "1785153461.533159"}

    async def send_slack_dm(self, user_id, text, **kwargs):
        self.sent.append(("dm", user_id, text, kwargs))
        return {"sent": True, "ts": "1785153461.533159"}

    async def update_notion_next_date(self, page_id, next_date_start, **_kwargs):
        self.advanced.append((page_id, next_date_start))
        return {"id": page_id}

    async def update_notion_booking(self, page_id, status, **kwargs):
        self.booking_updates.append((page_id, status, kwargs))
        return {"id": page_id}

    async def share_drive_file(self, file_id, email):
        self.drive_permissions.append({"email": email, "role": "writer"})
        return {"email": email, "role": "writer"}

    async def drive_file_permissions(self, file_id):
        return list(self.drive_permissions)


class ManualNotionFakeClient(FakeClient):
    def __init__(self, row):
        super().__init__(
            [],
            run_result={
                "meetingId": "orbie-weekly-sync-spotlight-demo",
                "docUrl": "https://docs.google.com/document/d/spotlight-doc/edit",
            },
            slack_users=[
                {"id": "UDC", "email": "dc.builder@world.org", "team_id": "TL1HM8UUU"},
                {
                    "id": "UPIOTR",
                    "email": "piotr.piwowarczyk@world.org",
                    "team_id": "TL1HM8UUU",
                },
            ],
        )
        self.row = row

    async def notion_cadences(self):
        return [self.row]

    async def notion_users(self):
        return [{"id": "owner-dc", "person": {"email": "dc.builder@world.org"}}]


def test_manual_run_resolves_owner_scoped_draft_notion_cadence(monkeypatch):
    row = _published_row(
        **{
            "Ritual": "Weekly Sync Spotlight Demo",
            "Automation ID": "orbie-weekly-sync-spotlight-demo",
            "Automation status": "Draft",
            "Owner / DRI": '["user://owner-dc"]',
            "Notification recipients": "",
            "Document access": "All World members",
        }
    )
    client = ManualNotionFakeClient(row)
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)

    result = asyncio.run(
        meeting_automation.handler(
            _input(
                "Weekly Sync Spotlight Demo",
                requester_slack_user_id="UDC",
                requester_slack_email="dc.builder@world.org",
            ),
            FakeContext(),
        )
    )

    scheduled_call = next(
        call for call in client.calls if call[0] == "run_scheduled_cadence"
    )
    assert scheduled_call[1]["id"] == "orbie-weekly-sync-spotlight-demo"
    assert result["verified_editors"] == [
        "dc.builder@world.org",
        "piotr.piwowarczyk@world.org",
    ]


def test_scheduled_handler_delivers_channel_message_and_advances_notion_date(
    monkeypatch,
):
    client = ScheduledFakeClient(_published_row())
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)
    result = asyncio.run(
        meeting_automation.handler(
            meeting_automation.Input(
                now="2026-08-14T07:15:00Z",
                metadata={"source": "workflow_schedule"},
            ),
            FakeContext(),
        )
    )

    assert result["due"] == ["weekly-sync"]
    assert client.sent[0][0:2] == ("channel", "C069VHQEJEQ")
    assert "newly created document from the template" in client.sent[0][2]
    assert "<@U0BEQ8M7QSK>" in client.sent[0][2]
    assert client.advanced == [("notion-page-1", "2026-08-24")]


def test_auto_book_scheduled_handler_books_before_docs_and_uses_actual_time(
    monkeypatch,
):
    row = _published_row(
        **{
            "Calendar booking": "Auto-book",
            "Organizer calendar": "wf-main",
            "Booking window (business days)": 1,
            "Duration (min)": 45,
            "Participants": "mandy.payne@world.org",
        }
    )
    client = ScheduledFakeClient(row)
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)

    result = asyncio.run(
        meeting_automation.handler(
            meeting_automation.Input(
                now="2026-08-14T07:15:00Z",
                metadata={"source": "workflow_schedule"},
            ),
            FakeContext(),
        )
    )

    assert client.bookings == [("weekly-sync", "2026-08-17T08:00:00+00:00")]
    assert client.booking_updates == [
        (
            "notion-page-1",
            "Booked",
            {
                "booked_start": "2026-08-17T08:00:00+00:00",
                "meeting_url": "https://zoom.us/j/123",
            },
        )
    ]
    run = result["runs"][0]
    assert run["occurrence_at"] == "2026-08-17T08:00:00+00:00"
    assert client.advanced == [("notion-page-1", "2026-08-24")]
    assert "https://zoom.us/j/123" in client.sent[0][2]


class BookingFailureClient(ScheduledFakeClient):
    async def book_scheduled_meeting(self, _cadence, _occurrence_at):
        raise RuntimeError("provider detail must not be sent to Slack")


def test_auto_book_failure_blocks_notion_and_does_not_advance_next_date(monkeypatch):
    row = _published_row(
        **{
            "Calendar booking": "Auto-book",
            "Organizer calendar": "wf-main",
            "Booking window (business days)": 1,
            "Duration (min)": 45,
            "Participants": "mandy.payne@world.org",
        }
    )
    client = BookingFailureClient(row)
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)

    with pytest.raises(RuntimeError, match="provider detail"):
        asyncio.run(
            meeting_automation.handler(
                meeting_automation.Input(
                    now="2026-08-14T07:15:00Z",
                    metadata={"source": "workflow_schedule"},
                ),
                FakeContext(),
            )
        )

    assert client.booking_updates == [("notion-page-1", "Blocked", {})]
    assert client.advanced == []
    assert len(client.sent) == 1
    assert "provider detail" not in client.sent[0][2]
    assert "Next date was not advanced" in client.sent[0][2]


def test_scheduled_handler_sends_one_dm_per_private_recipient(monkeypatch):
    row = _published_row(
        **{
            "Slack channel ID": "",
            "Slack channel name": "",
            "Notification emails": "mandy.payne@world.org,piotr.piwowarczyk@world.org",
        }
    )
    client = ScheduledFakeClient(
        row,
        slack_users=[
            *_slack_users(),
            {
                "id": "U0B0P93D63Z",
                "email": "piotr.piwowarczyk@world.org",
                "team_id": "TL1HM8UUU",
                "is_bot": False,
                "deleted": False,
            },
        ],
    )
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)

    asyncio.run(
        meeting_automation.handler(
            meeting_automation.Input(
                now="2026-08-14T07:15:00Z",
                metadata={"source": "workflow_schedule"},
            ),
            FakeContext(),
        )
    )

    assert [(item[0], item[1]) for item in client.sent] == [
        ("dm", "U0BEQ8M7QSK"),
        ("dm", "U0B0P93D63Z"),
    ]
    assert len({item[3]["client_msg_id"] for item in client.sent}) == 2


def test_scheduled_handler_rejects_private_outbox_items_with_channel_destinations(
    monkeypatch,
):
    client = ScheduledFakeClient(
        _published_row(
            **{
                "Slack channel ID": "",
                "Slack channel name": "",
            }
        )
    )
    client.notifications = [
        {
            "notificationId": "agenda:weekly-sync:2026-08-17:U0BEQ8M7QSK",
            "kind": "agenda",
            "meetingId": "weekly-sync",
            "visibility": "private",
            "channelId": "C069VHQEJEQ",
            "recipientSlackUserId": "U0BEQ8M7QSK",
            "docUrl": "https://docs.example/weekly-sync-2026-08-17",
            "occurrenceAt": "2026-08-17T08:00:00Z",
        }
    ]
    monkeypatch.setattr(meeting_automation, "_client", lambda _ctx: client)

    with pytest.raises(ValueError, match="private scheduled notification"):
        asyncio.run(
            meeting_automation.handler(
                meeting_automation.Input(
                    now="2026-08-13T07:15:00Z",
                    metadata={"source": "workflow_schedule"},
                ),
                FakeContext(),
            )
        )
