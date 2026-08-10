"""Run an owner-scoped Meeting Ops cadence from an authenticated Slack DM."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from api.workflow_engine import WorkflowContext

WORKFLOW_NAME = "meeting_automation"
WORKFLOW_PRINCIPAL = True
WORLD_SLACK_TEAM_ID = "TL1HM8UUU"
MEETING_OPS_TOOL = "meeting-ops"


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
            if isinstance(block, dict) and block.get("type") == "text" and "text" in block:
                value = block["text"]
                continue
        return value
    return value


@dataclass
class Input:
    cadence_query: str
    requester_slack_user_id: str
    requester_slack_team_id: str
    slack_channel_id: str
    request_message_id: str
    requester_slack_email: str | None = None


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


class MeetingOpsToolClient:
    """Adapter for the workflow principal's caller-scoped tool methods."""

    def __init__(self, ctx: WorkflowContext) -> None:
        self._ctx = ctx

    async def authorized_cadences(self, user_id: str, team_id: str) -> list[dict[str, Any]]:
        result = await self._ctx.call_tool(
            MEETING_OPS_TOOL,
            "authorized_cadences",
            {
                "requester_slack_user_id": user_id,
                "requester_slack_team_id": team_id,
            },
        )
        output = _tool_output(result)
        return [item for item in output if isinstance(item, dict)] if isinstance(output, list) else []

    async def run_cadence(
        self,
        cadence_id: str,
        *,
        requester_slack_user_id: str,
        requester_slack_team_id: str,
    ) -> dict[str, Any] | None:
        result = await self._ctx.call_tool(
            MEETING_OPS_TOOL,
            "run_cadence",
            {
                "cadence_id": cadence_id,
                "requester_slack_user_id": requester_slack_user_id,
                "requester_slack_team_id": requester_slack_team_id,
            },
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
        return [item for item in output if isinstance(item, dict)] if isinstance(output, list) else []

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


def _client(ctx: WorkflowContext) -> MeetingOpsClient:
    return MeetingOpsToolClient(ctx)


def _validate_input(inp: Input) -> None:
    if inp.requester_slack_team_id != WORLD_SLACK_TEAM_ID:
        raise ValueError("meeting automation is only available to the World Slack team")
    if not inp.slack_channel_id.startswith("D"):
        raise ValueError("meeting automation requires a Slack DM channel")
    for field in (
        "cadence_query",
        "requester_slack_user_id",
        "slack_channel_id",
        "request_message_id",
    ):
        if not getattr(inp, field).strip():
            raise ValueError(f"{field} is required")


def _resolve_cadence(cadences: list[dict[str, Any]], query: str) -> dict[str, Any]:
    normalized_query = query.strip()
    exact = [
        cadence
        for cadence in cadences
        if cadence.get("id") == normalized_query or cadence.get("title") == normalized_query
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


def _public_result_message(cadence: dict[str, Any], result: dict[str, Any] | None) -> str:
    title = str(cadence.get("title") or cadence.get("id") or "cadence")
    if result and result.get("docUrl"):
        return f"Meeting automation complete for *{title}*.\nDocument: {result['docUrl']}"
    return f"Meeting automation ran for *{title}*, but no document was created in the current window."


async def handler(inp: Input, ctx: WorkflowContext) -> dict[str, Any]:
    _validate_input(inp)
    client = _client(ctx)
    user_id = inp.requester_slack_user_id
    team_id = inp.requester_slack_team_id

    cadences = await ctx.step(
        _step_name("list_authorized_cadences", inp.request_message_id),
        lambda: client.authorized_cadences(user_id, team_id),
    )
    try:
        cadence = _resolve_cadence(cadences, inp.cadence_query)
    except ValueError:
        rejection = await ctx.step(
            _step_name("reject_cadence", inp.request_message_id),
            lambda: ctx.post_to_slack(
                inp.slack_channel_id,
                "I couldn't find one cadence you are allowed to run with that name. "
                "Use its exact cadence ID or title and try again.",
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

    run_result = await ctx.step(
        _step_name("run_cadence", inp.request_message_id, cadence_id),
        lambda: client.run_cadence(
            cadence_id,
            requester_slack_user_id=user_id,
            requester_slack_team_id=team_id,
        ),
    )

    if cadence.get("visibility") == "public":
        message = _public_result_message(cadence, run_result)
        slack_result = await ctx.step(
            _step_name("deliver_public_result", inp.request_message_id, cadence_id),
            lambda: ctx.post_to_slack(inp.slack_channel_id, message),
        )
        return {
            "cadence": {"id": cadence_id, "title": cadence.get("title")},
            "visibility": "public",
            "run": run_result,
            "delivered": [slack_result],
            "acknowledged": [],
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
        and notification.get("recipientSlackUserId") == user_id
    ]
    delivered: list[Any] = []
    acknowledged: list[dict[str, Any]] = []
    for notification in caller_notifications:
        notification_id = str(notification.get("notificationId") or "")
        if not notification_id:
            raise ValueError("private notification has no notificationId")
        delivered_result = await ctx.step(
            _step_name("deliver_private_notification", inp.request_message_id, notification_id),
            lambda notification=notification: ctx.post_to_slack(
                inp.slack_channel_id,
                str(notification.get("text") or ""),
            ),
        )
        delivered.append(delivered_result)
        acknowledged.append(
            await ctx.step(
                _step_name("ack_private_notification", inp.request_message_id, notification_id),
                lambda notification_id=notification_id: client.acknowledge_notification(
                    notification_id,
                    requester_slack_user_id=user_id,
                    requester_slack_team_id=team_id,
                ),
            )
        )

    if not caller_notifications:
        delivered.append(
            await ctx.step(
                _step_name("deliver_private_noop", inp.request_message_id, cadence_id),
                lambda: ctx.post_to_slack(
                    inp.slack_channel_id,
                    _public_result_message(cadence, run_result),
                ),
            )
        )

    return {
        "cadence": {"id": cadence_id, "title": cadence.get("title")},
        "visibility": "private",
        "run": run_result,
        "delivered": delivered,
        "acknowledged": acknowledged,
    }
