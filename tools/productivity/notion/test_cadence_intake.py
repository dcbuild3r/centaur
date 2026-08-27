from datetime import datetime

from notion.cadence_intake import (
    build_cadence_proposal,
    infer_cadence_defaults,
    resolve_document_name,
    stable_automation_id,
)


def test_known_weekly_all_hands_defaults_are_human_facing() -> None:
    defaults = infer_cadence_defaults(
        "World Foundation Weekly All Hands",
        now=datetime.fromisoformat("2026-08-24T12:00:00+02:00"),
    )

    assert defaults.frequency == "Weekly"
    assert defaults.next_date == "2026-08-24"
    assert defaults.time_zone == "Europe/Prague"
    assert defaults.meeting_time == "16:00"
    assert defaults.notification_time == "09:00"
    assert defaults.slack_channel_name == "#wf-all"
    assert defaults.document_name_template == "CW{week} World Foundation Weekly All Hands"


def test_explicit_values_override_workspace_conventions() -> None:
    defaults = infer_cadence_defaults(
        "World Foundation Weekly All Hands",
        next_date="2026-09-07",
        time_zone="UTC",
        meeting_time="17:30",
        notification_time="08:45",
        slack_channel_name="#custom-channel",
        document_name_template="All Hands — {YYYY-MM-DD}",
    )

    assert defaults.next_date == "2026-09-07"
    assert defaults.time_zone == "UTC"
    assert defaults.meeting_time == "17:30"
    assert defaults.notification_time == "08:45"
    assert defaults.slack_channel_name == "#custom-channel"
    assert defaults.document_name_template == "All Hands — {YYYY-MM-DD}"
    assert defaults.inferred_fields == ()


def test_private_cadence_does_not_infer_the_public_all_hands_channel() -> None:
    defaults = infer_cadence_defaults(
        "World Foundation Weekly All Hands",
        visibility="private",
        next_date="2026-08-31",
    )

    assert defaults.slack_channel_name == ""


def test_non_weekly_cadence_requires_first_occurrence() -> None:
    try:
        infer_cadence_defaults("Monthly Leadership Review", frequency="Monthly")
    except ValueError as error:
        assert "next_date is required" in str(error)
    else:
        raise AssertionError("monthly cadence without a first occurrence must be rejected")


def test_proposal_omits_internal_identifiers_and_emails() -> None:
    proposal = build_cadence_proposal(
        "World Foundation Weekly All Hands",
        now=datetime.fromisoformat("2026-08-24T12:00:00+02:00"),
    )

    rendered = proposal.render()
    assert "CW35 World Foundation Weekly All Hands" in rendered
    assert "Monday 2026-08-24" in rendered
    assert "Friday at 09:00" in rendered
    assert "automation_id" not in rendered
    assert "channel_id" not in rendered
    assert "@world.org" not in rendered
    assert "template" not in rendered.casefold()
    assert "Reply 'confirm' to create this as a Draft." in rendered


def test_document_name_resolves_iso_week_boundaries() -> None:
    assert resolve_document_name(
        "CW{week} All Hands — {YYYY-MM-DD}",
        "2026-12-31",
        "UTC",
    ) == "CW53 All Hands — 2026-12-31"
    assert resolve_document_name("CW{week} All Hands", "2027-01-01", "UTC") == (
        "CW53 All Hands"
    )
    assert resolve_document_name("CW{week} All Hands", "2027-01-04", "UTC") == (
        "CW01 All Hands"
    )


def test_document_name_supports_calendar_week_alias() -> None:
    assert resolve_document_name(
        "CW{calendar_week} World Foundation Weekly All Hands",
        "2026-08-31",
        "UTC",
    ) == "CW36 World Foundation Weekly All Hands"


def test_stable_automation_id_is_canonical_and_opaque() -> None:
    values = {"cadence": "Weekly Sync", "owner_id": "person-1", "channel_id": "C123"}
    assert stable_automation_id(values) == stable_automation_id(
        {"channel_id": "C123", "owner_id": "person-1", "cadence": "Weekly Sync"}
    )
    assert stable_automation_id(values).startswith("cadence-")
    assert "Weekly Sync" not in stable_automation_id(values)
