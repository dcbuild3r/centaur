from __future__ import annotations

import pytest

from notion.client import NotionClient


def _client(monkeypatch, *, existing=None):
    client = NotionClient.__new__(NotionClient)
    client._http = None
    users = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "type": "person",
            "person": {"email": "creator@world.org"},
        },
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "type": "person",
            "person": {"email": "owner@world.org"},
        },
        {
            "id": "33333333-3333-3333-3333-333333333333",
            "type": "person",
            "person": {"email": "recipient@world.org"},
        },
    ]
    monkeypatch.setattr(client, "_all_users", lambda: users)
    monkeypatch.setattr(client, "ensure_cadence_booking_schema", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        client, "query_database", lambda *args, **kwargs: {"results": existing or []}
    )
    return client


def test_create_cadence_resolves_people_and_writes_a_draft(monkeypatch):
    client = _client(monkeypatch)
    created = {}

    def create_page(parent, properties, **_kwargs):
        created.update(parent=parent, properties=properties)
        return {"id": "page-1", "url": "https://notion.so/page-1", "properties": properties}

    monkeypatch.setattr(client, "create_page", create_page)

    result = client.create_cadence(
        cadence="Weekly Sync",
        automation_id="weekly-sync",
        frequency="weekly",
        next_date="2026-08-17T10:00:00+02:00",
        time_zone="Europe/Prague",
        meeting_time="10:00",
        notification_time="09:15",
        google_template_url="https://docs.google.com/document/d/template/edit",
        google_output_folder_url="https://drive.google.com/drive/folders/folder",
        creator_email="creator@world.org",
        notification_recipients=[
            "https://www.notion.so/33333333333333333333333333333333",
            "recipient@world.org",
        ],
        notification_emails="additional@world.org",
        slack_channel_id="C123456",
        slack_channel_name="#ai-agents",
        participants=["Piotr", "Orbie"],
        purpose="Collect weekly updates",
    )

    assert result["id"] == "page-1"
    assert created["parent"] == {"database_id": "cbdf28b9-3bc7-474c-85ed-9b323eb09889"}
    props = created["properties"]
    assert props["Cadence"]["title"][0]["text"]["content"] == "Weekly Sync"
    assert props["Automation status"] == {"select": {"name": "Draft"}}
    assert props["Auto-created"] == {"checkbox": True}
    assert props["Owner / DRI"]["people"] == [
        {
            "object": "id",
            "id": "11111111-1111-1111-1111-111111111111",
        }
    ]
    assert [item["id"] for item in props["Notification recipients"]["people"]] == [
        "33333333-3333-3333-3333-333333333333"
    ]
    assert props["Notification emails"]["rich_text"][0]["text"]["content"] == (
        "additional@world.org, recipient@world.org"
    )


def test_create_cadence_infers_weekly_all_hands_defaults_and_id(monkeypatch):
    client = _client(monkeypatch)
    created = {}
    monkeypatch.setattr(
        client,
        "create_page",
        lambda parent, properties, **_kwargs: (
            created.update(parent=parent, properties=properties) or {"id": "page-all-hands"}
        ),
    )

    result = client.create_cadence(
        cadence="World Foundation Weekly All Hands",
        next_date="2026-08-31",
        creator_email="creator@world.org",
        slack_channel_id="C123456789",
        slack_channel_name="#wf-all",
    )

    assert result["id"] == "page-all-hands"
    props = created["properties"]
    assert props["Automation ID"]["rich_text"][0]["text"]["content"].startswith("cadence-")
    assert props["Frequency"] == {"select": {"name": "Weekly"}}
    assert props["Time zone"]["rich_text"][0]["text"]["content"] == "Europe/Prague"
    assert props["Meeting time"]["rich_text"][0]["text"]["content"] == "16:00"
    assert props["Notification time"]["rich_text"][0]["text"]["content"] == "09:00"
    assert props["Document name template"]["rich_text"][0]["text"]["content"] == (
        "CW{week} World Foundation Weekly All Hands"
    )


def test_generated_automation_id_makes_retries_idempotent(monkeypatch):
    client = _client(monkeypatch)
    existing = []
    create_calls = []

    def query_database(*_args, **_kwargs):
        return {"results": existing}

    def create_page(_parent, properties, **_kwargs):
        create_calls.append(properties)
        page = {"id": "generated-page", "properties": properties}
        existing.append(page)
        return page

    monkeypatch.setattr(client, "query_database", query_database)
    monkeypatch.setattr(client, "create_page", create_page)

    values = {
        "cadence": "World Foundation Weekly All Hands",
        "next_date": "2026-08-31",
        "creator_email": "creator@world.org",
        "slack_channel_id": "C123456789",
        "slack_channel_name": "#wf-all",
    }
    first = client.create_cadence(**values)
    second = client.create_cadence(**values)

    assert first["id"] == second["id"] == "generated-page"
    assert len(create_calls) == 1


def test_create_cadence_is_idempotent_by_automation_id(monkeypatch):
    existing_page = {
        "id": "existing-page",
        "properties": {
            "Cadence": {
                "type": "title",
                "title": [{"plain_text": "Weekly Sync"}],
            }
        },
    }
    client = _client(monkeypatch, existing=[existing_page])
    monkeypatch.setattr(client, "create_page", lambda *_args, **_kwargs: pytest.fail("duplicate"))

    assert (
        client.create_cadence(
            cadence="Weekly Sync",
            automation_id="weekly-sync",
            frequency="Weekly",
            next_date="2026-08-17",
            time_zone="Europe/Prague",
            meeting_time="10:00",
            notification_time="09:15",
            creator_email="creator@world.org",
        )
        is existing_page
    )


def test_create_cadence_rejects_a_different_owner(monkeypatch):
    client = _client(monkeypatch)

    with pytest.raises(ValueError, match="creator must remain"):
        client.create_cadence(
            cadence="Weekly Sync",
            automation_id="weekly-sync",
            frequency="Weekly",
            next_date="2026-08-17",
            time_zone="Europe/Prague",
            meeting_time="10:00",
            notification_time="09:15",
            creator_email="creator@world.org",
            owner="owner@world.org",
        )


def test_create_cadence_allows_email_only_notification_recipients(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        client,
        "create_page",
        lambda _parent, properties, **_kwargs: {"properties": properties},
    )

    result = client.create_cadence(
        cadence="Email-only sync",
        automation_id="email-only-sync",
        frequency="Weekly",
        next_date="2026-08-17",
        time_zone="Europe/Prague",
        meeting_time="10:00",
        notification_time="09:15",
        creator_email="creator@world.org",
        notification_recipients="slack-only@world.org",
    )

    assert result["properties"]["Notification recipients"] == {"people": []}
    assert result["properties"]["Notification emails"]["rich_text"][0]["text"]["content"] == (
        "slack-only@world.org"
    )


def test_create_cadence_writes_auto_book_configuration(monkeypatch):
    client = _client(monkeypatch)
    created = {}
    monkeypatch.setattr(
        client,
        "create_page",
        lambda parent, properties, **_kwargs: (
            created.update(parent=parent, properties=properties) or {"id": "page-auto"}
        ),
    )

    result = client.create_cadence(
        cadence="Auto-book sync",
        automation_id="auto-book-sync",
        frequency="Weekly",
        next_date="2026-08-17",
        time_zone="Europe/Prague",
        meeting_time="10:00",
        notification_time="09:15",
        creator_email="creator@world.org",
        participants=["recipient@world.org"],
        duration_minutes=45,
        calendar_booking="Auto-book",
        organizer_calendar="wf-main",
        booking_window_business_days=3,
    )

    assert result["id"] == "page-auto"
    props = created["properties"]
    assert props["Calendar booking"] == {"select": {"name": "Auto-book"}}
    assert props["Organizer calendar"]["rich_text"][0]["text"]["content"] == "wf-main"
    assert props["Booking window (business days)"] == {"number": 3}
    assert props["Booking status"] == {"select": {"name": "Not booked"}}
    assert props["Booked start"] == {"date": None}
    assert props["Booked meeting URL"] == {"url": None}


def test_create_cadence_rejects_incomplete_auto_book_configuration(monkeypatch):
    client = _client(monkeypatch)
    with pytest.raises(ValueError, match="duration_minutes"):
        client.create_cadence(
            cadence="Missing duration",
            automation_id="missing-duration",
            frequency="Weekly",
            next_date="2026-08-17",
            time_zone="Europe/Prague",
            meeting_time="10:00",
            notification_time="09:15",
            creator_email="creator@world.org",
            participants=["recipient@world.org"],
            calendar_booking="Auto-book",
            organizer_calendar="wf-main",
            booking_window_business_days=3,
        )


def test_create_private_cadence_targets_a_copied_template_and_defaults_owner_recipient(
    monkeypatch,
):
    client = _client(monkeypatch)
    database_id = "44444444-4444-4444-4444-444444444444"
    schema_calls = []
    created = {}
    monkeypatch.setattr(
        client,
        "database",
        lambda _database_id: {"description": [{"plain_text": "ORBiE_PRIVATE_CADENCE_TEMPLATE_V1"}]},
    )
    monkeypatch.setattr(
        client,
        "ensure_cadence_booking_schema",
        lambda database_id: schema_calls.append(database_id) or {},
    )
    monkeypatch.setattr(
        client,
        "create_page",
        lambda parent, properties, **_kwargs: (
            created.update(parent=parent, properties=properties) or {"id": "private-page"}
        ),
    )

    result = client.create_cadence(
        cadence="Private Weekly Sync",
        automation_id="private-weekly-sync",
        frequency="Weekly",
        next_date="2026-08-17",
        time_zone="Europe/Prague",
        meeting_time="10:00",
        notification_time="09:15",
        creator_email="creator@world.org",
        visibility="private",
        cadence_database_url=f"https://www.notion.so/{database_id.replace('-', '')}",
    )

    assert result["id"] == "private-page"
    assert schema_calls == [database_id]
    assert created["parent"] == {"database_id": database_id}
    assert created["properties"]["Document access"] == {"select": {"name": "Cadence members"}}
    assert created["properties"]["Slack channel ID"]["rich_text"][0]["text"]["content"] == ""
    assert created["properties"]["Notification recipients"]["people"] == [
        {"object": "id", "id": "11111111-1111-1111-1111-111111111111"}
    ]


def test_create_private_cadence_rejects_an_unmarked_database(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(client, "database", lambda _database_id: {"description": []})

    with pytest.raises(ValueError, match="copied from the Orbie private cadence template"):
        client.create_cadence(
            cadence="Private Weekly Sync",
            automation_id="private-weekly-sync",
            frequency="Weekly",
            next_date="2026-08-17",
            time_zone="Europe/Prague",
            meeting_time="10:00",
            notification_time="09:15",
            creator_email="creator@world.org",
            visibility="private",
            cadence_database_id="44444444-4444-4444-4444-444444444444",
        )
