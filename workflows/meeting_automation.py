"""Run an owner-scoped Meeting Ops cadence from an authenticated Slack surface."""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from api.workflow_engine import WorkflowContext

WORKFLOW_NAME = "meeting_automation"
WORKFLOW_PRINCIPAL = True
WORLD_SLACK_TEAM_ID = "TL1HM8UUU"
MEETING_OPS_TOOL = "meeting-ops"
MEETING_SCHEDULER_TOOL = "meeting-scheduler"
MAX_CUSTOM_INSTRUCTIONS_CHARS = 4000
CADENCES_DATABASE_ID = "cbdf28b9-3bc7-474c-85ed-9b323eb09889"
PRIVATE_CADENCE_TEMPLATE_MARKER = "ORBiE_PRIVATE_CADENCE_TEMPLATE_V1"
DEFAULT_CADENCE_TIME_ZONE = "Europe/Prague"
DEFAULT_MEETING_TIME = "10:00"
DEFAULT_NOTIFICATION_TIME = "09:15"
DEFAULT_PREPARATION_BUSINESS_DAYS = 1
EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
MANUAL_ORGANIZER_CALENDAR_KEY = "MEETING_MANUAL_ORGANIZER_CALENDAR_KEY"


def _env_value(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_flag(name: str, default: bool = False) -> bool:
    value = _env_value(name, "")
    if not value.strip():
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_positive_int(name: str, default: int) -> int:
    try:
        value = int(_env_value(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# The durable runtime wakes this workflow often enough to honor each cadence's
# local notification time. The workflow itself decides which rows are due.
# Keep this as a durable cron schedule so the control plane owns the tick and
# can replay it after a restart; the cadence rows still carry the business-time
# calculation for preparation and delivery.
SCHEDULE = {
    "schedule_id": "meeting_automation_scheduler",
    "cron": _env_value("MEETING_OPS_SCHEDULER_CRON", "*/15 * * * *"),
    "enabled": _env_flag("MEETING_OPS_SCHEDULER_ENABLED", default=False),
    "timezone": "UTC",
    "no_delivery": True,
}


def _tool_output(result: Any) -> Any:
    """Unwrap workflow bridge and MCP-compatible result envelopes."""

    value = result
    for _ in range(6):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return value
            continue
        if not isinstance(value, dict):
            return value
        if "output" in value and (
            "tool" in value
            or "method" in value
            or set(value).issubset({"output", "ok", "status"})
        ):
            value = value["output"]
            continue
        if "data" in value and set(value).issubset({"data", "ok", "status"}):
            value = value["data"]
            continue
        if "structuredContent" in value:
            value = value["structuredContent"]
            continue
        if set(value).issubset({"result", "ok", "status"}) and "result" in value:
            value = value["result"]
            continue
        content = value.get("content")
        if isinstance(content, list) and len(content) == 1:
            block = content[0]
            if (
                isinstance(block, dict)
                and block.get("type") == "text"
                and "text" in block
            ):
                value = block["text"]
                continue
        return value
    return value


@dataclass
class Input:
    cadence_query: str = ""
    requester_identity: str = ""
    requester_slack_user_id: str = ""
    requester_slack_team_id: str = ""
    slack_channel_id: str = ""
    slack_conversation_kind: str = ""
    request_message_id: str = ""
    slack_thread_ts: str | None = None
    requester_slack_email: str | None = None
    custom_instructions: str | None = None
    now: str | None = None
    scheduling_operation: str = ""
    scheduling_args: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class MeetingOpsClient(Protocol):
    async def authorized_cadences(
        self,
        requester_slack_user_id: str,
        requester_slack_team_id: str,
    ) -> list[dict[str, Any]]: ...

    async def run_cadence(
        self,
        cadence_id: str,
        *,
        requester_slack_user_id: str,
        requester_slack_team_id: str,
        custom_instructions: str | None = None,
        document_editor_emails: list[str] | None = None,
    ) -> dict[str, Any] | None: ...

    async def pending_notifications_for_caller(
        self,
        requester_slack_user_id: str,
        requester_slack_team_id: str,
    ) -> list[dict[str, Any]]: ...

    async def acknowledge_notification(
        self,
        notification_id: str,
        *,
        requester_slack_user_id: str,
        requester_slack_team_id: str,
    ) -> dict[str, Any]: ...

    async def run_scheduled_cadence(
        self,
        cadence: dict[str, Any],
        occurrence_at: str,
        *,
        now: str,
        requester_slack_team_id: str,
        requester_slack_user_id: str | None = None,
    ) -> dict[str, Any] | None: ...

    async def run_scheduled_notifications(
        self,
        cadence: dict[str, Any],
        *,
        now: str,
        requester_slack_team_id: str,
    ) -> dict[str, Any] | None: ...

    async def book_scheduled_meeting(
        self, cadence: dict[str, Any], occurrence_at: str
    ) -> dict[str, Any]: ...

    async def scheduling_operation(
        self, operation: str, args: dict[str, Any]
    ) -> Any: ...

    async def pending_notifications(self) -> list[dict[str, Any]]: ...

    async def acknowledge_notification_unscoped(
        self, notification_id: str
    ) -> dict[str, Any]: ...

    async def notion_cadences(self) -> list[dict[str, Any]]: ...

    async def notion_users(self) -> list[dict[str, Any]]: ...

    async def slack_users(self) -> list[dict[str, Any]]: ...

    async def slack_channel_members(self, channel_id: str) -> list[dict[str, Any]]: ...

    async def send_slack_message(
        self, channel: str, text: str, *, client_msg_id: str
    ) -> dict[str, Any]: ...

    async def send_slack_dm(
        self, user_id: str, text: str, *, client_msg_id: str
    ) -> dict[str, Any]: ...

    async def update_notion_next_date(
        self,
        page_id: str,
        next_date_start: str,
        expected_current_start: str | None = None,
    ) -> dict[str, Any]: ...

    async def update_notion_booking(
        self,
        page_id: str,
        status: str,
        *,
        booked_start: str | None = None,
        meeting_url: str | None = None,
        clear_booking: bool = False,
    ) -> dict[str, Any]: ...

    async def publish_notion_meeting_summary(
        self,
        page_id: str,
        *,
        occurrence_key: str,
        title: str,
        start: str,
        summary: str,
        transcript: str,
    ) -> dict[str, Any]: ...

    async def share_drive_file(self, file_id: str, email: str) -> dict[str, Any]: ...

    async def drive_file_permissions(self, file_id: str) -> list[dict[str, Any]]: ...


class MeetingOpsToolClient:
    """Adapter for the workflow principal's caller-scoped tool methods."""

    def __init__(self, ctx: WorkflowContext) -> None:
        self._ctx = ctx

    async def authorized_cadences(
        self, user_id: str, team_id: str
    ) -> list[dict[str, Any]]:
        result = await self._ctx.call_tool(
            MEETING_OPS_TOOL,
            "authorized_cadences",
            {
                "requester_slack_user_id": user_id,
                "requester_slack_team_id": team_id,
            },
        )
        output = _tool_output(result)
        return (
            [item for item in output if isinstance(item, dict)]
            if isinstance(output, list)
            else []
        )

    async def run_cadence(
        self,
        cadence_id: str,
        *,
        requester_slack_user_id: str,
        requester_slack_team_id: str,
        custom_instructions: str | None = None,
        document_editor_emails: list[str] | None = None,
    ) -> dict[str, Any] | None:
        arguments: dict[str, str] = {
            "cadence_id": cadence_id,
            "requester_slack_user_id": requester_slack_user_id,
            "requester_slack_team_id": requester_slack_team_id,
        }
        if custom_instructions:
            arguments["custom_instructions"] = custom_instructions
        if document_editor_emails:
            arguments["document_editor_emails"] = document_editor_emails
        result = await self._ctx.call_tool(
            MEETING_OPS_TOOL,
            "run_cadence",
            arguments,
        )
        output = _tool_output(result)
        return output if isinstance(output, dict) else None

    async def pending_notifications_for_caller(
        self,
        user_id: str,
        team_id: str,
    ) -> list[dict[str, Any]]:
        result = await self._ctx.call_tool(
            MEETING_OPS_TOOL,
            "pending_notifications_for_caller",
            {
                "requester_slack_user_id": user_id,
                "requester_slack_team_id": team_id,
            },
        )
        output = _tool_output(result)
        return (
            [item for item in output if isinstance(item, dict)]
            if isinstance(output, list)
            else []
        )

    async def acknowledge_notification(
        self,
        notification_id: str,
        *,
        requester_slack_user_id: str,
        requester_slack_team_id: str,
    ) -> dict[str, Any]:
        result = await self._ctx.call_tool(
            MEETING_OPS_TOOL,
            "acknowledge_notification",
            {
                "notification_id": notification_id,
                "requester_slack_user_id": requester_slack_user_id,
                "requester_slack_team_id": requester_slack_team_id,
            },
        )
        output = _tool_output(result)
        return output if isinstance(output, dict) else {}

    async def run_scheduled_cadence(
        self,
        cadence: dict[str, Any],
        occurrence_at: str,
        *,
        now: str,
        requester_slack_team_id: str,
        requester_slack_user_id: str | None = None,
    ) -> dict[str, Any] | None:
        arguments: dict[str, Any] = {
            "cadence": cadence,
            "occurrence_at": occurrence_at,
            "now": now,
            "requester_slack_team_id": requester_slack_team_id,
        }
        if requester_slack_user_id:
            arguments["requester_slack_user_id"] = requester_slack_user_id
        result = await self._ctx.call_tool(
            MEETING_OPS_TOOL,
            "run_scheduled_cadence",
            arguments,
        )
        output = _tool_output(result)
        return output if isinstance(output, dict) else None

    async def run_scheduled_notifications(
        self,
        cadence: dict[str, Any],
        *,
        now: str,
        requester_slack_team_id: str,
    ) -> dict[str, Any] | None:
        result = await self._ctx.call_tool(
            MEETING_OPS_TOOL,
            "run_scheduled_notifications",
            {
                "cadence": cadence,
                "now": now,
                "requester_slack_team_id": requester_slack_team_id,
            },
        )
        output = _tool_output(result)
        return output if isinstance(output, dict) else None

    async def book_scheduled_meeting(
        self, cadence: dict[str, Any], occurrence_at: str
    ) -> dict[str, Any]:
        occurrence_key = f"{cadence['id']}:{cadence['_meeting_date']}"
        current = _tool_output(
            await self._ctx.call_tool(
                MEETING_SCHEDULER_TOOL,
                "get_or_reconcile_meeting",
                {"occurrence_key": occurrence_key},
            )
        )
        if isinstance(current, dict) and current.get("status") in {
            "completed",
            "cancelled",
        }:
            return current
        # Always send the desired cadence state through book_meeting. The
        # scheduler owns the occurrence lock and turns this into a no-op when
        # unchanged, or updates the existing Zoom/Calendar pair when a
        # published cadence changed before this occurrence started.
        result = await self._ctx.call_tool(
            MEETING_SCHEDULER_TOOL,
            "book_meeting",
            {
                "occurrence_key": occurrence_key,
                "request_id": occurrence_key,
                "cadence_id": str(cadence["id"]),
                "title": str(cadence["title"]),
                "start": occurrence_at,
                "duration_minutes": int(cadence["durationMin"]),
                "time_zone": str(cadence["timeZone"]),
                "attendee_emails": list(cadence["bookingAttendees"]),
                "organizer_calendar_key": str(cadence["organizerCalendar"]),
                "mode": "cadence",
            },
        )
        output = _tool_output(result)
        if not isinstance(output, dict):
            raise TypeError("meeting scheduler returned an unexpected booking result")
        return output

    async def scheduling_operation(self, operation: str, args: dict[str, Any]) -> Any:
        result = await self._ctx.call_tool(
            MEETING_SCHEDULER_TOOL,
            operation,
            args,
        )
        return _tool_output(result)

    async def pending_notifications(self) -> list[dict[str, Any]]:
        result = await self._ctx.call_tool(
            MEETING_OPS_TOOL, "pending_notifications", {}
        )
        output = _tool_output(result)
        return (
            [item for item in output if isinstance(item, dict)]
            if isinstance(output, list)
            else []
        )

    async def acknowledge_notification_unscoped(
        self, notification_id: str
    ) -> dict[str, Any]:
        result = await self._ctx.call_tool(
            MEETING_OPS_TOOL,
            "acknowledge_notification_unscoped",
            {"notification_id": notification_id},
        )
        output = _tool_output(result)
        return output if isinstance(output, dict) else {}

    async def notion_cadences(self) -> list[dict[str, Any]]:
        databases = await self._paginate_notion(
            "search",
            {"filter_type": "database"},
        )
        database_ids = [CADENCES_DATABASE_ID]
        for database in databases:
            if not isinstance(database, dict):
                continue
            database_id = str(database.get("id") or "").strip()
            if not database_id or database_id in database_ids:
                continue
            title = "".join(
                str(item.get("plain_text") or item.get("text", {}).get("content") or "")
                for item in database.get("title", [])
                if isinstance(item, dict)
            )
            description = "".join(
                str(item.get("plain_text") or item.get("text", {}).get("content") or "")
                for item in database.get("description", [])
                if isinstance(item, dict)
            )
            if (
                "cadence" in title.casefold()
                or PRIVATE_CADENCE_TEMPLATE_MARKER in description
            ):
                database_ids.append(database_id)

        rows: list[dict[str, Any]] = []
        for database_id in database_ids:
            for row in await self._paginate_notion(
                "query_database", {"database_id": database_id}
            ):
                row = dict(row)
                row["_cadence_database_id"] = database_id
                rows.append(row)
        return rows

    async def notion_users(self) -> list[dict[str, Any]]:
        return await self._paginate_notion("users", {})

    async def _paginate_notion(
        self, method: str, base_args: dict[str, Any]
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            args = {**base_args, "page_size": 100}
            if cursor:
                args["start_cursor"] = cursor
            result = await self._ctx.call_tool("notion", method, args)
            output = _tool_output(result)
            if isinstance(output, dict):
                items = output.get("results", [])
                results.extend(item for item in items if isinstance(item, dict))
                if not output.get("has_more"):
                    break
                cursor = str(output.get("next_cursor") or "") or None
                if not cursor:
                    break
                continue
            if isinstance(output, list):
                results.extend(item for item in output if isinstance(item, dict))
            break
        return results

    async def slack_users(self) -> list[dict[str, Any]]:
        # Resolve against the complete paginated workspace list. A small fixed
        # page would make a valid owner appear missing once the workspace grows.
        result = await self._ctx.call_tool("slack", "list_users", {"limit": 10000})
        output = _tool_output(result)
        return (
            [item for item in output if isinstance(item, dict)]
            if isinstance(output, list)
            else []
        )

    async def slack_channel_members(self, channel_id: str) -> list[dict[str, Any]]:
        result = await self._ctx.call_tool(
            "slack", "get_channel_members", {"channel": channel_id}
        )
        output = _tool_output(result)
        return (
            [item for item in output if isinstance(item, dict)]
            if isinstance(output, list)
            else []
        )

    async def send_slack_message(
        self, channel: str, text: str, *, client_msg_id: str
    ) -> dict[str, Any]:
        result = await self._ctx.call_tool(
            "slack",
            "send_message",
            {
                "channel": channel,
                "text": text,
                "no_attribution": True,
                "client_msg_id": client_msg_id,
            },
        )
        output = _tool_output(result)
        return output if isinstance(output, dict) else {}

    async def send_slack_dm(
        self, user_id: str, text: str, *, client_msg_id: str
    ) -> dict[str, Any]:
        result = await self._ctx.call_tool(
            "slack",
            "send_dm",
            {
                "user_id": user_id,
                "text": text,
                "no_attribution": True,
                "client_msg_id": client_msg_id,
            },
        )
        output = _tool_output(result)
        return output if isinstance(output, dict) else {}

    async def update_notion_next_date(
        self,
        page_id: str,
        next_date_start: str,
        expected_current_start: str | None = None,
    ) -> dict[str, Any]:
        if expected_current_start is not None:
            current_result = await self._ctx.call_tool(
                "notion", "page", {"page_id": page_id}
            )
            current_page = _tool_output(current_result)
            current_start = (
                _property_value(current_page, "Next date")
                if isinstance(current_page, dict)
                else None
            )
            if not _same_notion_date_start(current_start, expected_current_start):
                raise ValueError(
                    "cadence Next date changed while the occurrence was running"
                )
        result = await self._ctx.call_tool(
            "notion",
            "update_page",
            {
                "page_id": page_id,
                "properties": {"Next date": {"date": {"start": next_date_start}}},
            },
        )
        output = _tool_output(result)
        return output if isinstance(output, dict) else {}

    async def update_notion_booking(
        self,
        page_id: str,
        status: str,
        *,
        booked_start: str | None = None,
        meeting_url: str | None = None,
        clear_booking: bool = False,
    ) -> dict[str, Any]:
        properties: dict[str, Any] = {"Booking status": {"select": {"name": status}}}
        if clear_booking:
            properties["Booked start"] = {"date": None}
            properties["Booked meeting URL"] = {"url": None}
        elif booked_start:
            properties["Booked start"] = {"date": {"start": booked_start}}
        if not clear_booking and meeting_url:
            properties["Booked meeting URL"] = {"url": meeting_url}
        result = await self._ctx.call_tool(
            "notion", "update_page", {"page_id": page_id, "properties": properties}
        )
        output = _tool_output(result)
        return output if isinstance(output, dict) else {}

    async def publish_notion_meeting_summary(
        self,
        page_id: str,
        *,
        occurrence_key: str,
        title: str,
        start: str,
        summary: str,
        transcript: str,
    ) -> dict[str, Any]:
        marker = f"ORBiE_ZOOM_SUMMARY:{occurrence_key}"
        existing = await self._paginate_notion("block_children", {"block_id": page_id})
        if any(marker in _notion_block_text(block) for block in existing):
            return {"page_id": page_id, "marker": marker, "created": False}
        children = [
            _notion_heading(f"{title} — {start}", 2),
            _notion_paragraph(marker),
            _notion_heading("Zoom summary", 3),
            *_notion_paragraph_chunks(summary or "Zoom summary was not available."),
            _notion_heading("Transcript", 3),
            *_notion_paragraph_chunks(transcript or "Transcript was not available."),
        ]
        result = await self._ctx.call_tool(
            "notion",
            "append_block_children",
            {"block_id": page_id, "children": children[:100]},
        )
        output = _tool_output(result)
        if not isinstance(output, dict):
            raise TypeError("Notion meeting publication returned an unexpected result")
        return {"page_id": page_id, "marker": marker, "created": True}

    async def share_drive_file(self, file_id: str, email: str) -> dict[str, Any]:
        result = await self._ctx.call_tool(
            "gsuite",
            "drive_share",
            {
                "file_id": file_id,
                "email": email,
                "role": "writer",
                "send_notification": False,
            },
        )
        output = _tool_output(result)
        return output if isinstance(output, dict) else {}

    async def drive_file_permissions(self, file_id: str) -> list[dict[str, Any]]:
        result = await self._ctx.call_tool(
            "gsuite", "drive_list_permissions", {"file_id": file_id}
        )
        output = _tool_output(result)
        return (
            [item for item in output if isinstance(item, dict)]
            if isinstance(output, list)
            else []
        )


def _client(ctx: WorkflowContext) -> MeetingOpsClient:
    return MeetingOpsToolClient(ctx)


def _is_scheduled(inp: Input) -> bool:
    return inp.metadata.get("source") == "workflow_schedule"


def _parse_now(value: str | None) -> dt.datetime:
    if not value:
        return dt.datetime.now(dt.UTC)
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def _property_value(row: dict[str, Any], name: str) -> Any:
    """Read both the REST page-property shape and query-SQL shape."""

    if name in row and row[name] is not None:
        return row[name]
    # Notion data-source SQL expands date properties into queryable columns,
    # e.g. `date:Next date:start`, instead of returning a `Next date` value.
    # Keep the scheduler tolerant of both the SQL row and REST page shapes.
    if name == "Next date":
        expanded_date = row.get("date:Next date:start")
        if expanded_date is not None:
            return expanded_date
    prop = (row.get("properties") or {}).get(name)
    if not isinstance(prop, dict):
        return None
    prop_type = prop.get("type")
    if prop_type == "title":
        return "".join(
            str(item.get("plain_text") or item.get("text", {}).get("content") or "")
            for item in prop.get("title", [])
        )
    if prop_type in {"rich_text", "text"}:
        return "".join(
            str(item.get("plain_text") or item.get("text", {}).get("content") or "")
            for item in prop.get("rich_text", prop.get("text", []))
        )
    if prop_type in {"select", "status"}:
        selected = prop.get(prop_type)
        return selected.get("name") if isinstance(selected, dict) else selected
    if prop_type == "number":
        return prop.get("number")
    if prop_type == "url":
        return prop.get("url")
    if prop_type == "date":
        date = prop.get("date") or {}
        return date.get("start")
    if prop_type == "people":
        return prop.get("people", [])
    return prop.get(prop_type)


def _same_notion_date_start(left: Any, right: Any) -> bool:
    """Compare Notion date values without confusing offsets or date-only rows."""

    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return left_text == right_text
    if left_text == right_text:
        return True
    try:
        left_value = dt.datetime.fromisoformat(left_text.replace("Z", "+00:00"))
        right_value = dt.datetime.fromisoformat(right_text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if left_value.tzinfo is None:
        left_value = left_value.replace(tzinfo=dt.UTC)
    if right_value.tzinfo is None:
        right_value = right_value.replace(tzinfo=dt.UTC)
    return left_value.astimezone(dt.UTC) == right_value.astimezone(dt.UTC)


def _notion_block_text(block: dict[str, Any]) -> str:
    block_type = str(block.get("type") or "")
    payload = block.get(block_type)
    rich_text = payload.get("rich_text") if isinstance(payload, dict) else None
    if not isinstance(rich_text, list):
        return ""
    return "".join(
        str(item.get("plain_text") or item.get("text", {}).get("content") or "")
        for item in rich_text
        if isinstance(item, dict)
    )


def _notion_rich_text(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": text}}]


def _notion_paragraph(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _notion_rich_text(text)},
    }


def _notion_heading(text: str, level: int) -> dict[str, Any]:
    kind = f"heading_{level}"
    return {
        "object": "block",
        "type": kind,
        kind: {"rich_text": _notion_rich_text(text)},
    }


def _notion_paragraph_chunks(text: str, size: int = 1800) -> list[dict[str, Any]]:
    normalized = str(text or "").strip()
    return [
        _notion_paragraph(normalized[offset : offset + size])
        for offset in range(0, len(normalized), size)
    ] or [_notion_paragraph("")]


def _as_bool(value: Any) -> bool:
    return value in (True, 1, "1", "true", "True", "yes", "YES", "__YES__")


def _person_refs(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [
                item.strip() for item in re.split(r"[,\n;]", value) if item.strip()
            ]
    if not isinstance(value, list):
        value = [value]
    refs: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, str):
            refs.append({"id": item, "email": ""})
            continue
        if not isinstance(item, dict):
            continue
        person = item.get("person") or {}
        refs.append(
            {
                "id": str(item.get("id") or item.get("user", {}).get("id") or ""),
                "email": str(item.get("email") or person.get("email") or ""),
            }
        )
    return [ref for ref in refs if ref["id"] or ref["email"]]


def _identity_key(value: str) -> str:
    return value.strip().lower().replace("user://", "").replace("-", "")


def _notion_user_emails(users: list[dict[str, Any]]) -> dict[str, str]:
    emails: dict[str, str] = {}
    for user in users:
        person = user.get("person") or {}
        email = str(person.get("email") or user.get("email") or "").strip().lower()
        user_id = str(user.get("id") or "")
        if email and user_id:
            emails[_identity_key(user_id)] = email
            emails[_identity_key("user://" + user_id)] = email
    return emails


def _email_list(value: Any) -> list[str]:
    if not value:
        return []
    return [
        item.strip().lower() for item in re.split(r"[,\n;]", str(value)) if item.strip()
    ]


def _resolve_slack_users(
    refs: list[dict[str, str]],
    raw_emails: list[str],
    notion_users: list[dict[str, Any]],
    slack_users: list[dict[str, Any]],
) -> list[str]:
    notion_emails = _notion_user_emails(notion_users)
    emails: list[str] = []
    for ref in refs:
        email = ref["email"].strip().lower() or notion_emails.get(
            _identity_key(ref["id"]), ""
        )
        if not email:
            raise ValueError("Notion recipient has no email address")
        emails.append(email)
    emails.extend(raw_emails)
    unique_emails = list(dict.fromkeys(emails))
    resolved: list[str] = []
    for email in unique_emails:
        matches = [
            user
            for user in slack_users
            if str(user.get("email") or "").strip().lower() == email
            and not user.get("deleted")
            and not user.get("is_deleted")
            and not user.get("is_bot")
            and user.get("team_id") == WORLD_SLACK_TEAM_ID
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Slack email match for {email} must resolve to exactly one active user"
            )
        user_id = str(matches[0].get("id") or "").strip()
        if not user_id:
            raise ValueError(f"Slack match for {email} has no user ID")
        resolved.append(user_id)
    return list(dict.fromkeys(resolved))


def _channel_editor_emails(
    channel_members: list[dict[str, Any]],
    slack_users: list[dict[str, Any]],
) -> list[str]:
    """Resolve every active human World member of a channel to an editor email."""

    if not channel_members:
        raise ValueError("Slack channel membership could not be resolved")
    users_by_id = {
        str(user.get("id") or ""): user
        for user in slack_users
        if str(user.get("id") or "")
    }
    emails: list[str] = []
    for member in channel_members:
        member_id = str(member.get("id") or "").strip()
        user = users_by_id.get(member_id, {}).copy()
        user.update(
            {key: value for key, value in member.items() if value not in (None, "")}
        )
        if user.get("deleted") or user.get("is_deleted") or user.get("is_bot"):
            continue
        if str(user.get("team_id") or "").strip() != WORLD_SLACK_TEAM_ID:
            continue
        email = str(user.get("email") or "").strip().lower()
        if not email:
            raise ValueError(
                f"Slack channel member {member_id or 'unknown'} has no email"
            )
        emails.append(email)
    if not emails:
        raise ValueError("Slack channel has no active World human members")
    return list(dict.fromkeys(emails))


def _fallback_mpim_editor_emails(
    cadence: dict[str, Any],
    slack_users: list[dict[str, Any]],
    requester_slack_user_id: str,
    requester_slack_email: str | None,
) -> list[str]:
    """Share with the trusted MPIM requester and configured cadence owners.

    Slack's ``conversations.members`` endpoint requires ``mpim:read``. Until
    that scope is installed, the Slack ingress only admits explicitly
    allowlisted MPIMs, so this narrow fallback covers the manual Piotr test
    without granting the document to an arbitrary workspace audience. It is
    intentionally not used for scheduled runs or ordinary channels.
    """

    users_by_id = {
        str(user.get("id") or ""): user
        for user in slack_users
        if str(user.get("id") or "")
    }
    recipient_ids: list[str] = [requester_slack_user_id]
    recipient_ids.extend(
        str(user_id).strip()
        for key in ("ownerSlackUserId", "notificationRecipients")
        for user_id in (
            cadence.get(key)
            if isinstance(cadence.get(key), list)
            else [cadence.get(key)]
        )
        if str(user_id or "").strip()
    )

    emails: list[str] = []
    if requester_slack_email:
        emails.append(requester_slack_email.strip().lower())
    for user_id in dict.fromkeys(recipient_ids):
        user = users_by_id.get(user_id, {})
        if user.get("deleted") or user.get("is_deleted") or user.get("is_bot"):
            continue
        if str(user.get("team_id") or "").strip() != WORLD_SLACK_TEAM_ID:
            continue
        email = str(user.get("email") or "").strip().lower()
        if email:
            emails.append(email)

    emails = list(dict.fromkeys(email for email in emails if email))
    if not emails:
        raise ValueError("trusted MPIM fallback has no active World human members")
    return emails


def _all_world_editor_emails(slack_users: list[dict[str, Any]]) -> list[str]:
    """Return every active, human Slack user with an exact World email domain."""

    emails = [
        str(user.get("email") or "").strip().lower()
        for user in slack_users
        if not user.get("deleted")
        and not user.get("is_deleted")
        and not user.get("is_bot")
        and str(user.get("team_id") or "").strip() == WORLD_SLACK_TEAM_ID
        and str(user.get("email") or "").strip().lower().endswith("@world.org")
    ]
    if not emails:
        raise ValueError("Slack workspace has no active @world.org human members")
    return list(dict.fromkeys(emails))


def _emails_for_slack_ids(
    user_ids: list[str], slack_users: list[dict[str, Any]]
) -> list[str]:
    users_by_id = {
        str(user.get("id") or "").strip(): user
        for user in slack_users
        if str(user.get("id") or "").strip()
    }
    emails: list[str] = []
    for user_id in dict.fromkeys(user_ids):
        user = users_by_id.get(user_id, {})
        if user.get("deleted") or user.get("is_deleted") or user.get("is_bot"):
            continue
        if str(user.get("team_id") or "").strip() != WORLD_SLACK_TEAM_ID:
            continue
        email = str(user.get("email") or "").strip().lower()
        if not email:
            raise ValueError(f"Slack cadence member {user_id} has no email")
        emails.append(email)
    return list(dict.fromkeys(emails))


def _slack_ids_for_emails(
    emails: list[str], slack_users: list[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    by_email = {
        str(user.get("email") or "").strip().lower(): str(user.get("id") or "").strip()
        for user in slack_users
        if not user.get("deleted")
        and not user.get("is_deleted")
        and not user.get("is_bot")
        and str(user.get("team_id") or "").strip() == WORLD_SLACK_TEAM_ID
    }
    resolved: list[str] = []
    unresolved: list[str] = []
    for email in dict.fromkeys(
        str(value).strip().lower() for value in emails if str(value).strip()
    ):
        user_id = by_email.get(email, "")
        (resolved if user_id else unresolved).append(user_id or email)
    return list(dict.fromkeys(resolved)), unresolved


def _post_meeting_message(
    title: str, summary: str, transcript: str, notion_url: str = ""
) -> str:
    parts = [
        f"📝 *{title} — meeting follow-up*",
        summary or "Zoom summary was not available.",
    ]
    if notion_url:
        parts.append(f"Canonical notes and transcript: <{notion_url}|Notion>")
    elif transcript:
        excerpt = transcript[:2400]
        suffix = "\n…" if len(transcript) > len(excerpt) else ""
        parts.append(f"*Transcript*\n```{excerpt}{suffix}```")
    return "\n\n".join(parts)[:3900]


def _cadence_member_editor_emails(
    owner_ids: list[str],
    recipient_ids: list[str],
    attendees: list[str],
    slack_users: list[dict[str, Any]],
) -> list[str]:
    emails = _emails_for_slack_ids(owner_ids + recipient_ids, slack_users)
    for attendee in attendees:
        email = attendee.strip().lower()
        if re.fullmatch(r"[^@\s]+@world\.org", email):
            emails.append(email)
    return list(dict.fromkeys(emails))


def _document_id(result: dict[str, Any] | None) -> str:
    if not result:
        raise ValueError("cadence run returned no document")
    direct = str(result.get("docId") or "").strip()
    if direct:
        return direct
    url = str(result.get("docUrl") or "").strip()
    match = re.search(r"/document/d/([A-Za-z0-9_-]+)", url)
    if not match:
        raise ValueError("cadence run returned no Google document ID")
    return match.group(1)


async def _ensure_document_editors(
    ctx: WorkflowContext,
    client: MeetingOpsClient,
    *,
    step_prefix: str,
    run_result: dict[str, Any] | None,
    emails: list[str],
) -> list[str]:
    """Grant and verify writer access through Orbie's authenticated GSuite tool."""

    # Shared Drives report members who can edit content as ``fileOrganizer``
    # (Content manager) or ``organizer`` (Manager), rather than ``writer``.
    # All four roles below have sufficient access to edit a Google document.
    editor_roles = {"writer", "fileOrganizer", "organizer", "owner"}

    requested = list(
        dict.fromkeys(email.strip().lower() for email in emails if email.strip())
    )
    if not requested:
        raise ValueError("cadence has no document editors")
    file_id = _document_id(run_result)
    before = await ctx.step(
        f"{step_prefix}:list_drive_permissions:before",
        lambda: client.drive_file_permissions(file_id),
    )
    writers = {
        str(permission.get("email") or permission.get("emailAddress") or "")
        .strip()
        .lower()
        for permission in before
        if str(permission.get("role") or "").strip() in editor_roles
    }
    writer_domains = {
        str(permission.get("domain") or "").strip().lower()
        for permission in before
        if str(permission.get("role") or "").strip() in editor_roles
        and str(permission.get("type") or "").strip() == "domain"
    }
    for email in requested:
        email_domain = email.rsplit("@", 1)[-1] if "@" in email else ""
        if email in writers or email_domain in writer_domains:
            continue
        await ctx.step(
            f"{step_prefix}:share_drive_file:{email}",
            lambda email=email: client.share_drive_file(file_id, email),
        )
    after = await ctx.step(
        f"{step_prefix}:list_drive_permissions:after",
        lambda: client.drive_file_permissions(file_id),
    )
    verified = {
        str(permission.get("email") or permission.get("emailAddress") or "")
        .strip()
        .lower()
        for permission in after
        if str(permission.get("role") or "").strip() in editor_roles
    }
    verified_domains = {
        str(permission.get("domain") or "").strip().lower()
        for permission in after
        if str(permission.get("role") or "").strip() in editor_roles
        and str(permission.get("type") or "").strip() == "domain"
    }
    missing = [
        email
        for email in requested
        if email not in verified
        and (email.rsplit("@", 1)[-1] if "@" in email else "") not in verified_domains
    ]
    if missing:
        raise ValueError(
            "GSuite did not verify Editor access for: " + ", ".join(missing)
        )
    return requested


def _is_mpim_membership_scope_error(error: Exception) -> bool:
    message = str(error).lower()
    return "mpim:read" in message or "missing_scope" in message


def _google_id(value: Any, kind: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"published cadence is missing its Google {kind}")
    patterns = {
        "template": r"/document/d/([A-Za-z0-9_-]+)",
        "folder": r"/folders/([A-Za-z0-9_-]+)",
    }
    match = re.search(patterns[kind], raw)
    if match:
        return match.group(1)
    if raw.startswith("http"):
        raise ValueError(f"published cadence has an unrecognized Google {kind} URL")
    return raw


def _parse_clock(value: Any, default: str) -> dt.time:
    raw = str(value or default).strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        raise ValueError(f"invalid time {raw!r}; expected HH:mm")
    return dt.time(int(match.group(1)), int(match.group(2)))


def _default_doc_name_template(title: str, frequency: str) -> str:
    """Return the human-facing default for legacy rows without a template."""

    if frequency == "weekly" and re.search(
        r"\bweekly\b.*\ball\s+hands\b|\ball\s+hands\b.*\bweekly\b",
        title,
        re.IGNORECASE,
    ):
        return f"CW{{week}} {title}"
    return f"{title} — {{YYYY-MM-DD}}"


def _zone(name: Any) -> ZoneInfo:
    zone_name = str(name or DEFAULT_CADENCE_TIME_ZONE).strip()
    try:
        return ZoneInfo(zone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown cadence time zone {zone_name!r}") from exc


def _parse_occurrence(
    value: Any, zone: ZoneInfo, meeting_time: dt.time
) -> tuple[dt.datetime, bool]:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("published cadence is missing Next date")
    date_only = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw))
    parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00").replace(" ", "T"))
    if date_only or (
        parsed.time() == dt.time(0, 0) and "T" not in raw and " " not in raw
    ):
        parsed = dt.datetime.combine(parsed.date(), meeting_time)
    parsed = (
        parsed.replace(tzinfo=zone)
        if parsed.tzinfo is None
        else parsed.astimezone(zone)
    )
    return parsed, date_only


def _business_days_before(value: dt.date, days: int) -> dt.date:
    if days < 0:
        raise ValueError("Preparation lead (business days) cannot be negative")
    result = value
    remaining = days
    while remaining:
        result -= dt.timedelta(days=1)
        if result.weekday() < 5:
            remaining -= 1
    return result


def _next_occurrence(value: dt.datetime, frequency: str) -> dt.datetime:
    if frequency == "weekly":
        return value + dt.timedelta(days=7)
    if frequency == "bi-weekly":
        return value + dt.timedelta(days=14)
    months = 3 if frequency == "quarterly" else 1
    day = value.day
    month_end_anchor = day == calendar.monthrange(value.year, value.month)[1]
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    target_last_day = calendar.monthrange(year, month)[1]
    return value.replace(
        year=year,
        month=month,
        day=target_last_day if month_end_anchor else min(day, target_last_day),
    )


def _resolve_booking_attendees(
    value: Any,
    slack_users: list[dict[str, Any]],
) -> list[str]:
    """Resolve Auto-book participants to one active World Slack identity."""

    if isinstance(value, (list, tuple)):
        raw = [str(item).strip().lower() for item in value if str(item).strip()]
    else:
        raw = [
            item.strip().lower()
            for item in re.split(r"[,\n;]", str(value or ""))
            if item.strip()
        ]
    if not raw:
        raise ValueError("Auto-book cadences require Participants")
    attendees: list[str] = []
    for email in raw:
        if not EMAIL_RE.fullmatch(email):
            raise ValueError("Auto-book Participants must be exact email addresses")
        matches = [
            user
            for user in slack_users
            if str(user.get("email") or "").strip().lower() == email
            and user.get("team_id") == WORLD_SLACK_TEAM_ID
            and not user.get("deleted")
            and not user.get("is_deleted")
            and not user.get("is_bot")
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Auto-book participant {email} must resolve to exactly one active World user"
            )
        if email not in attendees:
            attendees.append(email)
    return attendees


def _resolve_requester_calendar_email(
    inp: Input,
    slack_users: list[dict[str, Any]],
) -> str:
    """Resolve the authenticated manual scheduler to one calendar identity."""

    requester_id = str(inp.requester_slack_user_id or "").strip()
    matches = [
        user
        for user in slack_users
        if str(user.get("id") or "").strip() == requester_id
        and str(user.get("team_id") or "").strip() == WORLD_SLACK_TEAM_ID
        and not user.get("deleted")
        and not user.get("is_deleted")
        and not user.get("is_bot")
    ]
    if len(matches) != 1:
        raise ValueError(
            "manual meeting organizer must resolve to exactly one active Slack user"
        )
    email = str(matches[0].get("email") or "").strip().lower()
    if not EMAIL_RE.fullmatch(email):
        raise ValueError("manual meeting organizer has no verified calendar email")
    supplied_email = str(inp.requester_slack_email or "").strip().lower()
    if supplied_email and supplied_email != email:
        raise ValueError(
            "requester Slack email does not match the verified Slack directory"
        )
    return email


def _manual_organizer_calendar_key() -> str:
    key = _env_value(MANUAL_ORGANIZER_CALENDAR_KEY, "").strip()
    if not key:
        raise ValueError(
            f"{MANUAL_ORGANIZER_CALENDAR_KEY} must name a managed organizer calendar"
        )
    return key


def normalize_notion_cadence(
    row: dict[str, Any],
    notion_users: list[dict[str, Any]],
    slack_users: list[dict[str, Any]],
    channel_members: list[dict[str, Any]] | None = None,
    *,
    allow_draft: bool = False,
) -> dict[str, Any]:
    """Convert one Published Cadences row into the worker contract."""

    status = str(_property_value(row, "Automation status") or "").strip()
    allowed_statuses = {"Published", "Draft"} if allow_draft else {"Published"}
    if status not in allowed_statuses:
        raise ValueError("cadence is not available for this workflow")
    title = str(_property_value(row, "Cadence") or "").strip()
    cadence_id = str(
        _property_value(row, "Automation ID") or row.get("id") or ""
    ).strip()
    if not title or not cadence_id:
        raise ValueError("published cadence requires Cadence and Automation ID")
    frequency = str(_property_value(row, "Frequency") or "").strip().lower()
    frequency = frequency.replace(" ", "-")
    if frequency not in {"weekly", "bi-weekly", "monthly", "quarterly"}:
        raise ValueError(f"unsupported cadence frequency {frequency!r}")
    zone = _zone(_property_value(row, "Time zone"))
    meeting_time = _parse_clock(
        _property_value(row, "Meeting time"), DEFAULT_MEETING_TIME
    )
    notification_time = _parse_clock(
        _property_value(row, "Notification time"), DEFAULT_NOTIFICATION_TIME
    )
    occurrence, date_only = _parse_occurrence(
        _property_value(row, "Next date"), zone, meeting_time
    )
    try:
        preparation_days = int(
            _property_value(row, "Preparation lead (business days)")
            or DEFAULT_PREPARATION_BUSINESS_DAYS
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Preparation lead (business days) must be an integer") from exc
    preparation_at = dt.datetime.combine(
        _business_days_before(occurrence.date(), preparation_days),
        notification_time,
        tzinfo=zone,
    )
    calendar_booking = str(_property_value(row, "Calendar booking") or "Off").strip()
    if calendar_booking.casefold() == "auto-book":
        calendar_booking = "Auto-book"
    elif calendar_booking.casefold() == "off":
        calendar_booking = "Off"
    else:
        raise ValueError("Calendar booking must be Off or Auto-book")
    organizer_calendar = str(_property_value(row, "Organizer calendar") or "").strip()
    booking_status = str(_property_value(row, "Booking status") or "Not booked").strip()
    booked_start = _property_value(row, "Booked start")
    booked_meeting_url = str(_property_value(row, "Booked meeting URL") or "").strip()
    booking_window_value = _property_value(row, "Booking window (business days)")
    duration_value = _property_value(row, "Duration (min)")
    booking_attendees: list[str] = []
    booking_at = preparation_at
    if calendar_booking == "Auto-book":
        if not organizer_calendar:
            raise ValueError("Auto-book cadences require an Organizer calendar")
        try:
            booking_window = int(booking_window_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Auto-book cadences require Booking window (business days)"
            ) from exc
        if booking_window <= 0:
            raise ValueError("Booking window (business days) must be positive")
        try:
            duration = int(duration_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Auto-book cadences require Duration (min)") from exc
        if duration <= 0:
            raise ValueError("Auto-book Duration (min) must be positive")
        booking_attendees = _resolve_booking_attendees(
            _property_value(row, "Participants"), slack_users
        )
        booking_at = dt.datetime.combine(
            _business_days_before(occurrence.date(), booking_window),
            notification_time,
            tzinfo=zone,
        )
    owner_refs = _person_refs(_property_value(row, "Owner / DRI"))
    recipient_refs = _person_refs(_property_value(row, "Notification recipients"))
    owner_ids = _resolve_slack_users(
        owner_refs,
        [],
        notion_users,
        slack_users,
    )
    recipient_ids = _resolve_slack_users(
        recipient_refs,
        _email_list(_property_value(row, "Notification emails")),
        notion_users,
        slack_users,
    )
    channel_id = str(_property_value(row, "Slack channel ID") or "").strip()
    channel_name = str(_property_value(row, "Slack channel name") or "").strip()
    if bool(channel_id) != bool(channel_name):
        raise ValueError("Slack channel ID and Slack channel name must be set together")
    access_value = str(_property_value(row, "Document access") or "").strip()
    access_mode = access_value or (
        "All World members" if channel_id.startswith("C") else "Cadence members"
    )
    if access_mode not in {"Cadence members", "All World members"}:
        raise ValueError(f"unsupported Document access mode {access_mode!r}")
    visibility = "private" if access_mode == "Cadence members" else "public"
    if visibility == "private" and not owner_ids:
        raise ValueError("private cadences require an Owner / DRI")
    if channel_id:
        expected_prefix = "G" if visibility == "private" else "C"
        if not channel_id.startswith(expected_prefix):
            raise ValueError(
                f"{visibility} cadence Slack destinations must use a {expected_prefix}... ID"
            )
    resolved_recipient_ids = list(dict.fromkeys(owner_ids + recipient_ids))
    source_doc_id = _google_id(_property_value(row, "Google template URL"), "template")
    output_folder_id = _google_id(
        _property_value(row, "Google output folder URL"), "folder"
    )
    attendees = [
        item.strip()
        for item in re.split(r"[,\n;]", str(_property_value(row, "Participants") or ""))
        if item.strip()
    ]
    if access_mode == "All World members":
        document_editor_emails = _all_world_editor_emails(slack_users)
    elif channel_members is not None and channel_id:
        document_editor_emails = _channel_editor_emails(channel_members, slack_users)
    else:
        document_editor_emails = _cadence_member_editor_emails(
            owner_ids, recipient_ids, attendees, slack_users
        )
    if not document_editor_emails:
        raise ValueError("cadence has no document members with editor access")
    next_date_start = (
        occurrence.isoformat() if not date_only else occurrence.date().isoformat()
    )
    return {
        "id": cadence_id,
        "title": title,
        "sourceDocId": source_doc_id,
        "outputFolderId": output_folder_id,
        "nextOccurrenceAt": occurrence.astimezone(dt.UTC).isoformat(),
        "cadence": frequency,
        "notifyChannel": channel_id or None,
        "notifyChannelName": channel_name or None,
        "notificationRecipients": resolved_recipient_ids,
        "notificationMode": "orbie",
        "visibility": visibility,
        # Public channel cadences may intentionally mention nobody. Private
        # cadences require an explicitly configured Owner / DRI.
        "ownerSlackUserId": owner_ids[0] if owner_ids else None,
        "accessSlackUserIds": owner_ids[1:],
        "documentEditorEmails": document_editor_emails,
        "documentAccess": access_mode,
        "notifyLeadMin": 0,
        "staleWindowMin": 7 * 24 * 60,
        "notesDelayMin": _property_value(row, "Notes delay (min)"),
        "durationMin": _property_value(row, "Duration (min)"),
        "docNameTemplate": _property_value(row, "Document name template")
        or _default_doc_name_template(title, frequency),
        "templateTabName": "Format",
        "notesTabName": "Meeting Notes",
        "attendees": attendees,
        "calendarBooking": calendar_booking,
        "organizerCalendar": organizer_calendar,
        "bookingWindowBusinessDays": booking_window_value,
        "bookingStatus": booking_status,
        "bookedStart": booked_start,
        "bookedMeetingUrl": booked_meeting_url,
        "bookingAttendees": booking_attendees,
        "timeZone": zone.key,
        "status": "active",
        "_page_id": str(row.get("id") or ""),
        "_occurrence_local": occurrence,
        "_preparation_at": preparation_at,
        "_booking_at": booking_at,
        "_next_date_start": next_date_start,
        "_date_only": date_only,
        "_meeting_date": occurrence.date().isoformat(),
    }


def _scheduled_message(cadence: dict[str, Any], notification: dict[str, Any]) -> str:
    title = str(cadence.get("title") or cadence.get("id") or "Meeting")
    date_label = str(
        notification.get("occurrenceAt") or cadence.get("_meeting_date", "")
    )[:10]
    mentions = " ".join(
        f"<@{user_id}>" for user_id in cadence.get("notificationRecipients", [])
    )
    if notification.get("kind") == "notes":
        prefix = f"✅ Notes from {title}"
        request = "Please review the notes and add any follow-up items."
    else:
        prefix = f"📋 *{title}*"
        request = "Please put your update in the newly created document from the template before the meeting."
    doc_url = str(notification.get("docUrl") or "").strip()
    document = f"<{doc_url}|Open document>" if doc_url else "the meeting document"
    parts = [f"{prefix} for {date_label}: {document}", request]
    meeting_url = str(cadence.get("bookedMeetingUrl") or "").strip()
    if meeting_url:
        parts.append(f"Join meeting: <{meeting_url}|World Foundation Zoom>")
    if mentions:
        parts.append(f"Owners: {mentions}")
    return "\n".join(parts)


def _manual_notification_message(notification: dict[str, Any]) -> str:
    """Preserve worker wording while normalizing a document URL for Slack."""

    text = str(notification.get("text") or "").strip()
    doc_url = str(notification.get("docUrl") or "").strip()
    if not text:
        return "Open the meeting document."
    if not doc_url or f"<{doc_url}|" in text:
        return text
    return text.replace(doc_url, f"<{doc_url}|Open document>")


def _notification_client_id(notification_id: str) -> str:
    # Slack accepts this as a client-generated message id. A fixed-length
    # digest keeps it within conservative API limits while retaining stable
    # retry identity for the same outbox item.
    return hashlib.sha256(notification_id.encode("utf-8")).hexdigest()[:32]


def _validated_delivery(result: Any, notification_id: str) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise TypeError(f"Slack delivery for {notification_id} returned no result")
    if not str(result.get("ts") or result.get("timestamp") or "").strip():
        raise ValueError(
            f"Slack delivery for {notification_id} returned no message timestamp"
        )
    return result


def _validated_acknowledgement(result: Any, notification_id: str) -> dict[str, Any]:
    if not isinstance(result, dict) or result.get("acknowledged") is not True:
        raise ValueError(f"notification {notification_id} was not acknowledged")
    if str(result.get("notificationId") or "") != notification_id:
        raise ValueError(f"acknowledgement does not match {notification_id}")
    return result


def _validated_scheduled_run(result: Any, cadence_id: str) -> dict[str, Any]:
    if not isinstance(result, dict) or not str(result.get("docUrl") or "").strip():
        raise ValueError(f"scheduled cadence {cadence_id} returned no document")
    if str(result.get("meetingId") or cadence_id) != cadence_id:
        raise ValueError(f"scheduled cadence result does not match {cadence_id}")
    return result


def _validated_booking(result: Any, cadence_id: str) -> dict[str, Any]:
    if not isinstance(result, dict) or result.get("status") != "booked":
        raise ValueError(
            f"scheduled cadence {cadence_id} did not produce a booked meeting"
        )
    actual_start = str(
        result.get("actualStart") or result.get("actual_start") or ""
    ).strip()
    meeting_url = str(
        result.get("zoomJoinUrl") or result.get("zoom_join_url") or ""
    ).strip()
    if not actual_start or not meeting_url:
        raise ValueError(
            f"scheduled cadence {cadence_id} booking has no actual start or Zoom URL"
        )
    return {**result, "actualStart": actual_start, "zoomJoinUrl": meeting_url}


def _validated_notion_update(result: Any, page_id: str) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise TypeError(f"Notion update for {page_id} returned no result")
    updated_id = str(result.get("id") or result.get("page_id") or "").replace("-", "")
    expected_id = page_id.replace("-", "")
    if updated_id and updated_id != expected_id:
        raise ValueError(f"Notion update returned the wrong page for {page_id}")
    if not updated_id:
        raise ValueError(f"Notion update for {page_id} returned no page ID")
    return result


def _notification_destination(
    cadence: dict[str, Any], notification: dict[str, Any]
) -> tuple[str, str]:
    visibility = str(notification.get("visibility") or "")
    if visibility != cadence.get("visibility"):
        raise ValueError("scheduled notification visibility does not match its cadence")
    channel_id = str(notification.get("channelId") or "").strip()
    recipient_id = str(notification.get("recipientSlackUserId") or "").strip()
    if visibility == "public":
        if not cadence.get("notifyChannel") or not cadence.get("notifyChannelName"):
            raise ValueError(
                "public scheduled cadence has no complete channel destination"
            )
        if not channel_id or channel_id != cadence.get("notifyChannel") or recipient_id:
            raise ValueError("public scheduled notification has an invalid destination")
        return "channel", channel_id
    if visibility == "private":
        if channel_id:
            if channel_id != cadence.get("notifyChannel") or recipient_id:
                raise ValueError(
                    "private scheduled notification has an invalid destination"
                )
            if not channel_id.startswith("G"):
                raise ValueError("private scheduled notification must use a G... ID")
            return "channel", channel_id
        if not recipient_id:
            raise ValueError(
                "private scheduled notification has an invalid destination"
            )
        return "dm", recipient_id
    raise ValueError("scheduled notification has an unsupported visibility")


def _validate_input(inp: Input) -> None:
    if _is_scheduled(inp):
        return
    if inp.requester_slack_team_id != WORLD_SLACK_TEAM_ID:
        raise ValueError("meeting automation is only available to the World Slack team")
    if not inp.slack_channel_id.startswith(("C", "D", "G")):
        raise ValueError("meeting automation requires a Slack conversation ID")
    if (
        not inp.slack_channel_id.startswith("D")
        and not (inp.slack_thread_ts or "").strip()
    ):
        raise ValueError("channel meeting automation requires slack_thread_ts")
    for required_field in (
        "cadence_query",
        "requester_slack_user_id",
        "slack_channel_id",
        "request_message_id",
    ):
        if not getattr(inp, required_field).strip():
            raise ValueError(f"{required_field} is required")
    if inp.custom_instructions is not None:
        if len(inp.custom_instructions) > MAX_CUSTOM_INSTRUCTIONS_CHARS or any(
            (ord(character) < 32 and character not in "\n\r\t")
            or 127 <= ord(character) <= 159
            for character in inp.custom_instructions
        ):
            raise ValueError(
                "custom_instructions must contain at most 4000 printable characters"
            )
        inp.custom_instructions = inp.custom_instructions.strip() or None


SCHEDULING_OPERATIONS = frozenset(
    {
        "find_availability",
        "book_meeting",
        "reschedule_meeting",
        "cancel_meeting",
        "get_or_reconcile_meeting",
    }
)
SCHEDULING_FIELDS = {
    "find_availability": {
        "organizer_calendar_key",
        "attendee_emails",
        "time_min",
        "time_max",
        "duration_minutes",
        "response_timezone",
        "working_start",
        "working_end",
    },
    "book_meeting": {
        "occurrence_key",
        "title",
        "start",
        "duration_minutes",
        "time_zone",
        "attendee_emails",
        "organizer_calendar_key",
        "cadence_id",
        "request_id",
        "confirmation_token",
    },
    "reschedule_meeting": {
        "occurrence_key",
        "start",
        "expected_version",
        "organizer_calendar_key",
        "confirmation_token",
    },
    "cancel_meeting": {
        "occurrence_key",
        "organizer_calendar_key",
        "confirmation_token",
    },
    "get_or_reconcile_meeting": {"occurrence_key"},
}


def _scheduling_args(inp: Input) -> tuple[str, dict[str, Any], str]:
    operation = str(inp.scheduling_operation or "").strip()
    if operation not in SCHEDULING_OPERATIONS:
        raise ValueError("unsupported meeting scheduling operation")
    raw = inp.scheduling_args
    if not isinstance(raw, dict):
        raise TypeError("scheduling_args must be an object")
    allowed_fields = SCHEDULING_FIELDS[operation]
    unknown_fields = sorted(set(raw) - allowed_fields)
    if unknown_fields:
        raise ValueError(
            f"{operation} received unsupported arguments: {', '.join(unknown_fields)}"
        )
    args = dict(raw)

    def require(*names: str) -> None:
        missing = [name for name in names if args.get(name) in (None, "", [])]
        if missing:
            raise ValueError(f"{operation} requires {', '.join(missing)}")

    if operation == "find_availability":
        require(
            "attendee_emails",
            "time_min",
            "time_max",
            "duration_minutes",
        )
    elif operation == "book_meeting":
        require(
            "occurrence_key",
            "title",
            "start",
            "duration_minutes",
            "time_zone",
            "attendee_emails",
            "confirmation_token",
        )
        args.setdefault("request_id", args["occurrence_key"])
        args["mode"] = "ad_hoc"
    elif operation == "reschedule_meeting":
        require(
            "occurrence_key",
            "start",
            "expected_version",
            "organizer_calendar_key",
            "confirmation_token",
        )
        args["mode"] = "ad_hoc"
    elif operation == "cancel_meeting":
        require("occurrence_key", "organizer_calendar_key", "confirmation_token")
    else:
        require("occurrence_key")
    request_key = str(
        inp.request_message_id
        or args.get("occurrence_key")
        or hashlib.sha256(
            json.dumps(args, sort_keys=True, default=str).encode()
        ).hexdigest()[:24]
    )
    return operation, args, request_key


def _public_scheduling_result(
    operation: str,
    result: Any,
    args: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise TypeError(f"{operation} returned an invalid scheduler result")
    if operation == "find_availability":
        candidates = result.get("candidates")
        if not isinstance(candidates, list):
            raise ValueError("availability result has no candidate list")
        return {
            "status": str(result.get("status") or "ok"),
            "candidates": [item for item in candidates if isinstance(item, dict)],
            "attendees": list(args.get("attendee_emails") or []),
            "timezone": str(args.get("response_timezone") or DEFAULT_CADENCE_TIME_ZONE),
        }
    if operation in {"book_meeting", "reschedule_meeting"}:
        status = str(result.get("status") or "")
        if status != "booked":
            raise ValueError(f"{operation} did not return a booked meeting")
        actual_start = str(
            result.get("actualStart") or result.get("actual_start") or ""
        ).strip()
        join_url = str(
            result.get("zoomJoinUrl") or result.get("zoom_join_url") or ""
        ).strip()
        if not actual_start or not join_url:
            raise ValueError(f"{operation} returned no booked start or Zoom URL")
        public = {
            "status": status,
            "actualStart": actual_start,
            "zoomJoinUrl": join_url,
        }
        organizer_email = str(
            result.get("organizer_calendar_id")
            or result.get("organizerCalendarId")
            or result.get("organizer_calendar_key")
            or result.get("organizerCalendarKey")
            or ""
        ).strip()
        if organizer_email:
            public["organizerEmail"] = organizer_email
        event_link = str(
            result.get("calendarHtmlLink") or result.get("calendar_html_link") or ""
        ).strip()
        if event_link:
            public["calendarHtmlLink"] = event_link
        return public
    if operation == "cancel_meeting":
        return {"status": str(result.get("status") or "cancelled")}
    return {
        "status": str(result.get("status") or "pending"),
        **{
            key: result[key]
            for key in (
                "occurrenceKey",
                "occurrence_key",
                "version",
                "organizerCalendarKey",
                "organizer_calendar_key",
                "cadenceId",
                "cadence_id",
                "actualStart",
                "zoomJoinUrl",
                "calendarHtmlLink",
                "providerState",
                "cancelConfirmationToken",
            )
            if key in result
        },
    }


def _scheduling_message(operation: str, result: dict[str, Any]) -> str:
    if operation == "find_availability":
        candidates = result.get("candidates") or []
        if not candidates:
            return "I couldn't find a common free/busy slot in that window."
        lines = ["Available meeting slots (timezone shown):"]
        lines.extend(
            f"• {item.get('start')} to {item.get('end')} ({item.get('timezone')})"
            for item in candidates[:10]
        )
        return "\n".join(lines)
    if operation == "cancel_meeting":
        return "The meeting was cancelled in Calendar and Zoom."
    if operation == "get_or_reconcile_meeting":
        return f"Meeting state: {result.get('status', 'pending')}."
    return (
        f"Meeting {result.get('status', 'updated')}.\n"
        f"Start: {result.get('actualStart')}\n"
        f"Join: <{result.get('zoomJoinUrl')}|World Foundation Zoom>"
    )


async def _sync_scheduling_cadence_booking(
    ctx: WorkflowContext,
    client: MeetingOpsClient,
    operation: str,
    result: Any,
    request_key: str,
) -> dict[str, Any] | None:
    """Reflect a one-off provider change in the owning cadence row."""

    if operation not in {"reschedule_meeting", "cancel_meeting"}:
        return None
    if not isinstance(result, dict):
        raise TypeError(f"{operation} returned an invalid scheduler result")
    cadence_id = str(result.get("cadence_id") or "").strip()
    if not cadence_id:
        return None
    rows = await ctx.step(
        f"scheduling:list_notion_cadences:{request_key}",
        lambda: client.notion_cadences(),
    )
    matches = [
        row
        for row in rows
        if str(_property_value(row, "Automation ID") or row.get("id") or "").strip()
        == cadence_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"cadence {cadence_id} could not be uniquely resolved in Notion"
        )
    page_id = str(matches[0].get("id") or "").strip()
    if not page_id:
        raise ValueError(f"cadence {cadence_id} has no Notion page ID")
    if operation == "cancel_meeting":
        updated = await ctx.step(
            f"scheduling:cadence-cancel:{request_key}",
            lambda: client.update_notion_booking(
                page_id,
                "Not booked",
                clear_booking=True,
            ),
        )
    else:
        actual_start = str(
            result.get("actualStart") or result.get("actual_start") or ""
        ).strip()
        meeting_url = str(
            result.get("zoomJoinUrl") or result.get("zoom_join_url") or ""
        ).strip()
        if not actual_start or not meeting_url:
            raise ValueError(f"{operation} returned no booked start or Zoom URL")
        updated = await ctx.step(
            f"scheduling:cadence-reschedule:{request_key}",
            lambda: client.update_notion_booking(
                page_id,
                "Booked",
                booked_start=actual_start,
                meeting_url=meeting_url,
            ),
        )
    return _validated_notion_update(updated, page_id)


async def _authorize_scheduling_cadence_operation(
    ctx: WorkflowContext,
    client: MeetingOpsClient,
    inp: Input,
    operation: str,
    result: dict[str, Any],
    request_key: str,
) -> None:
    """Require a verified caller for provider mutations on cadence meetings."""

    cadence_id = str(result.get("cadence_id") or result.get("cadenceId") or "").strip()
    if not cadence_id:
        # Ad-hoc occurrences have no Notion owner and are protected by their
        # slot/cancellation confirmation token instead.
        return
    requester = str(inp.requester_slack_user_id or "").strip()
    if not requester or inp.requester_slack_team_id != WORLD_SLACK_TEAM_ID:
        raise ValueError(
            "cadence meeting changes require a verified World Slack requester"
        )

    rows = await ctx.step(
        f"scheduling:authorize:list_cadences:{request_key}",
        lambda: client.notion_cadences(),
    )
    matches = [
        row
        for row in rows
        if str(_property_value(row, "Automation ID") or row.get("id") or "").strip()
        == cadence_id
    ]
    if len(matches) != 1:
        raise ValueError("cadence meeting authorization could not resolve its owner")

    notion_users = await ctx.step(
        f"scheduling:authorize:list_notion_users:{request_key}",
        lambda: client.notion_users(),
    )
    slack_users = await ctx.step(
        f"scheduling:authorize:list_slack_users:{request_key}",
        lambda: client.slack_users(),
    )
    row = matches[0]
    owner_ids = _resolve_slack_users(
        _person_refs(_property_value(row, "Owner / DRI")),
        [],
        notion_users,
        slack_users,
    )
    recipient_ids = _resolve_slack_users(
        _person_refs(_property_value(row, "Notification recipients")),
        _email_list(_property_value(row, "Notification emails")),
        notion_users,
        slack_users,
    )
    if requester not in set(owner_ids + recipient_ids):
        raise ValueError("caller is not authorized to change this cadence meeting")


async def _scheduling_handler(inp: Input, ctx: WorkflowContext) -> dict[str, Any]:
    client = _client(ctx)
    operation, args, request_key = _scheduling_args(inp)
    if operation in {"find_availability", "book_meeting"} and args.get("cadence_id"):
        raise ValueError("manual meeting scheduling cannot target a cadence")
    slack_users: list[dict[str, Any]] | None = None
    if "attendee_emails" in args:
        slack_users = await ctx.step(
            f"scheduling:list_slack_users:{request_key}",
            lambda: client.slack_users(),
        )
        args["attendee_emails"] = _resolve_booking_attendees(
            args["attendee_emails"], slack_users
        )
    if operation in {"find_availability", "book_meeting"}:
        if inp.requester_slack_team_id != WORLD_SLACK_TEAM_ID:
            raise ValueError(
                "manual meeting ownership requires a verified World Slack requester"
            )
        if slack_users is None:
            slack_users = await ctx.step(
                f"scheduling:list_slack_users:{request_key}",
                lambda: client.slack_users(),
            )
        # Resolve the authenticated requester even though the managed Orbie
        # calendar owns the event. The caller cannot choose a different
        # organizer through scheduling_args.
        _resolve_requester_calendar_email(inp, slack_users)
        args["organizer_calendar_key"] = _manual_organizer_calendar_key()
    preflight: dict[str, Any] | None = None
    if operation in {
        "reschedule_meeting",
        "cancel_meeting",
        "get_or_reconcile_meeting",
    }:
        preflight_result = await ctx.step(
            f"scheduling:authorize:occurrence:{request_key}",
            lambda: client.scheduling_operation(
                "get_or_reconcile_meeting",
                {"occurrence_key": args["occurrence_key"]},
            ),
        )
        if not isinstance(preflight_result, dict):
            raise TypeError("meeting occurrence lookup returned an invalid result")
        preflight = preflight_result
        await _authorize_scheduling_cadence_operation(
            ctx, client, inp, operation, preflight_result, request_key
        )
    result = (
        preflight
        if operation == "get_or_reconcile_meeting"
        else await ctx.step(
            f"scheduling:{operation}:{request_key}",
            lambda: client.scheduling_operation(operation, args),
        )
    )
    cadence_update = await _sync_scheduling_cadence_booking(
        ctx, client, operation, result, request_key
    )
    public_result = _public_scheduling_result(operation, result, args)
    delivered = None
    if inp.slack_channel_id:
        delivered = await ctx.step(
            f"scheduling:deliver:{request_key}",
            lambda: ctx.post_to_slack(
                inp.slack_channel_id,
                _scheduling_message(operation, public_result),
                **_slack_post_args(inp),
            ),
        )
    return {
        "status": "ok",
        "operation": operation,
        "result": public_result,
        "cadenceUpdate": cadence_update,
        "delivered": delivered,
    }


def _resolve_cadence(cadences: list[dict[str, Any]], query: str) -> dict[str, Any]:
    normalized_query = query.strip()
    exact = [
        cadence
        for cadence in cadences
        if cadence.get("id") == normalized_query
        or cadence.get("title") == normalized_query
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValueError("cadence query is ambiguous")

    folded_query = normalized_query.casefold()
    matches = [
        cadence
        for cadence in cadences
        if folded_query in str(cadence.get("id") or "").casefold()
        or folded_query in str(cadence.get("title") or "").casefold()
    ]
    if len(matches) != 1:
        if not matches:
            raise ValueError("no authorized cadence matched that query")
        raise ValueError("cadence query is ambiguous")
    return matches[0]


def _step_name(prefix: str, request_message_id: str, suffix: str = "") -> str:
    parts = [prefix, request_message_id]
    if suffix:
        parts.append(suffix)
    return ":".join(parts)


def _public_result_message(
    cadence: dict[str, Any], result: dict[str, Any] | None
) -> str:
    title = str(cadence.get("title") or cadence.get("id") or "cadence")
    if result and result.get("docUrl"):
        return (
            f"Meeting automation complete for *{title}*.\n"
            f"Document: <{result['docUrl']}|Open document>"
        )
    return f"Meeting automation ran for *{title}*, but no document was created."


async def _resolve_manual_notion_cadence(
    inp: Input,
    ctx: WorkflowContext,
    client: MeetingOpsClient,
) -> dict[str, Any]:
    """Resolve an owner-scoped Draft/Published Notion cadence for manual use."""

    rows = await ctx.step(
        _step_name("list_manual_notion_cadences", inp.request_message_id),
        lambda: client.notion_cadences(),
    )
    query = inp.cadence_query.strip().casefold()
    matched_rows = [
        row
        for row in rows
        if str(_property_value(row, "Automation status") or "").strip()
        in {"Draft", "Published"}
        and query
        in {
            str(
                _property_value(row, "Automation ID") or row.get("id") or ""
            ).casefold(),
            str(_property_value(row, "Cadence") or "").casefold(),
        }
    ]
    if len(matched_rows) != 1:
        raise ValueError("manual Notion cadence must resolve exactly once")
    notion_users = await ctx.step(
        _step_name("list_manual_notion_users", inp.request_message_id),
        lambda: client.notion_users(),
    )
    slack_users = await ctx.step(
        _step_name("list_manual_slack_users", inp.request_message_id),
        lambda: client.slack_users(),
    )
    candidates: list[dict[str, Any]] = []
    for row in matched_rows:
        row_id = str(_property_value(row, "Automation ID") or row.get("id") or "")
        channel_id = str(_property_value(row, "Slack channel ID") or "").strip()
        members = None
        if (
            channel_id
            and str(_property_value(row, "Document access") or "")
            != "All World members"
        ):
            members = await ctx.step(
                _step_name(
                    "list_manual_channel_members", inp.request_message_id, row_id
                ),
                lambda channel_id=channel_id: client.slack_channel_members(channel_id),
            )
        candidates.append(
            normalize_notion_cadence(
                row,
                notion_users,
                slack_users,
                members,
                allow_draft=True,
            )
        )
    if len(candidates) != 1:
        raise ValueError("manual Notion cadence must resolve exactly once")
    cadence = candidates[0]
    if inp.requester_slack_user_id not in {
        cadence.get("ownerSlackUserId"),
        *cadence.get("accessSlackUserIds", []),
        *cadence.get("notificationRecipients", []),
    }:
        raise ValueError("manual Notion cadence is not owned by or shared with caller")
    cadence["_manual_notion"] = True
    return cadence


async def _scheduled_handler(inp: Input, ctx: WorkflowContext) -> dict[str, Any]:
    client = _client(ctx)
    now = _parse_now(inp.now or inp.metadata.get("scheduled_at"))
    now_iso = now.isoformat()
    rows = await ctx.step(
        "scheduled:list_notion_cadences",
        lambda: client.notion_cadences(),
    )
    notion_users = await ctx.step(
        "scheduled:list_notion_users",
        lambda: client.notion_users(),
    )
    slack_users = await ctx.step(
        "scheduled:list_slack_users",
        lambda: client.slack_users(),
    )
    channel_members_by_id: dict[str, list[dict[str, Any]]] = {}
    cadences: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    for row in rows:
        if str(_property_value(row, "Automation status") or "").strip() != "Published":
            continue
        try:
            channel_id = str(_property_value(row, "Slack channel ID") or "").strip()
            channel_members: list[dict[str, Any]] | None = None
            if channel_id:
                if channel_id not in channel_members_by_id:
                    channel_members_by_id[channel_id] = await ctx.step(
                        f"scheduled:list_channel_members:{channel_id}",
                        lambda channel_id=channel_id: client.slack_channel_members(
                            channel_id
                        ),
                    )
                channel_members = channel_members_by_id[channel_id]
            cadences.append(
                normalize_notion_cadence(
                    row, notion_users, slack_users, channel_members
                )
            )
        except ValueError as error:
            invalid.append(
                {
                    "id": str(
                        _property_value(row, "Automation ID") or row.get("id") or ""
                    ),
                    "reason": str(error),
                }
            )
    by_id = {str(cadence["id"]): cadence for cadence in cadences}
    post_meetings: list[dict[str, Any]] = []
    candidates = await ctx.step(
        f"scheduled:post-meeting-candidates:{now.strftime('%Y%m%d%H%M')}",
        lambda: client.scheduling_operation(
            "post_meeting_candidates", {"now": now_iso, "limit": 25}
        ),
    )
    if not isinstance(candidates, list):
        raise TypeError("meeting scheduler returned invalid post-meeting candidates")
    for candidate in (item for item in candidates if isinstance(item, dict)):
        occurrence_key = str(
            candidate.get("occurrence_key") or candidate.get("occurrenceKey") or ""
        ).strip()
        meeting_id = str(
            candidate.get("zoom_meeting_id") or candidate.get("zoomMeetingId") or ""
        ).strip()
        if not occurrence_key or not meeting_id:
            continue
        artifacts = await ctx.step(
            f"scheduled:post-meeting-artifacts:{occurrence_key}",
            lambda meeting_id=meeting_id: client.scheduling_operation(
                "collect_post_meeting_artifacts", {"meeting_id": meeting_id}
            ),
        )
        if not isinstance(artifacts, dict) or not artifacts.get("ready"):
            post_meetings.append(
                {"occurrence_key": occurrence_key, "status": "processing"}
            )
            continue
        cadence = by_id.get(str(candidate.get("cadence_id") or ""))
        title = str(candidate.get("title") or (cadence or {}).get("title") or "Meeting")
        start = str(
            candidate.get("actual_start") or candidate.get("requested_start") or ""
        )
        summary = str(artifacts.get("summary_text") or "").strip()
        transcript = str(artifacts.get("transcript") or "").strip()
        notion_page_id = str((cadence or {}).get("_page_id") or "")
        notion_url = ""
        if notion_page_id:
            await ctx.step(
                f"scheduled:post-meeting-notion:{occurrence_key}",
                lambda notion_page_id=notion_page_id, occurrence_key=occurrence_key, title=title, start=start, summary=summary, transcript=transcript: (
                    client.publish_notion_meeting_summary(
                        notion_page_id,
                        occurrence_key=occurrence_key,
                        title=title,
                        start=start,
                        summary=summary,
                        transcript=transcript,
                    )
                ),
            )
            notion_url = f"https://www.notion.so/{notion_page_id.replace('-', '')}"
        attendee_ids, unresolved = _slack_ids_for_emails(
            list(candidate.get("attendee_emails") or []), slack_users
        )
        delivered_to: list[str] = []
        message = _post_meeting_message(title, summary, transcript, notion_url)
        for user_id in attendee_ids:
            await ctx.step(
                f"scheduled:post-meeting-dm:{occurrence_key}:{user_id}",
                lambda user_id=user_id, message=message, occurrence_key=occurrence_key: (
                    client.send_slack_dm(
                        user_id,
                        message,
                        client_msg_id=_notification_client_id(
                            f"post-meeting:{occurrence_key}:{user_id}"
                        ),
                    )
                ),
            )
            delivered_to.append(user_id)
        if (
            cadence
            and cadence.get("visibility") == "public"
            and cadence.get("notifyChannel")
        ):
            channel_id = str(cadence["notifyChannel"])
            await ctx.step(
                f"scheduled:post-meeting-channel:{occurrence_key}:{channel_id}",
                lambda channel_id=channel_id, message=message, occurrence_key=occurrence_key: (
                    client.send_slack_message(
                        channel_id,
                        message,
                        client_msg_id=_notification_client_id(
                            f"post-meeting:{occurrence_key}:{channel_id}"
                        ),
                    )
                ),
            )
            delivered_to.append(channel_id)
        marked = await ctx.step(
            f"scheduled:post-meeting-mark:{occurrence_key}",
            lambda occurrence_key=occurrence_key, notion_page_id=notion_page_id, delivered_to=delivered_to: (
                client.scheduling_operation(
                    "mark_post_meeting_delivered",
                    {
                        "occurrence_key": occurrence_key,
                        "notion_page_id": notion_page_id or None,
                        "delivered_to": delivered_to,
                    },
                )
            ),
        )
        post_meetings.append(
            {
                "occurrence_key": occurrence_key,
                "status": "delivered",
                "notion_page_id": notion_page_id or None,
                "delivered_to": delivered_to,
                "unresolved_attendee_emails": unresolved,
                "marked": bool(marked),
            }
        )
    due = [
        cadence
        for cadence in cadences
        if now.astimezone(_zone(cadence["timeZone"])) >= cadence["_booking_at"]
    ]

    maintenance: list[dict[str, Any]] = []
    for cadence in cadences:
        result = await ctx.step(
            f"scheduled:notifications:{cadence['id']}",
            lambda cadence=cadence: client.run_scheduled_notifications(
                {
                    key: value
                    for key, value in cadence.items()
                    if not key.startswith("_")
                },
                now=now_iso,
                requester_slack_team_id=WORLD_SLACK_TEAM_ID,
            ),
        )
        if result:
            maintenance.append({"cadence_id": cadence["id"], "result": result})

    runs: list[dict[str, Any]] = []
    for cadence in due:
        occurrence_at = cadence["_occurrence_local"].astimezone(dt.UTC).isoformat()
        booked: dict[str, Any] | None = None
        booked_occurrence_at = occurrence_at
        page_id = str(cadence.get("_page_id") or "")
        if cadence.get("calendarBooking") == "Auto-book":
            if not page_id:
                raise ValueError(
                    f"scheduled cadence {cadence['id']} has no Notion page id"
                )
            try:
                booked = await ctx.step(
                    f"scheduled:book:{cadence['id']}:{cadence['_meeting_date']}",
                    lambda cadence=cadence, occurrence_at=occurrence_at: (
                        client.book_scheduled_meeting(cadence, occurrence_at)
                    ),
                )
            except Exception:  # noqa: BLE001 - all provider failures share this retry path
                # Keep Next date at the original cadence anchor and make the
                # failure visible without leaking provider error details. The
                # stable Slack client_msg_id makes retries idempotent.
                try:
                    blocked_page = await ctx.step(
                        f"scheduled:booking-blocked:{cadence['id']}:{cadence['_meeting_date']}",
                        lambda page_id=page_id: client.update_notion_booking(
                            page_id, "Blocked"
                        ),
                    )
                    _validated_notion_update(blocked_page, page_id)
                finally:
                    owner_id = str(cadence.get("ownerSlackUserId") or "").strip()
                    channel_id = str(cadence.get("notifyChannel") or "").strip()
                    if not owner_id and not channel_id:
                        raise
                    failure_id = (
                        f"booking-failure:{cadence['id']}:{cadence['_meeting_date']}"
                    )
                    failure_text = (
                        f"⚠️ Calendar/Zoom booking for *{cadence.get('title', cadence['id'])}* "
                        "did not complete. The cadence Next date was not advanced; Orbie will retry "
                        "the same occurrence."
                    )
                    if owner_id:
                        delivery = await ctx.step(
                            f"scheduled:booking-failure-dm:{cadence['id']}:{cadence['_meeting_date']}",
                            lambda owner_id=owner_id, failure_text=failure_text, failure_id=failure_id: (
                                client.send_slack_dm(
                                    owner_id,
                                    failure_text,
                                    client_msg_id=_notification_client_id(failure_id),
                                )
                            ),
                        )
                    else:
                        delivery = await ctx.step(
                            f"scheduled:booking-failure-channel:{cadence['id']}:{cadence['_meeting_date']}",
                            lambda channel_id=channel_id, failure_text=failure_text, failure_id=failure_id: (
                                client.send_slack_message(
                                    channel_id,
                                    failure_text,
                                    client_msg_id=_notification_client_id(failure_id),
                                )
                            ),
                        )
                    _validated_delivery(delivery, failure_id)
                    raise
            booked = _validated_booking(booked, cadence["id"])
            booked_occurrence_at = booked["actualStart"]
            booking_page = await ctx.step(
                f"scheduled:booking-status:{cadence['id']}:{cadence['_meeting_date']}",
                lambda page_id=page_id, booked=booked: client.update_notion_booking(
                    page_id,
                    "Booked",
                    booked_start=booked["actualStart"],
                    meeting_url=booked["zoomJoinUrl"],
                ),
            )
            _validated_notion_update(booking_page, page_id)
            cadence["bookedStart"] = booked["actualStart"]
            cadence["bookedMeetingUrl"] = booked["zoomJoinUrl"]
        result = await ctx.step(
            f"scheduled:run:{cadence['id']}:{cadence['_meeting_date']}",
            lambda cadence=cadence, booked_occurrence_at=booked_occurrence_at: (
                client.run_scheduled_cadence(
                    {
                        key: value
                        for key, value in cadence.items()
                        if not key.startswith("_") and key != "documentEditorEmails"
                    },
                    booked_occurrence_at,
                    now=now_iso,
                    requester_slack_team_id=WORLD_SLACK_TEAM_ID,
                )
            ),
        )
        if result:
            result = _validated_scheduled_run(result, cadence["id"])
            verified_editors = await _ensure_document_editors(
                ctx,
                client,
                step_prefix=f"scheduled:permissions:{cadence['id']}:{cadence['_meeting_date']}",
                run_result=result,
                emails=list(cadence.get("documentEditorEmails") or []),
            )
            runs.append(
                {
                    "cadence_id": cadence["id"],
                    "occurrence_at": booked_occurrence_at,
                    "result": result,
                    "verified_editors": verified_editors,
                    "booking": booked,
                }
            )
        elif booked is not None:
            raise ValueError(f"scheduled cadence {cadence['id']} returned no document")

    pending = await ctx.step(
        "scheduled:list_outbox",
        lambda: client.pending_notifications(),
    )
    delivered: list[dict[str, Any]] = []
    for notification in pending:
        cadence_id = str(notification.get("meetingId") or "")
        cadence = by_id.get(cadence_id)
        if not cadence or notification.get("kind") not in {"agenda", "notes"}:
            continue
        notification_id = str(notification.get("notificationId") or "")
        if not notification_id:
            raise ValueError("scheduled notification has no notificationId")
        text = _scheduled_message(cadence, notification)
        destination_kind, destination = _notification_destination(cadence, notification)
        if destination_kind == "channel":
            delivery = await ctx.step(
                f"scheduled:deliver:{notification_id}",
                lambda destination=destination, text=text, notification_id=notification_id: (
                    client.send_slack_message(
                        destination,
                        text,
                        client_msg_id=_notification_client_id(notification_id),
                    )
                ),
            )
        else:
            delivery = await ctx.step(
                f"scheduled:deliver:{notification_id}",
                lambda destination=destination, text=text, notification_id=notification_id: (
                    client.send_slack_dm(
                        destination,
                        text,
                        client_msg_id=_notification_client_id(notification_id),
                    )
                ),
            )
        delivery = _validated_delivery(delivery, notification_id)
        acknowledged = await ctx.step(
            f"scheduled:ack:{notification_id}",
            lambda notification_id=notification_id: (
                client.acknowledge_notification_unscoped(notification_id)
            ),
        )
        acknowledged = _validated_acknowledgement(acknowledged, notification_id)
        delivered.append(
            {
                "notification": notification,
                "delivery": delivery,
                "acknowledged": acknowledged,
            }
        )

    advanced: list[dict[str, Any]] = []
    for run in runs:
        cadence = by_id[run["cadence_id"]]
        next_occurrence = _next_occurrence(
            cadence["_occurrence_local"], cadence["cadence"]
        )
        next_date_start = (
            next_occurrence.isoformat()
            if not cadence["_date_only"]
            else next_occurrence.date().isoformat()
        )
        page_id = str(cadence.get("_page_id") or "")
        if not page_id:
            raise ValueError(f"scheduled cadence {cadence['id']} has no Notion page id")
        updated = await ctx.step(
            f"scheduled:advance:{cadence['id']}:{cadence['_meeting_date']}",
            lambda page_id=page_id, next_date_start=next_date_start, expected_current_start=cadence["_next_date_start"]: (
                client.update_notion_next_date(
                    page_id,
                    next_date_start,
                    expected_current_start=expected_current_start,
                )
            ),
        )
        updated = _validated_notion_update(updated, page_id)
        advanced.append(
            {
                "cadence_id": cadence["id"],
                "next_date": next_date_start,
                "notion": updated,
            }
        )

    return {
        "status": "scheduled",
        "now": now_iso,
        "due": [cadence["id"] for cadence in due],
        "runs": runs,
        "maintenance": maintenance,
        "delivered": delivered,
        "advanced": advanced,
        "invalid": invalid,
        "post_meetings": post_meetings,
    }


def _slack_post_args(inp: Input) -> dict[str, str]:
    return (
        {}
        if inp.slack_channel_id.startswith("D")
        else {"thread_ts": inp.slack_thread_ts or inp.request_message_id}
    )


async def _post_manual_progress(
    inp: Input, ctx: WorkflowContext, stage: str, text: str
) -> Any:
    """Post an idempotent, predefined status update to the requesting thread."""

    return await ctx.step(
        _step_name("progress", inp.request_message_id, stage),
        lambda: ctx.post_to_slack(
            inp.slack_channel_id,
            text,
            **_slack_post_args(inp),
        ),
    )


async def handler(inp: Input, ctx: WorkflowContext) -> dict[str, Any]:
    if _is_scheduled(inp):
        return await _scheduled_handler(inp, ctx)
    if str(inp.scheduling_operation or "").strip():
        return await _scheduling_handler(inp, ctx)
    _validate_input(inp)
    client = _client(ctx)
    user_id = inp.requester_slack_user_id
    team_id = inp.requester_slack_team_id

    await _post_manual_progress(
        inp,
        ctx,
        "resolving",
        "Resolving the cadence and checking your access…",
    )

    cadences = await ctx.step(
        _step_name("list_authorized_cadences", inp.request_message_id),
        lambda: client.authorized_cadences(user_id, team_id),
    )
    try:
        cadence = _resolve_cadence(cadences, inp.cadence_query)
    except ValueError:
        try:
            cadence = await _resolve_manual_notion_cadence(inp, ctx, client)
        except ValueError:
            rejection = await ctx.step(
                _step_name("reject_cadence", inp.request_message_id),
                lambda: ctx.post_to_slack(
                    inp.slack_channel_id,
                    "I couldn't find one cadence you are allowed to run with that name. "
                    "Use its exact cadence ID or title and try again.",
                    **_slack_post_args(inp),
                ),
            )
            return {
                "status": "rejected",
                "reason": "cadence_not_resolved",
                "delivered": [rejection],
            }
    cadence_id = str(cadence.get("id") or "")
    if not cadence_id:
        raise ValueError("authorized cadence has no id")

    cadence_title = str(cadence.get("title") or cadence_id)
    await _post_manual_progress(
        inp,
        ctx,
        "creating_document",
        f"Cadence found: *{cadence_title}*. Creating or reusing the agenda document…",
    )

    run_arguments: dict[str, Any] = {
        "requester_slack_user_id": user_id,
        "requester_slack_team_id": team_id,
    }
    document_editor_emails: list[str] = []
    editor_channel_id: str | None = None
    if inp.slack_conversation_kind == "mpim":
        # A manual run from a trusted group DM shares with that triggering
        # conversation, even when the cadence also has a public notification
        # channel. Ordinary one-to-one DMs remain caller-scoped.
        editor_channel_id = inp.slack_channel_id
    elif cadence.get("visibility") == "public" and cadence.get("notifyChannel"):
        editor_channel_id = str(cadence["notifyChannel"])
    if editor_channel_id:
        slack_users = await ctx.step(
            _step_name("list_slack_users", inp.request_message_id, cadence_id),
            lambda: client.slack_users(),
        )
        try:
            channel_members = await ctx.step(
                _step_name("list_channel_members", inp.request_message_id, cadence_id),
                lambda: client.slack_channel_members(editor_channel_id),
            )
        except Exception as error:
            if (
                inp.slack_conversation_kind != "mpim"
                or not _is_mpim_membership_scope_error(error)
            ):
                raise
            document_editor_emails = _fallback_mpim_editor_emails(
                cadence,
                slack_users,
                user_id,
                inp.requester_slack_email,
            )
        else:
            document_editor_emails = _channel_editor_emails(
                channel_members, slack_users
            )
    if not document_editor_emails:
        slack_users = await ctx.step(
            _step_name("list_slack_users", inp.request_message_id, cadence_id),
            lambda: client.slack_users(),
        )
        document_editor_emails = _fallback_mpim_editor_emails(
            cadence,
            slack_users,
            user_id,
            inp.requester_slack_email,
        )
    if inp.custom_instructions:
        run_arguments["custom_instructions"] = inp.custom_instructions

    if cadence.get("_manual_notion"):
        occurrence_at = cadence["_occurrence_local"].astimezone(dt.UTC).isoformat()
        run_result = await ctx.step(
            _step_name("run_notion_cadence", inp.request_message_id, cadence_id),
            lambda: client.run_scheduled_cadence(
                {
                    key: value
                    for key, value in cadence.items()
                    if not key.startswith("_") and key != "documentEditorEmails"
                },
                occurrence_at,
                now=_parse_now(inp.now).isoformat(),
                requester_slack_team_id=team_id,
                requester_slack_user_id=user_id,
            ),
        )
        document_editor_emails = list(cadence.get("documentEditorEmails") or [])
    else:
        run_result = await ctx.step(
            _step_name("run_cadence", inp.request_message_id, cadence_id),
            lambda: client.run_cadence(
                cadence_id,
                **run_arguments,
            ),
        )
    await _post_manual_progress(
        inp,
        ctx,
        "verifying_delivery",
        "Document ready. Verifying editor access and sending notifications…",
    )
    verified_editors = (
        await _ensure_document_editors(
            ctx,
            client,
            step_prefix=_step_name(
                "document_permissions", inp.request_message_id, cadence_id
            ),
            run_result=run_result,
            emails=document_editor_emails,
        )
        if run_result and (run_result.get("docId") or run_result.get("docUrl"))
        else []
    )

    if cadence.get("visibility") == "public":
        pending = await ctx.step(
            _step_name("list_public_notifications", inp.request_message_id, cadence_id),
            lambda: client.pending_notifications(),
        )
        public_notifications = [
            notification
            for notification in pending
            if notification.get("meetingId") == cadence_id
            and notification.get("visibility") == "public"
        ]
        delivered: list[Any] = []
        acknowledged: list[dict[str, Any]] = []
        for notification in public_notifications:
            notification_id = str(notification.get("notificationId") or "")
            if not notification_id:
                raise ValueError("public notification has no notificationId")
            text = _scheduled_message(cadence, notification)
            destination_kind, destination = _notification_destination(
                cadence, notification
            )
            if destination_kind != "channel":
                raise ValueError("public manual notification must target a channel")
            delivery = await ctx.step(
                _step_name(
                    "deliver_public_notification",
                    inp.request_message_id,
                    notification_id,
                ),
                lambda destination=destination, text=text, notification_id=notification_id: (
                    client.send_slack_message(
                        destination,
                        text,
                        client_msg_id=_notification_client_id(notification_id),
                    )
                ),
            )
            delivered.append(_validated_delivery(delivery, notification_id))
            acknowledged_result = await ctx.step(
                _step_name(
                    "ack_public_notification", inp.request_message_id, notification_id
                ),
                lambda notification_id=notification_id: (
                    client.acknowledge_notification_unscoped(notification_id)
                ),
            )
            acknowledged.append(
                _validated_acknowledgement(acknowledged_result, notification_id)
            )
        confirmation = await ctx.step(
            _step_name("deliver_public_result", inp.request_message_id, cadence_id),
            lambda: ctx.post_to_slack(
                inp.slack_channel_id,
                _public_result_message(cadence, run_result),
                **_slack_post_args(inp),
            ),
        )
        delivered.append(confirmation)
        return {
            "cadence": {"id": cadence_id, "title": cadence.get("title")},
            "visibility": "public",
            "run": run_result,
            "verified_editors": verified_editors,
            "delivered": delivered,
            "acknowledged": acknowledged,
        }

    pending = await ctx.step(
        _step_name("list_private_notifications", inp.request_message_id, cadence_id),
        lambda: client.pending_notifications_for_caller(user_id, team_id),
    )
    caller_notifications = [
        notification
        for notification in pending
        if notification.get("meetingId") == cadence_id
        and notification.get("visibility") == "private"
        and (
            notification.get("recipientSlackUserId") == user_id
            or (
                notification.get("channelId")
                and notification.get("channelId") == cadence.get("notifyChannel")
            )
        )
    ]
    delivered: list[Any] = []
    acknowledged: list[dict[str, Any]] = []
    for notification in caller_notifications:
        notification_id = str(notification.get("notificationId") or "")
        if not notification_id:
            raise ValueError("private notification has no notificationId")
        delivered_result = await ctx.step(
            _step_name(
                "deliver_private_notification", inp.request_message_id, notification_id
            ),
            lambda notification=notification: ctx.post_to_slack(
                str(notification.get("channelId") or inp.slack_channel_id),
                _manual_notification_message(notification),
                **_slack_post_args(inp),
            ),
        )
        delivered.append(delivered_result)
        acknowledged_result = await ctx.step(
            _step_name(
                "ack_private_notification", inp.request_message_id, notification_id
            ),
            lambda notification_id=notification_id: client.acknowledge_notification(
                notification_id,
                requester_slack_user_id=user_id,
                requester_slack_team_id=team_id,
            ),
        )
        acknowledged.append(
            _validated_acknowledgement(acknowledged_result, notification_id)
        )

    if not caller_notifications:
        delivered.append(
            await ctx.step(
                _step_name("deliver_private_noop", inp.request_message_id, cadence_id),
                lambda: ctx.post_to_slack(
                    inp.slack_channel_id,
                    _public_result_message(cadence, run_result),
                    **_slack_post_args(inp),
                ),
            )
        )

    return {
        "cadence": {"id": cadence_id, "title": cadence.get("title")},
        "visibility": "private",
        "run": run_result,
        "verified_editors": verified_editors,
        "delivered": delivered,
        "acknowledged": acknowledged,
    }
