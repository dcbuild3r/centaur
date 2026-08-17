from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from meeting_scheduler import client


async def _async_value(value):
    return value


def test_find_availability_uses_freebusy_only_and_returns_slots(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("MEETING_ORGANIZER_CALENDARS", json.dumps({"wf": "organizer@world.org"}))
    calls = []

    class FakeFreebusy:
        def query(self, **kwargs):
            calls.append(kwargs)
            return self

        def execute(self):
            return {
                "calendars": {
                    "organizer@world.org": {"busy": []},
                    "person@world.org": {
                        "busy": [{"start": "2026-08-17T09:00:00Z", "end": "2026-08-17T10:00:00Z"}]
                    },
                }
            }

    class FakeService:
        def freebusy(self):
            return FakeFreebusy()

    monkeypatch.setattr(client, "get_calendar_service", lambda: FakeService())
    result = client.MeetingSchedulerClient().find_availability(
        "wf",
        ["person@world.org"],
        "2026-08-17T09:00:00Z",
        "2026-08-17T12:00:00Z",
        30,
    )

    assert calls[0]["body"]["items"] == [
        {"id": "organizer@world.org"},
        {"id": "person@world.org"},
    ]
    assert result["candidates"][0]["start"] == "2026-08-17T10:00:00Z"
    assert "summary" not in calls[0]


def test_ad_hoc_booking_requires_confirmation(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("MEETING_ORGANIZER_CALENDARS", '{"wf":"organizer@world.org"}')

    with pytest.raises(client.MeetingSchedulerError, match="explicit confirmation"):
        client.MeetingSchedulerClient().book_meeting(
            "request:1",
            "Planning",
            "2026-08-17T10:00:00Z",
            30,
            "Europe/Prague",
            ["person@world.org"],
            "wf",
            mode="ad_hoc",
        )


def test_ad_hoc_booking_rechecks_a_confirmed_slot_for_staleness(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("MEETING_ORGANIZER_CALENDARS", '{"wf":"organizer@world.org"}')

    class FakeFreebusy:
        def query(self, **_kwargs):
            return self

        def execute(self):
            return {
                "calendars": {
                    "organizer@world.org": {
                        "busy": [
                            {
                                "start": "2099-08-17T10:00:00Z",
                                "end": "2099-08-17T10:30:00Z",
                            }
                        ]
                    },
                    "person@world.org": {"busy": []},
                }
            }

    class FakeService:
        def freebusy(self):
            return FakeFreebusy()

    monkeypatch.setattr(client, "get_calendar_service", lambda: FakeService())
    confirmation = client._slot_confirmation_token(
        start=client._parse_rfc3339("2099-08-17T10:00:00Z", field="start"),
        duration=30,
        time_zone="Europe/Prague",
        attendees=["person@world.org"],
        organizer_calendar_key="wf",
    )
    with pytest.raises(client.MeetingSchedulerError, match="no longer free"):
        client.MeetingSchedulerClient().book_meeting(
            "request:stale",
            "Planning",
            "2099-08-17T10:00:00Z",
            30,
            "Europe/Prague",
            ["person@world.org"],
            "wf",
            mode="ad_hoc",
            confirmation_token=confirmation,
        )


def test_organizer_alias_is_allowlisted(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("MEETING_ORGANIZER_CALENDARS", '{"wf":"organizer@world.org"}')

    with pytest.raises(client.MeetingSchedulerError, match="not allowlisted"):
        client.MeetingSchedulerClient().find_availability(
            "primary",
            ["person@world.org"],
            "2026-08-17T09:00:00Z",
            "2026-08-17T10:00:00Z",
            30,
        )


def test_find_availability_applies_working_window_in_requested_timezone(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("MEETING_ORGANIZER_CALENDARS", '{"wf":"organizer@world.org"}')

    class FakeFreebusy:
        def query(self, **_kwargs):
            return self

        def execute(self):
            return {
                "calendars": {
                    "organizer@world.org": {"busy": []},
                    "person@world.org": {"busy": []},
                }
            }

    class FakeService:
        def freebusy(self):
            return FakeFreebusy()

    monkeypatch.setattr(client, "get_calendar_service", lambda: FakeService())
    result = client.MeetingSchedulerClient().find_availability(
        "wf",
        ["person@world.org"],
        "2026-03-09T15:00:00Z",
        "2026-03-09T19:00:00Z",
        60,
        response_timezone="America/New_York",
    )

    assert result["candidates"][0] == {
        "start": "2026-03-09T11:00:00-04:00",
        "end": "2026-03-09T12:00:00-04:00",
        "timezone": "America/New_York",
        "confirmationToken": client._slot_confirmation_token(
            start=client._parse_rfc3339("2026-03-09T15:00:00Z", field="start"),
            duration=60,
            time_zone="America/New_York",
            attendees=["person@world.org"],
            organizer_calendar_key="wf",
        ),
    }


def test_ad_hoc_reschedule_and_cancel_require_confirmation(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("MEETING_ORGANIZER_CALENDARS", '{"wf":"organizer@world.org"}')
    scheduler = client.MeetingSchedulerClient()

    monkeypatch.setattr(
        scheduler,
        "_get_existing",
        lambda _key: None,
    )
    with pytest.raises(client.MeetingSchedulerError, match="explicit confirmation"):
        scheduler.reschedule_meeting("request:1", "2026-08-17T10:00:00Z", 1, "wf", mode="ad_hoc")
    with pytest.raises(client.MeetingSchedulerError, match="explicit confirmation"):
        scheduler.cancel_meeting("request:1", "wf")


def test_reschedule_rejects_a_stale_expected_version(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    scheduler = client.MeetingSchedulerClient()
    state = {
        "status": "booked",
        "version": 3,
        "organizer_calendar_key": "wf",
        "actual_start": "2099-08-17T10:00:00+00:00",
        "duration_minutes": 30,
        "time_zone": "Europe/Prague",
        "zoom_meeting_id": "zoom-1",
        "calendar_event_id": "event-1",
        "organizer_calendar_id": "organizer@world.org",
    }

    class Connection:
        async def fetchrow(self, _query, _key):
            return state

    async def lock(_key, operation):
        return await operation(Connection())

    monkeypatch.setattr(client, "_with_occurrence_lock", lock)
    with pytest.raises(client.MeetingSchedulerError, match="version is stale"):
        scheduler.reschedule_meeting(
            "request:1",
            "2099-08-17T11:00:00Z",
            2,
            "wf",
            mode="ad_hoc",
            confirmation_token="confirmed",
        )


def test_reschedule_compensates_zoom_when_calendar_update_fails(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("MEETING_ORGANIZER_CALENDARS", '{"wf":"organizer@world.org"}')
    scheduler = client.MeetingSchedulerClient()
    state = {
        "status": "booked",
        "version": 2,
        "organizer_calendar_key": "wf",
        "organizer_calendar_id": "organizer@world.org",
        "actual_start": "2099-08-17T10:00:00+00:00",
        "requested_start": "2099-08-17T10:00:00+00:00",
        "duration_minutes": 30,
        "time_zone": "Europe/Prague",
        "attendee_emails": ["person@world.org"],
        "zoom_meeting_id": "zoom-1",
        "zoom_join_url": "https://zoom/j/1",
        "calendar_event_id": "event-1",
    }
    zoom_calls = []

    class Request:
        def __init__(self, value=None, error=None):
            self.value = value
            self.error = error

        def execute(self):
            if self.error:
                raise self.error
            return self.value

    class Freebusy:
        def query(self, **_kwargs):
            return self

        def execute(self):
            return {
                "calendars": {
                    "organizer@world.org": {"busy": []},
                    "person@world.org": {"busy": []},
                }
            }

    class Events:
        def __init__(self):
            self.update_count = 0

        def get(self, **_kwargs):
            return Request({"id": "event-1", "start": {}, "end": {}})

        def update(self, **_kwargs):
            self.update_count += 1
            if self.update_count == 1:
                return Request(error=RuntimeError("calendar update failed"))
            return Request({"id": "event-1", "htmlLink": "https://calendar/event-1"})

    events = Events()

    class FakeService:
        def freebusy(self):
            return Freebusy()

        def events(self):
            return events

    monkeypatch.setattr(client, "get_calendar_service", lambda: FakeService())

    def zoom_request(method, path, **kwargs):
        zoom_calls.append((method, path, kwargs))
        return {}

    monkeypatch.setattr(scheduler, "_zoom_request", zoom_request)

    class Connection:
        async def fetchrow(self, query, *_args):
            if "select *" in query:
                return state
            raise AssertionError(query)

        async def execute(self, *_args):
            return None

    async def lock(_key, operation):
        return await operation(Connection())

    monkeypatch.setattr(client, "_with_occurrence_lock", lock)

    with pytest.raises(client.MeetingSchedulerError, match="provider rescheduling failed"):
        scheduler.reschedule_meeting(
            "occurrence:1",
            "2099-08-17T11:00:00Z",
            2,
            "wf",
        )

    assert [call[1] for call in zoom_calls] == ["/meetings/zoom-1", "/meetings/zoom-1"]
    assert zoom_calls[0][2]["payload"]["start_time"] == "2099-08-17T11:00:00Z"
    assert zoom_calls[1][2]["payload"]["start_time"] == "2099-08-17T10:00:00Z"
    assert events.update_count == 2


def test_ad_hoc_retry_rejects_parameter_drift(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("MEETING_ORGANIZER_CALENDARS", '{"wf":"organizer@world.org"}')
    scheduler = client.MeetingSchedulerClient()
    state = {
        "status": "pending",
        "title": "Original",
        "requested_start": "2099-08-17T10:00:00+00:00",
        "duration_minutes": 30,
        "time_zone": "Europe/Prague",
        "organizer_calendar_key": "wf",
        "organizer_calendar_id": "organizer@world.org",
        "attendee_emails": ["person@world.org"],
        "calendar_event_id": "",
        "zoom_meeting_id": "",
    }

    class Freebusy:
        def query(self, **_kwargs):
            return self

        def execute(self):
            return {
                "calendars": {
                    "organizer@world.org": {"busy": []},
                    "person@world.org": {"busy": []},
                }
            }

    class FakeService:
        def freebusy(self):
            return Freebusy()

    monkeypatch.setattr(client, "get_calendar_service", lambda: FakeService())
    class Connection:
        async def execute(self, *_args):
            return None

        async def fetchrow(self, query, *_args):
            if "returning occurrence_key" in query:
                return None
            return state

    async def lock(_key, operation):
        return await operation(Connection())

    monkeypatch.setattr(client, "_with_occurrence_lock", lock)
    confirmation = client._slot_confirmation_token(
        start=client._parse_rfc3339("2099-08-17T10:00:00Z", field="start"),
        duration=30,
        time_zone="Europe/Prague",
        attendees=["person@world.org"],
        organizer_calendar_key="wf",
    )

    with pytest.raises(client.MeetingSchedulerError, match="parameters cannot be changed"):
        scheduler.book_meeting(
            "request:1",
            "Changed",
            "2099-08-17T10:00:00Z",
            30,
            "Europe/Prague",
            ["person@world.org"],
            "wf",
            mode="ad_hoc",
            confirmation_token=confirmation,
        )


def test_cadence_reconciliation_allows_provider_bound_parameter_updates(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    scheduler = client.MeetingSchedulerClient()
    state = {
        "status": "booked",
        "title": "Original",
        "requested_start": "2099-08-17T10:00:00+00:00",
        "duration_minutes": 30,
        "time_zone": "Europe/Prague",
        "organizer_calendar_key": "wf",
        "organizer_calendar_id": "organizer@world.org",
        "attendee_emails": ["person@world.org"],
        "calendar_event_id": "event-1",
        "zoom_meeting_id": "zoom-1",
    }

    class Connection:
        async def fetchrow(self, query, *_args):
            if "returning occurrence_key" in query:
                return None
            return state

        async def execute(self, *_args):
            raise AssertionError("a booked cadence should reconcile before rewriting state")

    async def claim():
        return await scheduler._claim_occurrence_row(
            Connection(),
            key="cadence:1",
            cadence_id="cadence-1",
            request_id="cadence:1",
            title="Updated",
            requested_start=client._parse_rfc3339(
                "2099-08-17T10:00:00Z", field="requested_start"
            ),
            duration=45,
            time_zone="Europe/Prague",
            organizer_key="wf",
            organizer_id="organizer@world.org",
            attendees=["person@world.org", "new@world.org"],
            allow_parameter_update=True,
        )

    current, inserted = asyncio.run(claim())
    assert current == state
    assert inserted is False


def test_freebusy_errors_fail_closed_without_exposing_event_details(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("MEETING_ORGANIZER_CALENDARS", '{"wf":"organizer@world.org"}')

    class FakeFreebusy:
        def query(self, **_kwargs):
            return self

        def execute(self):
            return {
                "calendars": {
                    "organizer@world.org": {"busy": []},
                    "person@world.org": {
                        "errors": [{"reason": "notFound"}],
                        "busy": [],
                    },
                }
            }

    class FakeService:
        def freebusy(self):
            return FakeFreebusy()

    monkeypatch.setattr(client, "get_calendar_service", lambda: FakeService())
    with pytest.raises(client.MeetingSchedulerError, match="free/busy access"):
        client.MeetingSchedulerClient().find_availability(
            "wf",
            ["person@world.org"],
            "2026-08-17T09:00:00Z",
            "2026-08-17T10:00:00Z",
            30,
        )


def test_scheduler_lock_is_transaction_scoped(monkeypatch):
    calls = []

    class Transaction:
        async def __aenter__(self):
            calls.append("begin")

        async def __aexit__(self, *_args):
            calls.append("end")

    class Connection:
        def transaction(self):
            return Transaction()

        async def execute(self, query, *_args):
            calls.append(query)

        async def close(self):
            calls.append("close")

    connection = Connection()
    monkeypatch.setattr(client, "_database_url", lambda: "postgresql://scheduler")
    monkeypatch.setattr(client.asyncpg, "connect", lambda *_args, **_kwargs: _await(connection))

    async def operation(_connection):
        calls.append("operation")
        return "ok"

    async def run():
        return await client._with_occurrence_lock("cadence:2026-08-17", operation)

    async def _await(value):
        return value

    assert asyncio.run(run()) == "ok"
    assert calls == [
        "begin",
        "select pg_advisory_xact_lock(hashtextextended($1, 0))",
        "operation",
        "end",
        "close",
    ]


def test_book_meeting_reuses_deterministic_calendar_id_after_partial_insert(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("MEETING_ORGANIZER_CALENDARS", '{"wf":"organizer@world.org"}')
    monkeypatch.setenv("MEETING_ZOOM_HOST_USER_ID", "host-1")
    scheduler = client.MeetingSchedulerClient()
    state = {
        "status": "pending",
        "title": "Planning",
        "duration_minutes": 30,
        "organizer_calendar_key": "wf",
        "attendee_emails": ["person@world.org"],
        "zoom_meeting_id": "",
        "zoom_join_url": "",
        "calendar_event_id": "",
    }

    class FakeConnection:
        def transaction(self):
            raise AssertionError("test injects the lock boundary")

        async def fetchrow(self, query, *args):
            if "returning occurrence_key" in query:
                return {"occurrence_key": args[0]}
            if "set status = 'booked'" in query:
                return {**state, "status": "booked"}
            return state

        async def execute(self, *_args):
            return None

    class Request:
        def __init__(self, value=None, error=None):
            self.value = value
            self.error = error

        def execute(self):
            if self.error:
                raise self.error
            return self.value

    class Events:
        def __init__(self):
            self.insert_calls = []

        def insert(self, **kwargs):
            self.insert_calls.append(kwargs)
            return Request(error=RuntimeError("insert response lost"))

        def get(self, **_kwargs):
            return Request(
                value={
                    "id": client.MeetingSchedulerClient._calendar_event_id("cadence:1"),
                    "htmlLink": "https://calendar/event",
                }
            )

    events = Events()

    class FakeService:
        def events(self):
            return events

    monkeypatch.setattr(client, "get_calendar_service", lambda: FakeService())
    monkeypatch.setattr(
        scheduler,
        "_zoom_create",
        lambda **_kwargs: {"id": "zoom-1", "join_url": "https://zoom/j/1"},
    )
    monkeypatch.setattr(scheduler, "_zoom_find_by_occurrence", lambda _key: None)

    async def lock(_key, operation):
        return await operation(FakeConnection())

    monkeypatch.setattr(client, "_with_occurrence_lock", lock)
    result = scheduler.book_meeting(
        "cadence:1",
        "Planning",
        "2099-08-17T10:00:00Z",
        30,
        "Europe/Prague",
        ["person@world.org"],
        "wf",
    )

    assert result["status"] == "booked"
    assert result["zoomJoinUrl"] == "https://zoom/j/1"
    event_id = events.insert_calls[0]["id"]
    assert event_id == client.MeetingSchedulerClient._calendar_event_id("cadence:1")
    assert "_" not in event_id


def test_reconcile_recovers_missing_zoom_join_url_before_marking_booked(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    scheduler = client.MeetingSchedulerClient()
    state = {
        "status": "blocked",
        "organizer_calendar_id": "organizer@world.org",
        "calendar_event_id": "event-1",
        "calendar_html_link": "https://calendar/event-1",
        "zoom_meeting_id": "zoom-1",
        "zoom_join_url": "",
        "requested_start": "2026-08-17T10:00:00+00:00",
        "actual_start": None,
        "time_zone": "Europe/Prague",
        "version": 1,
    }
    updates = []
    marked = {}

    async def existing(_key):
        return dict(state)

    async def update(_key, **values):
        updates.append(values)
        return None

    async def mark(_key, **values):
        marked.update(values)
        return {
            **state,
            "status": "booked",
            "actual_start": values["actual_start"].isoformat(),
            "zoom_join_url": values["join_url"],
        }

    class Request:
        def execute(self):
            return {"id": "event-1"}

    class Events:
        def get(self, **_kwargs):
            return Request()

    class FakeService:
        def events(self):
            return Events()

    monkeypatch.setattr(scheduler, "_get_existing", existing)
    monkeypatch.setattr(scheduler, "_update_provider_state", update)
    monkeypatch.setattr(scheduler, "_mark_booked", mark)
    monkeypatch.setattr(client, "get_calendar_service", lambda: FakeService())

    class Connection:
        async def execute(self, *_args):
            return None

    async def lock(_key, operation):
        return await operation(Connection())

    monkeypatch.setattr(client, "_with_occurrence_lock", lock)

    def zoom_request(method, path, **_kwargs):
        if method == "GET" and path == "/meetings/zoom-1":
            return {"id": "zoom-1", "join_url": "https://zoom/j/1"}
        raise AssertionError((method, path))

    monkeypatch.setattr(scheduler, "_zoom_request", zoom_request)
    result = scheduler.get_or_reconcile_meeting("cadence:1")

    assert result["status"] == "booked"
    assert result["providerState"] == {"calendarPresent": True, "zoomPresent": True}
    assert marked["join_url"] == "https://zoom/j/1"
    assert updates == [{"join_url": "https://zoom/j/1"}]


def test_reconcile_marks_lost_provider_pair_retryable(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    scheduler = client.MeetingSchedulerClient()
    state = {
        "status": "booked",
        "organizer_calendar_id": "organizer@world.org",
        "calendar_event_id": "event-1",
        "zoom_meeting_id": "zoom-1",
        "zoom_join_url": "https://zoom/j/1",
        "requested_start": "2099-08-17T10:00:00+00:00",
        "actual_start": "2099-08-17T10:00:00+00:00",
    }
    errors = []

    async def existing(_key):
        return dict(state)

    async def mark_error(_key, message):
        errors.append(message)

    class Request:
        def execute(self):
            raise RuntimeError("calendar event disappeared")

    class Events:
        def get(self, **_kwargs):
            return Request()

    class FakeService:
        def events(self):
            return Events()

    monkeypatch.setattr(scheduler, "_get_existing", existing)
    monkeypatch.setattr(scheduler, "_mark_error", mark_error)
    monkeypatch.setattr(client, "get_calendar_service", lambda: FakeService())

    async def lock(_key, operation):
        return await operation(object())

    monkeypatch.setattr(client, "_with_occurrence_lock", lock)
    monkeypatch.setattr(
        scheduler,
        "_zoom_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("zoom missing")),
    )

    result = scheduler.get_or_reconcile_meeting("cadence:2026-08-17")

    assert result["status"] == "blocked"
    assert result["providerState"] == {"calendarPresent": False, "zoomPresent": False}
    assert errors == ["provider state is incomplete and requires reconciliation"]


def test_booked_cadence_reconciles_existing_providers_and_preserves_attendee_removals(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("MEETING_ORGANIZER_CALENDARS", '{"wf":"organizer@world.org"}')
    scheduler = client.MeetingSchedulerClient()
    state = {
        "status": "booked",
        "cadence_id": "weekly-sync",
        "request_id": "weekly-sync:2026-08-24",
        "title": "Old title",
        "duration_minutes": 30,
        "organizer_calendar_key": "wf",
        "organizer_calendar_id": "organizer@world.org",
        "attendee_emails": ["removed@world.org"],
        "actual_start": "2099-08-24T08:00:00+00:00",
        "requested_start": "2099-08-24T08:00:00+00:00",
        "time_zone": "Europe/Prague",
        "calendar_event_id": "event-1",
        "calendar_html_link": "https://calendar/event-1",
        "zoom_meeting_id": "zoom-1",
        "zoom_join_url": "https://zoom/j/1",
        "version": 2,
    }
    zoom_calls = []
    calendar_updates = []

    monkeypatch.setattr(
        scheduler,
        "_claim_occurrence_row",
        lambda *_args, **_kwargs: _async_value((state, False)),
    )
    monkeypatch.setattr(
        scheduler,
        "_zoom_request",
        lambda method, path, **kwargs: zoom_calls.append((method, path, kwargs)) or {},
    )

    class Request:
        def __init__(self, value):
            self.value = value

        def execute(self):
            return self.value

    class Events:
        def get(self, **_kwargs):
            return Request({"id": "event-1"})

        def update(self, **kwargs):
            calendar_updates.append(kwargs)
            return Request({"id": "event-1", "htmlLink": "https://calendar/event-1"})

    class FakeService:
        def events(self):
            return Events()

    monkeypatch.setattr(client, "get_calendar_service", lambda: FakeService())
    reconciled = {}

    async def mark(_connection, **kwargs):
        reconciled.update(kwargs)
        return {**state, "title": kwargs["title"], "duration_minutes": kwargs["duration"]}

    monkeypatch.setattr(scheduler, "_reconcile_booked_row", mark)

    class Connection:
        async def execute(self, *_args):
            return None

    async def lock(_key, operation):
        return await operation(Connection())

    monkeypatch.setattr(client, "_with_occurrence_lock", lock)
    result = scheduler.book_meeting(
        "weekly-sync:2026-08-24",
        "New title",
        "2099-08-24T09:00:00Z",
        45,
        "Europe/Prague",
        ["new@world.org"],
        "wf",
        cadence_id="weekly-sync",
        request_id="weekly-sync:2026-08-24",
    )

    assert result["reconciled"] is True
    assert zoom_calls[0][0:2] == ("PATCH", "/meetings/zoom-1")
    assert zoom_calls[0][2]["payload"] == {
        "topic": "New title",
        "start_time": "2099-08-24T09:00:00Z",
        "timezone": "Europe/Prague",
        "duration": 45,
    }
    assert calendar_updates[0]["sendUpdates"] == "all"
    assert [item["email"] for item in calendar_updates[0]["body"]["attendees"]] == [
        "removed@world.org",
        "new@world.org",
    ]
    assert reconciled["attendees"] == ["removed@world.org", "new@world.org"]


def test_cadence_retry_preserves_manual_reschedule_for_same_anchor(monkeypatch):
    monkeypatch.setenv("MEETING_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("MEETING_ORGANIZER_CALENDARS", '{"wf":"organizer@world.org"}')
    scheduler = client.MeetingSchedulerClient()
    state = {
        "status": "booked",
        "cadence_id": "weekly-sync",
        "request_id": "weekly-sync:2026-08-24",
        "title": "Weekly sync",
        "duration_minutes": 30,
        "organizer_calendar_key": "wf",
        "organizer_calendar_id": "organizer@world.org",
        "attendee_emails": ["person@world.org"],
        "requested_start": "2099-08-24T10:00:00+00:00",
        "actual_start": "2099-08-24T11:00:00+00:00",
        "time_zone": "Europe/Prague",
        "calendar_event_id": "event-1",
        "zoom_meeting_id": "zoom-1",
        "zoom_join_url": "https://zoom/j/1",
        "version": 2,
    }
    provider_calls = []

    async def claim(*_args, **_kwargs):
        return state, False

    monkeypatch.setattr(scheduler, "_claim_occurrence_row", claim)
    monkeypatch.setattr(
        scheduler,
        "_zoom_request",
        lambda *args, **kwargs: provider_calls.append((args, kwargs)) or {},
    )

    class Connection:
        async def execute(self, *_args):
            return None

    async def lock(_key, operation):
        return await operation(Connection())

    monkeypatch.setattr(client, "_with_occurrence_lock", lock)
    result = scheduler.book_meeting(
        "weekly-sync:2026-08-24",
        "Weekly sync",
        "2099-08-24T10:00:00Z",
        30,
        "Europe/Prague",
        ["person@world.org"],
        "wf",
        cadence_id="weekly-sync",
        request_id="weekly-sync:2026-08-24",
    )

    assert result["actualStart"] == "2099-08-24T11:00:00Z"
    assert result["zoomJoinUrl"] == "https://zoom/j/1"
    assert provider_calls == []


def test_public_scheduler_methods_have_explicit_tool_signatures():
    assert "**kwargs" not in str(inspect.signature(client.book_meeting))
    assert "**kwargs" not in str(inspect.signature(client.reschedule_meeting))
    assert "**kwargs" not in str(inspect.signature(client.cancel_meeting))
