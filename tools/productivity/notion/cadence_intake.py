"""Pure helpers for the human-facing Orbie cadence intake flow."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_TIME_ZONE = "Europe/Prague"
DEFAULT_MEETING_TIME = "10:00"
DEFAULT_NOTIFICATION_TIME = "09:15"
ALL_HANDS_MEETING_TIME = "16:00"
ALL_HANDS_NOTIFICATION_TIME = "09:00"
ALL_HANDS_CHANNEL_NAME = "#wf-all"

_WEEKLY_ALL_HANDS_RE = re.compile(
    r"\bweekly\b.*\ball\s+hands\b|\ball\s+hands\b.*\bweekly\b", re.I
)
_FREQUENCY_ALIASES = {
    "weekly": "Weekly",
    "biweekly": "Bi-weekly",
    "bi-weekly": "Bi-weekly",
    "monthly": "Monthly",
    "quarterly": "Quarterly",
}


def _required_text(name: str, value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def normalize_frequency(value: str | None) -> str:
    """Normalize the user-facing cadence frequency spelling."""

    raw = str(value or "Weekly").strip().casefold()
    try:
        return _FREQUENCY_ALIASES[raw]
    except KeyError as error:
        raise ValueError(f"unsupported frequency: {value!r}") from error


def _is_known_weekly_all_hands(cadence: str, frequency: str) -> bool:
    return frequency == "Weekly" and bool(_WEEKLY_ALL_HANDS_RE.search(cadence))


def _next_weekly_date(now: datetime, meeting_time: str) -> str:
    """Return the next Monday, advancing a week after today's meeting time."""

    local_date = now.date()
    days_until_monday = (7 - local_date.weekday()) % 7
    candidate = local_date + timedelta(days=days_until_monday)
    if candidate == local_date and now.strftime("%H:%M") >= meeting_time:
        candidate += timedelta(days=7)
    return candidate.isoformat()


def _business_days_before(value: date, days: int) -> date:
    if days < 0:
        raise ValueError("preparation_lead_business_days must be non-negative")
    result = value
    remaining = days
    while remaining:
        result -= timedelta(days=1)
        if result.weekday() < 5:
            remaining -= 1
    return result


def default_document_name_template(cadence: str, frequency: str) -> str:
    """Return the internal template used when the user did not provide one."""

    if _is_known_weekly_all_hands(cadence, frequency):
        return f"CW{{week}} {cadence}"
    return f"{cadence} — {{YYYY-MM-DD}}"


@dataclass(frozen=True)
class CadenceDefaults:
    """Resolved values used by both the proposal and the Notion write."""

    cadence: str
    frequency: str
    next_date: str
    time_zone: str
    meeting_time: str
    notification_time: str
    slack_channel_name: str
    document_name_template: str
    inferred_fields: tuple[str, ...]


def infer_cadence_defaults(
    cadence: str,
    *,
    frequency: str | None = None,
    next_date: str | None = None,
    time_zone: str | None = None,
    meeting_time: str | None = None,
    notification_time: str | None = None,
    slack_channel_name: str | None = None,
    document_name_template: str | None = None,
    visibility: str = "public",
    now: datetime | None = None,
) -> CadenceDefaults:
    """Resolve safe defaults without requiring internal identifiers from users.

    Explicit values always win. The only workspace-specific convention here is
    the known weekly all-hands pattern; other frequencies require an explicit
    first occurrence rather than silently inventing one.
    """

    title = _required_text("cadence", cadence)
    normalized_frequency = normalize_frequency(frequency)
    known_all_hands = _is_known_weekly_all_hands(title, normalized_frequency)
    inferred: list[str] = []

    resolved_zone = str(time_zone or "").strip()
    if not resolved_zone:
        resolved_zone = DEFAULT_TIME_ZONE
        inferred.append("time zone")
    zone = ZoneInfo(resolved_zone)

    resolved_meeting_time = str(meeting_time or "").strip()
    if not resolved_meeting_time:
        resolved_meeting_time = (
            ALL_HANDS_MEETING_TIME if known_all_hands else DEFAULT_MEETING_TIME
        )
        inferred.append("meeting time")

    resolved_notification_time = str(notification_time or "").strip()
    if not resolved_notification_time:
        resolved_notification_time = (
            ALL_HANDS_NOTIFICATION_TIME
            if known_all_hands
            else DEFAULT_NOTIFICATION_TIME
        )
        inferred.append("notification time")

    resolved_next_date = str(next_date or "").strip()
    if not resolved_next_date:
        if normalized_frequency != "Weekly":
            raise ValueError(
                "next_date is required for non-weekly cadences; include the first occurrence"
            )
        local_now = now or datetime.now(zone)
        if local_now.tzinfo is None:
            local_now = local_now.replace(tzinfo=zone)
        else:
            local_now = local_now.astimezone(zone)
        resolved_next_date = _next_weekly_date(local_now, resolved_meeting_time)
        inferred.append("next meeting date")

    resolved_channel_name = str(slack_channel_name or "").strip()
    if not resolved_channel_name and known_all_hands and visibility == "public":
        resolved_channel_name = ALL_HANDS_CHANNEL_NAME
        inferred.append("Slack channel")

    resolved_template = str(document_name_template or "").strip()
    if not resolved_template:
        resolved_template = default_document_name_template(title, normalized_frequency)
        inferred.append("document name")

    return CadenceDefaults(
        cadence=title,
        frequency=normalized_frequency,
        next_date=resolved_next_date,
        time_zone=zone.key,
        meeting_time=resolved_meeting_time,
        notification_time=resolved_notification_time,
        slack_channel_name=resolved_channel_name,
        document_name_template=resolved_template,
        inferred_fields=tuple(inferred),
    )


def _local_date(value: str, time_zone: str) -> date:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00").replace(" ", "T"))
    if parsed.tzinfo is None:
        return parsed.date()
    return parsed.astimezone(ZoneInfo(time_zone)).date()


def resolve_document_name(template: str, next_date: str, time_zone: str) -> str:
    """Resolve the user-visible document name for a cadence occurrence."""

    occurrence_date = _local_date(next_date, time_zone)
    return (
        str(template)
        .replace("{YYYY-MM-DD}", occurrence_date.isoformat())
        .replace("{week}", f"{occurrence_date.isocalendar().week:02d}")
    )


def stable_automation_id(values: dict[str, Any]) -> str:
    """Create a stable opaque id from canonical internal cadence values."""

    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    return f"cadence-{digest}"


@dataclass(frozen=True)
class CadenceProposal:
    """Display-safe proposal; it intentionally has no IDs or email addresses."""

    cadence: str
    frequency: str
    next_date: str
    time_zone: str
    meeting_time: str
    notification_time: str
    slack_channel_name: str
    document_name: str
    calendar_booking: str
    preparation_day: str
    inferred_fields: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "cadence": self.cadence,
            "frequency": self.frequency,
            "next_date": self.next_date,
            "time_zone": self.time_zone,
            "meeting_time": self.meeting_time,
            "notification_time": self.notification_time,
            "slack_channel": self.slack_channel_name or None,
            "document_name": self.document_name,
            "calendar_booking": self.calendar_booking,
            "preparation_day": self.preparation_day,
            "inferred_fields": list(self.inferred_fields),
        }

    def render(self) -> str:
        lines = [
            "Here's what I'll set up:",
            f"• {self.cadence}",
            f"• {self.frequency}, {_local_date(self.next_date, self.time_zone).strftime('%A')} "
            f"{self.next_date} at {self.meeting_time} ({self.time_zone})",
            f"• Notification: {self.preparation_day} at {self.notification_time}",
        ]
        if self.slack_channel_name:
            lines.append(f"• Slack: {self.slack_channel_name}")
        lines.extend(
            [
                f"• Document: {self.document_name}",
                f"• Calendar booking: {self.calendar_booking}",
            ]
        )
        if self.inferred_fields:
            lines.append(
                "I inferred the missing scheduling details from the workspace convention."
            )
        lines.append("Reply 'confirm' to create this as a Draft.")
        return "\n".join(lines)


def build_cadence_proposal(
    cadence: str,
    *,
    calendar_booking: str = "Off",
    preparation_lead_business_days: int = 1,
    now: datetime | None = None,
    **values: str | None,
) -> CadenceProposal:
    """Build the single concise proposal shown before a Draft write."""

    defaults = infer_cadence_defaults(cadence, now=now, **values)
    return CadenceProposal(
        cadence=defaults.cadence,
        frequency=defaults.frequency,
        next_date=defaults.next_date,
        time_zone=defaults.time_zone,
        meeting_time=defaults.meeting_time,
        notification_time=defaults.notification_time,
        slack_channel_name=defaults.slack_channel_name,
        document_name=resolve_document_name(
            defaults.document_name_template,
            defaults.next_date,
            defaults.time_zone,
        ),
        calendar_booking=calendar_booking,
        preparation_day=_business_days_before(
            _local_date(defaults.next_date, defaults.time_zone),
            preparation_lead_business_days,
        ).strftime("%A"),
        inferred_fields=defaults.inferred_fields,
    )
