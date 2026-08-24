"""Notion REST API client."""

from __future__ import annotations

import re
import uuid
from typing import Any

import httpx

from centaur_sdk import secret

from .cadence_intake import infer_cadence_defaults, stable_automation_id

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
CADENCES_DATABASE_ID = "cbdf28b9-3bc7-474c-85ed-9b323eb09889"
CADENCES_DATA_SOURCE_ID = "79b72eae-a343-4195-9614-1e9c9ef35445"
PRIVATE_CADENCE_TEMPLATE_MARKER = "ORBiE_PRIVATE_CADENCE_TEMPLATE_V1"

_CADENCE_FREQUENCIES = {"Weekly", "Bi-weekly", "Monthly", "Quarterly"}
_CADENCE_TYPES = {"Internal WF", "WF-TFH", "Governance"}
_CADENCE_AUDIENCES = {
    "Everyone",
    "Leadership",
    "Board",
    "Finance",
    "Legal",
    "Econ",
    "World Chain",
    "ProofKit",
    "Privacy",
    "TFH",
}
_TIME_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")
_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
_CALENDAR_BOOKING = {"Off", "Auto-book"}


def _required_text(name: str, value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _choice(name: str, value: str, choices: set[str]) -> str:
    text = _required_text(name, value)
    aliases = {"biweekly": "Bi-weekly", "bi-weekly": "Bi-weekly"}
    text = aliases.get(text.casefold(), text)
    normalized_choices = {choice.casefold(): choice for choice in choices}
    if text.casefold() in normalized_choices:
        return normalized_choices[text.casefold()]
    if text not in choices:
        raise ValueError(f"unsupported {name}: {text!r}")
    return text


def _split_values(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple)) else re.split(r"[,;\n]", value)
    return _unique_casefold([str(item).strip() for item in values if str(item).strip()])


def _unique_casefold(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        folded = value.casefold()
        if folded not in seen:
            seen.add(folded)
            result.append(value)
    return result


def _looks_like_email(value: str) -> bool:
    return "@" in value and " " not in value


def _notion_person(user_id: str) -> dict[str, str]:
    return {"object": "id", "id": user_id}


def _notion_user_id(value: str) -> str | None:
    return _notion_object_id(value)


def _notion_object_id(value: str) -> str | None:
    match = re.search(
        r"(?i)([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|[0-9a-f]{32})(?:$|[?#/])",
        value.rstrip("/"),
    )
    if not match:
        return None
    try:
        return str(uuid.UUID(match.group(1)))
    except ValueError:
        return None


def _validate_next_date(value: str) -> None:
    from datetime import date, datetime

    try:
        if "T" in value or " " in value:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("next_date must be an ISO date or datetime") from error


def _validate_time_zone(value: str) -> None:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"unknown time_zone: {value!r}") from error


class NotionClient:
    """Client for Notion's REST API."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or secret("NOTION_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "NOTION_API_KEY not set.\nGet one at https://www.notion.so/my-integrations"
            )
        self._http = httpx.Client(
            base_url=API_BASE,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Notion-Version": NOTION_VERSION,
            },
            timeout=30.0,
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an HTTP request."""
        resp = self._http.request(method, path, json=json, params=params)
        resp.raise_for_status()
        return resp.json()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def _post(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", path, json=json)

    def _patch(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("PATCH", path, json=json)

    def _delete(self, path: str) -> dict[str, Any]:
        return self._request("DELETE", path)

    # -------------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------------

    def search(
        self,
        query: str | None = None,
        filter_type: str | None = None,
        sort_direction: str = "descending",
        sort_timestamp: str = "last_edited_time",
        page_size: int = 100,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Search pages and databases by title.

        Args:
            query: Text to search for in titles
            filter_type: 'page' or 'database' to filter results
            sort_direction: 'ascending' or 'descending'
            sort_timestamp: 'last_edited_time'
            page_size: Results per page (max 100)
            start_cursor: Pagination cursor
        """
        body: dict[str, Any] = {"page_size": page_size}
        if query:
            body["query"] = query
        if filter_type:
            body["filter"] = {"property": "object", "value": filter_type}
        body["sort"] = {"direction": sort_direction, "timestamp": sort_timestamp}
        if start_cursor:
            body["start_cursor"] = start_cursor
        return self._post("/search", json=body)

    # -------------------------------------------------------------------------
    # Users
    # -------------------------------------------------------------------------

    def me(self) -> dict[str, Any]:
        """Get the bot user."""
        return self._get("/users/me")

    def users(self, page_size: int = 100, start_cursor: str | None = None) -> dict[str, Any]:
        """List all users in the workspace."""
        params: dict[str, Any] = {"page_size": page_size}
        if start_cursor:
            params["start_cursor"] = start_cursor
        return self._get("/users", params=params)

    def user(self, user_id: str) -> dict[str, Any]:
        """Retrieve a user by ID."""
        return self._get(f"/users/{user_id}")

    # -------------------------------------------------------------------------
    # Databases
    # -------------------------------------------------------------------------

    def database(self, database_id: str) -> dict[str, Any]:
        """Retrieve a database."""
        return self._get(f"/databases/{database_id}")

    def query_database(
        self,
        database_id: str,
        filter: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
        page_size: int = 100,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Query a database.

        Args:
            database_id: Database ID
            filter: Filter object (see Notion docs)
            sorts: Sort objects (see Notion docs)
            page_size: Results per page (max 100)
            start_cursor: Pagination cursor
        """
        body: dict[str, Any] = {"page_size": page_size}
        if filter:
            body["filter"] = filter
        if sorts:
            body["sorts"] = sorts
        if start_cursor:
            body["start_cursor"] = start_cursor
        return self._post(f"/databases/{database_id}/query", json=body)

    def create_database(
        self,
        parent_page_id: str,
        title: str,
        properties: dict[str, Any],
        is_inline: bool = False,
    ) -> dict[str, Any]:
        """Create a database.

        Args:
            parent_page_id: Parent page ID
            title: Database title
            properties: Property schema (see Notion docs)
            is_inline: Whether to create inline database
        """
        body: dict[str, Any] = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": properties,
            "is_inline": is_inline,
        }
        return self._post("/databases", json=body)

    def update_database(
        self,
        database_id: str,
        title: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a database."""
        body: dict[str, Any] = {}
        if title:
            body["title"] = [{"type": "text", "text": {"content": title}}]
        if properties:
            body["properties"] = properties
        return self._patch(f"/databases/{database_id}", json=body)

    def ensure_cadence_booking_schema(
        self, database_id: str = CADENCES_DATABASE_ID
    ) -> dict[str, Any]:
        """Add the governed Calendar booking fields to the Cadences database."""
        return self.update_database(
            database_id,
            properties={
                "Calendar booking": {
                    "select": {
                        "options": [
                            {"name": "Off", "color": "gray"},
                            {"name": "Auto-book", "color": "green"},
                        ]
                    }
                },
                "Organizer calendar": {"rich_text": {}},
                "Booking window (business days)": {"number": {"format": "number"}},
                "Booking status": {
                    "select": {
                        "options": [
                            {"name": "Not booked", "color": "gray"},
                            {"name": "Booked", "color": "green"},
                            {"name": "Blocked", "color": "red"},
                        ]
                    }
                },
                "Booked start": {"date": {}},
                "Booked meeting URL": {"url": {}},
            },
        )

    # -------------------------------------------------------------------------
    # Pages
    # -------------------------------------------------------------------------

    def page(self, page_id: str) -> dict[str, Any]:
        """Retrieve a page."""
        return self._get(f"/pages/{page_id}")

    def page_property(
        self,
        page_id: str,
        property_id: str,
        page_size: int = 100,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve a page property item."""
        params: dict[str, Any] = {"page_size": page_size}
        if start_cursor:
            params["start_cursor"] = start_cursor
        return self._get(f"/pages/{page_id}/properties/{property_id}", params=params)

    def create_page(
        self,
        parent: dict[str, Any],
        properties: dict[str, Any],
        children: list[dict[str, Any]] | None = None,
        icon: dict[str, Any] | None = None,
        cover: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a page.

        Args:
            parent: Parent object (database_id or page_id)
            properties: Page properties
            children: Initial block children
            icon: Page icon
            cover: Page cover
        """
        body: dict[str, Any] = {"parent": parent, "properties": properties}
        if children:
            body["children"] = children
        if icon:
            body["icon"] = icon
        if cover:
            body["cover"] = cover
        return self._post("/pages", json=body)

    def create_cadence(
        self,
        *,
        ritual: str,
        automation_id: str | None = None,
        frequency: str = "Weekly",
        next_date: str | None = None,
        time_zone: str | None = None,
        meeting_time: str | None = None,
        notification_time: str | None = None,
        preparation_lead_business_days: int = 1,
        google_template_url: str | None = None,
        google_output_folder_url: str | None = None,
        creator_notion_user_id: str | None = None,
        creator_email: str | None = None,
        owner: str | None = None,
        notification_recipients: str | list[str] | tuple[str, ...] | None = None,
        notification_emails: str | list[str] | tuple[str, ...] | None = None,
        slack_channel_id: str | None = None,
        slack_channel_name: str | None = None,
        document_name_template: str | None = None,
        participants: str | list[str] | tuple[str, ...] | None = None,
        purpose: str | None = None,
        cadence_type: str = "Internal WF",
        audience: str | list[str] | tuple[str, ...] | None = "Everyone",
        duration_minutes: int | float | None = None,
        notes_delay_minutes: int | float | None = None,
        notify_lead_minutes: int | float | None = None,
        notes_links: str | None = None,
        calendar_booking: str = "Off",
        organizer_calendar: str | None = None,
        booking_window_business_days: int | None = None,
        visibility: str = "public",
        cadence_database_id: str | None = None,
        cadence_database_url: str | None = None,
    ) -> dict[str, Any]:
        """Create one Draft row in a shared or private Orbie Cadences database.

        ``creator_notion_user_id`` or ``creator_email`` is required. The
        creator is always assigned as ``Owner / DRI``. ``owner`` is accepted
        only as a compatibility check so callers cannot silently assign a
        different owner. Private cadences must provide the database copied from
        the Orbie private cadence template. They may target a private ``G...``
        Slack channel or group DM, or leave the destination empty for
        owner/recipient DMs. When omitted, ``automation_id`` is generated from
        the canonical resolved request. An existing ID is returned unchanged,
        making retries idempotent within that database.
        """
        visibility = _choice("visibility", visibility, {"public", "private"})
        supplied_database = cadence_database_id or cadence_database_url
        database_id = _notion_object_id(supplied_database) if supplied_database else None
        if supplied_database and not database_id:
            raise ValueError("cadence_database_id must be a Notion database ID or URL")
        database_id = database_id or CADENCES_DATABASE_ID
        if visibility == "private":
            if database_id == CADENCES_DATABASE_ID:
                raise ValueError(
                    "private cadences require cadence_database_url copied from the Orbie template"
                )
            database = self.database(database_id)
            description = self.extract_rich_text(database.get("description") or [])
            if PRIVATE_CADENCE_TEMPLATE_MARKER not in description:
                raise ValueError(
                    "private cadence database must be copied from the Orbie private cadence template"
                )
        elif supplied_database and database_id != CADENCES_DATABASE_ID:
            raise ValueError("custom cadence databases must use visibility=private")

        ritual = _required_text("ritual", ritual)
        defaults = infer_cadence_defaults(
            ritual,
            frequency=frequency,
            next_date=next_date,
            time_zone=time_zone,
            meeting_time=meeting_time,
            notification_time=notification_time,
            slack_channel_name=slack_channel_name,
            document_name_template=document_name_template,
            visibility=visibility,
        )
        frequency = _choice("frequency", defaults.frequency, _CADENCE_FREQUENCIES)
        time_zone = _required_text("time_zone", defaults.time_zone)
        meeting_time = _required_text("meeting_time", defaults.meeting_time)
        notification_time = _required_text("notification_time", defaults.notification_time)
        if not _TIME_RE.fullmatch(meeting_time) or not _TIME_RE.fullmatch(notification_time):
            raise ValueError("meeting_time and notification_time must use HH:MM")
        next_date = _required_text("next_date", defaults.next_date)
        _validate_next_date(next_date)
        _validate_time_zone(time_zone)
        self.ensure_cadence_booking_schema(database_id)
        if preparation_lead_business_days < 0:
            raise ValueError("preparation_lead_business_days must be non-negative")
        calendar_booking = _choice("calendar_booking", calendar_booking, _CALENDAR_BOOKING)
        organizer_calendar = (organizer_calendar or "").strip()
        if calendar_booking == "Auto-book":
            if not organizer_calendar:
                raise ValueError("organizer_calendar is required for Auto-book cadences")
            if booking_window_business_days is None:
                raise ValueError("booking_window_business_days is required for Auto-book cadences")
            if int(booking_window_business_days) <= 0:
                raise ValueError("booking_window_business_days must be positive")
            if duration_minutes is None or int(duration_minutes) <= 0:
                raise ValueError("duration_minutes is required and positive for Auto-book cadences")
            participant_values = _split_values(participants)
            if not participant_values or any(
                not _EMAIL_RE.fullmatch(value) for value in participant_values
            ):
                raise ValueError(
                    "Auto-book Participants must contain exact verified email addresses"
                )
        elif booking_window_business_days is not None and int(booking_window_business_days) < 0:
            raise ValueError("booking_window_business_days must be non-negative")
        cadence_type = _choice("cadence_type", cadence_type, _CADENCE_TYPES)
        audience_values = _split_values(audience)
        unknown_audience = set(audience_values) - _CADENCE_AUDIENCES
        if unknown_audience:
            raise ValueError(f"unsupported audience: {sorted(unknown_audience)!r}")
        channel_id = (slack_channel_id or "").strip()
        channel_name = (defaults.slack_channel_name or "").strip()
        if bool(channel_id) != bool(channel_name):
            raise ValueError("slack_channel_id and slack_channel_name must be set together")
        if visibility == "private" and channel_id and not channel_id.startswith("G"):
            raise ValueError(
                "private cadence Slack destinations must use a G... private channel or group DM"
            )
        if visibility == "public" and channel_id and not channel_id.startswith("C"):
            raise ValueError("public cadence Slack destinations must use a C... channel ID")

        users = self._all_users()
        if calendar_booking == "Auto-book":
            for participant in _split_values(participants):
                if len(self._notion_user_matches(participant, users)) != 1:
                    raise ValueError(
                        f"Auto-book participant {participant} must resolve to exactly one Notion person"
                    )
        creator_id = self._resolve_notion_user(
            creator_notion_user_id or creator_email or "", users, field="creator"
        )
        owner_ids = self.resolve_notion_user_ids([owner], users=users) if owner else [creator_id]
        if owner_ids != [creator_id]:
            raise ValueError("the cadence creator must remain the Owner / DRI")

        recipient_values = _split_values(notification_recipients)
        if visibility == "private" and not recipient_values:
            recipient_values = [creator_id]
        recipient_ids: list[str] = []
        for reference in recipient_values:
            if _looks_like_email(reference):
                matches = self._notion_user_matches(reference, users)
                if len(matches) == 1:
                    recipient_id = str(matches[0]["id"])
                    if recipient_id not in recipient_ids:
                        recipient_ids.append(recipient_id)
                continue
            recipient_id = self._resolve_notion_user(reference, users, field="user")
            if recipient_id not in recipient_ids:
                recipient_ids.append(recipient_id)
        explicit_emails = _split_values(notification_emails)
        recipient_emails = [value for value in recipient_values if _looks_like_email(value)]
        email_values = _unique_casefold(explicit_emails + recipient_emails)

        automation_id = (automation_id or "").strip()
        if not automation_id:
            automation_id = stable_automation_id(
                {
                    "database_id": database_id,
                    "visibility": visibility,
                    "creator_id": creator_id,
                    "ritual": ritual,
                    "frequency": frequency,
                    "next_date": next_date,
                    "time_zone": time_zone,
                    "meeting_time": meeting_time,
                    "notification_time": notification_time,
                    "preparation_lead_business_days": preparation_lead_business_days,
                    "slack_channel_id": channel_id,
                    "slack_channel_name": channel_name,
                    "document_name_template": defaults.document_name_template,
                    "notification_recipients": recipient_ids,
                    "notification_emails": email_values,
                    "participants": _split_values(participants),
                    "purpose": (purpose or "").strip(),
                    "cadence_type": cadence_type,
                    "audience": audience_values,
                    "calendar_booking": calendar_booking,
                    "organizer_calendar": organizer_calendar,
                    "booking_window_business_days": booking_window_business_days,
                    "duration_minutes": duration_minutes,
                }
            )

        existing = self.query_database(
            database_id,
            filter={
                "property": "Automation ID",
                "rich_text": {"equals": automation_id},
            },
            page_size=2,
        ).get("results", [])
        if existing:
            existing_page = existing[0]
            existing_ritual = self.extract_title(existing_page)
            if existing_ritual and existing_ritual != ritual:
                raise ValueError(
                    f"Automation ID {automation_id!r} already belongs to {existing_ritual!r}"
                )
            return existing_page

        properties: dict[str, Any] = {
            "Ritual": {"title": self.make_rich_text(ritual)},
            "Automation ID": {"rich_text": self.make_rich_text(automation_id)},
            "Automation status": {"select": {"name": "Draft"}},
            "Auto-created": {"checkbox": True},
            "Frequency": {"select": {"name": frequency}},
            "Next date": {"date": {"start": next_date}},
            "Time zone": {"rich_text": self.make_rich_text(time_zone)},
            "Meeting time": {"rich_text": self.make_rich_text(meeting_time)},
            "Notification time": {"rich_text": self.make_rich_text(notification_time)},
            "Preparation lead (business days)": {"number": preparation_lead_business_days},
            "Owner / DRI": {"people": [_notion_person(creator_id)]},
            "Notification recipients": {
                "people": [_notion_person(user_id) for user_id in recipient_ids]
            },
            "Notification emails": {"rich_text": self.make_rich_text(", ".join(email_values))},
            "Slack channel ID": {"rich_text": self.make_rich_text(channel_id)},
            "Slack channel name": {"rich_text": self.make_rich_text(channel_name)},
            "Document name template": {
                "rich_text": self.make_rich_text(defaults.document_name_template)
            },
            "Participants": {
                "rich_text": self.make_rich_text(", ".join(_split_values(participants)))
            },
            "Purpose": {"rich_text": self.make_rich_text(purpose or "")},
            "Type": {"select": {"name": cadence_type}},
            "Audience": {"multi_select": [{"name": value} for value in audience_values]},
            "Notification mode": {"select": {"name": "Orbie"}},
            "Document access": {
                "select": {
                    "name": "Cadence members" if visibility == "private" else "All World members"
                }
            },
            "Calendar booking": {"select": {"name": calendar_booking}},
            "Organizer calendar": {"rich_text": self.make_rich_text(organizer_calendar)},
            "Booking status": {"select": {"name": "Not booked"}},
            "Booked start": {"date": None},
            "Booked meeting URL": {"url": None},
        }
        optional_urls = {
            "Google template URL": google_template_url,
            "Google output folder URL": google_output_folder_url,
        }
        for property_name, value in optional_urls.items():
            if value:
                properties[property_name] = {"url": value.strip()}
        optional_numbers = {
            "Duration (min)": duration_minutes,
            "Notes delay (min)": notes_delay_minutes,
            "Notify lead (min)": notify_lead_minutes,
        }
        for property_name, value in optional_numbers.items():
            if value is not None:
                if value < 0:
                    raise ValueError(f"{property_name} must be non-negative")
                properties[property_name] = {"number": value}
        if booking_window_business_days is not None:
            properties["Booking window (business days)"] = {
                "number": int(booking_window_business_days)
            }
        if notes_links:
            properties["Notes / links"] = {"rich_text": self.make_rich_text(notes_links.strip())}
        return self.create_page(
            {"database_id": database_id},
            properties,
        )

    def _all_users(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            response = self.users(page_size=100, start_cursor=cursor)
            results.extend(item for item in response.get("results", []) if isinstance(item, dict))
            if not response.get("has_more"):
                return results
            cursor = response.get("next_cursor")
            if not cursor:
                return results

    def resolve_notion_user_ids(
        self,
        references: list[str] | tuple[str, ...],
        *,
        users: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        """Resolve Notion profile IDs/URLs or exact email addresses to IDs."""
        resolved: list[str] = []
        user_list = users if users is not None else self._all_users()
        for reference in references:
            user_id = self._resolve_notion_user(reference, user_list, field="user")
            if user_id not in resolved:
                resolved.append(user_id)
        return resolved

    @staticmethod
    def _resolve_notion_user(
        reference: str,
        users: list[dict[str, Any]],
        *,
        field: str,
    ) -> str:
        token = _required_text(field, reference)
        matches = NotionClient._notion_user_matches(token, users)
        if len(matches) != 1:
            raise ValueError(f"{field} must resolve to exactly one Notion person")
        return str(matches[0]["id"])

    @staticmethod
    def _notion_user_matches(reference: str, users: list[dict[str, Any]]) -> list[dict[str, Any]]:
        reference_id = _notion_user_id(reference)
        if reference_id:
            return [
                user for user in users if str(user.get("id", "")).lower() == reference_id.lower()
            ]
        folded = reference.casefold()
        return [
            user
            for user in users
            if str(user.get("person", {}).get("email", "")).casefold() == folded
        ]

    def update_page(
        self,
        page_id: str,
        properties: dict[str, Any] | None = None,
        archived: bool | None = None,
        icon: dict[str, Any] | None = None,
        cover: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a page."""
        body: dict[str, Any] = {}
        if properties:
            body["properties"] = properties
        if archived is not None:
            body["archived"] = archived
        if icon:
            body["icon"] = icon
        if cover:
            body["cover"] = cover
        return self._patch(f"/pages/{page_id}", json=body)

    def archive_page(self, page_id: str) -> dict[str, Any]:
        """Archive (trash) a page."""
        return self.update_page(page_id, archived=True)

    def restore_page(self, page_id: str) -> dict[str, Any]:
        """Restore a page from trash."""
        return self.update_page(page_id, archived=False)

    # -------------------------------------------------------------------------
    # Blocks
    # -------------------------------------------------------------------------

    def block(self, block_id: str) -> dict[str, Any]:
        """Retrieve a block."""
        return self._get(f"/blocks/{block_id}")

    def block_children(
        self,
        block_id: str,
        page_size: int = 100,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve block children (page content)."""
        params: dict[str, Any] = {"page_size": page_size}
        if start_cursor:
            params["start_cursor"] = start_cursor
        return self._get(f"/blocks/{block_id}/children", params=params)

    def append_block_children(
        self,
        block_id: str,
        children: list[dict[str, Any]],
        after: str | None = None,
    ) -> dict[str, Any]:
        """Append blocks to a page or block.

        Args:
            block_id: Parent block/page ID
            children: Block objects to append
            after: Block ID to insert after
        """
        body: dict[str, Any] = {"children": children}
        if after:
            body["after"] = after
        return self._patch(f"/blocks/{block_id}/children", json=body)

    def update_block(
        self,
        block_id: str,
        block_data: dict[str, Any],
        archived: bool | None = None,
    ) -> dict[str, Any]:
        """Update a block."""
        body = block_data.copy()
        if archived is not None:
            body["archived"] = archived
        return self._patch(f"/blocks/{block_id}", json=body)

    def delete_block(self, block_id: str) -> dict[str, Any]:
        """Delete (archive) a block."""
        return self._delete(f"/blocks/{block_id}")

    # -------------------------------------------------------------------------
    # Comments
    # -------------------------------------------------------------------------

    def comments(
        self,
        block_id: str | None = None,
        page_size: int = 100,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve comments on a block or page."""
        params: dict[str, Any] = {"page_size": page_size}
        if block_id:
            params["block_id"] = block_id
        if start_cursor:
            params["start_cursor"] = start_cursor
        return self._get("/comments", params=params)

    def create_comment(
        self,
        parent: dict[str, Any],
        rich_text: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create a comment.

        Args:
            parent: {"page_id": "..."} or {"discussion_id": "..."}
            rich_text: Comment content as rich text
        """
        body = {"parent": parent, "rich_text": rich_text}
        return self._post("/comments", json=body)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def get_all_pages(
        self,
        database_id: str,
        filter: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all pages from a database (handles pagination)."""
        results = []
        cursor = None
        while True:
            resp = self.query_database(database_id, filter=filter, sorts=sorts, start_cursor=cursor)
            results.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return results

    def get_page_content(self, page_id: str) -> list[dict[str, Any]]:
        """Fetch all block children of a page (handles pagination)."""
        results = []
        cursor = None
        while True:
            resp = self.block_children(page_id, start_cursor=cursor)
            results.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return results

    @staticmethod
    def extract_title(page_or_db: dict[str, Any]) -> str:
        """Extract plain text title from a page or database object."""
        props = page_or_db.get("properties", {})

        # Database title
        if page_or_db.get("object") == "database":
            title_arr = page_or_db.get("title", [])
            return "".join(t.get("plain_text", "") for t in title_arr)

        # Page title - find the title property
        for prop in props.values():
            if prop.get("type") == "title":
                title_arr = prop.get("title", [])
                return "".join(t.get("plain_text", "") for t in title_arr)

        return ""

    @staticmethod
    def extract_rich_text(rich_text: list[dict[str, Any]]) -> str:
        """Extract plain text from rich text array."""
        return "".join(t.get("plain_text", "") for t in rich_text)

    @staticmethod
    def make_rich_text(text: str) -> list[dict[str, Any]]:
        """Create a simple rich text array from plain text."""
        return [{"type": "text", "text": {"content": text}}]

    @staticmethod
    def make_paragraph_block(text: str) -> dict[str, Any]:
        """Create a paragraph block."""
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": NotionClient.make_rich_text(text)},
        }

    @staticmethod
    def make_heading_block(text: str, level: int = 1) -> dict[str, Any]:
        """Create a heading block (level 1, 2, or 3)."""
        heading_type = f"heading_{level}"
        return {
            "object": "block",
            "type": heading_type,
            heading_type: {"rich_text": NotionClient.make_rich_text(text)},
        }

    @staticmethod
    def make_todo_block(text: str, checked: bool = False) -> dict[str, Any]:
        """Create a to-do block."""
        return {
            "object": "block",
            "type": "to_do",
            "to_do": {
                "rich_text": NotionClient.make_rich_text(text),
                "checked": checked,
            },
        }

    @staticmethod
    def make_bullet_block(text: str) -> dict[str, Any]:
        """Create a bulleted list item block."""
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": NotionClient.make_rich_text(text)},
        }


def _client() -> NotionClient:
    return NotionClient(api_key=secret("NOTION_API_KEY", ""))
