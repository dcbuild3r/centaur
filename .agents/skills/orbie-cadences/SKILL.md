---
name: orbie-cadences
description: Create and run Notion-backed Orbie Meeting Ops cadences. Use for "create cadence", "orbie create cadence", and "orbie cadence create".
---

# Orbie Cadences

Use this skill when a World Foundation user asks Orbie to create, inspect, or
run a cadence. The Notion **Cadences** database is the source of truth. The
durable `meeting_automation` workflow schedules only rows whose
`Automation status` is `Published`; newly created rows are always `Draft`.

## `orbie cadence create`

Treat `create cadence` and `orbie create cadence` as exact aliases. These
phrases always mean a Meeting Ops cadence in the governed Notion Cadences
database; never ask whether the user means sales outreach or Slack reminders.

Treat this as an interactive command. Before creating anything, ask for all
fields in one structured checklist and wait for the user's answers. Do not
create a partial row, guess a Slack channel, or publish a row on the user's
behalf.

Collect:

- Ritual/title and a stable, unique `Automation ID`.
- Frequency: `Weekly`, `Bi-weekly`, `Monthly`, or `Quarterly`.
- Next meeting date/time in ISO format, IANA time zone, meeting time, and
  notification time.
- Preparation lead in business days (default `1`). A Monday meeting with a
  one-day lead is prepared on Friday.
- Google template URL and Google output-folder URL.
- Scope and destination: choose the shared World Foundation Cadences database
  for a public cadence, or provide the exact private Cadences database URL
  copied from the Orbie Private Cadence Template. For a private cadence, the
  caller must have invited `orbie-automation@world.org` to that database/page.
  A private destination may be omitted for owner/recipient DMs, or may specify
  the exact `G...` private Slack channel/group-DM ID and name.
  Treat an explicit channel ID as authoritative; never substitute a similarly
  named channel.
- Creator's Notion profile or exact email. The creator is always `Owner / DRI`.
  If the user supplies a different owner, stop and explain that the creator
  must remain the owner.
- Notification recipients as Notion profiles or exact email addresses, plus
  any additional notification emails.
- Participants, purpose, document-name template, cadence type, and audience.

Optional fields are duration, notes delay, notify lead, and notes/links. Use
the defaults `Europe/Prague`, `09:15`, `10:00`, `1`, `Internal WF`, and
`Everyone` only when the user accepts the defaults. Validate all supplied
values before writing.

For Calendar booking, collect `Calendar booking` (`Off` or `Auto-book`), the
managed `Organizer calendar` alias, and `Booking window (business days)`. An
`Auto-book` cadence must also have a positive integer `Duration (min)` and
Participants that resolve to exact verified World email identities. Keep
`Off` for existing Docs-only cadences. New cadences remain Draft regardless of
the selected booking mode.

After confirmation, create the row with the Notion tool's `create_cadence`
operation (or the bundled `notion create-cadence` command) using these rules:

Before the first write in a workspace, ensure the Cadences database has the
Calendar booking fields (`Calendar booking`, `Organizer calendar`, `Booking
window (business days)`, `Booking status`, `Booked start`, and `Booked meeting
URL`). The Notion client exposes this as `ensure_cadence_booking_schema` and
`create_cadence` performs the idempotent schema update as well.

1. Resolve the creator and every Notion profile to a Notion person before
   writing. Email recipients are stored in `Notification emails` and are also
   resolved to a Notion person when the workspace has a unique matching
   profile; an email-only recipient remains valid for Slack matching.
2. Store resolved people in `Owner / DRI` and `Notification recipients`; preserve
   every raw email fallback in `Notification emails`.
3. Set `Auto-created` to true, `Notification mode` to `Orbie`, and
   `Automation status` to `Draft`. Set `Document access` to `Cadence members`
   for private rows and `All World members` for public rows.
4. Use the stable `Automation ID` as the idempotency key. A retry must return
   the existing row rather than creating a duplicate in that target database.
5. Report the created/existing Notion page, its Draft status, and the exact
   next step: a responsible owner must review and change the row to
   `Published` before scheduled execution.

Never put Slack, Notion, Google, or OAuth credentials in a cadence row or in a
Slack message.

## `orbie cadence run <id or title>`

Use the existing owner-scoped manual Meeting Ops workflow. Resolve one exact
authorized cadence, then let Orbie create/reuse the native Google template
copy, send the configured Slack channel message or recipient DMs, and
acknowledge notifications only after Slack delivery succeeds. Replaying the
same request must be idempotent. Manual runs do not advance `Next date`.

Accepted aliases are `run cadence`, `run meeting automation`, and `meeting
ops`. The command may be issued from a World Foundation direct message or a
group DM containing Orbie; it must never be accepted from a public channel.

## Scheduled execution

The `meeting_automation` Centaur workflow wakes on its durable cron tick,
reads `Published` rows, computes preparation in the row's timezone using
business days, and for enabled Auto-book rows reconciles or books the stable
Calendar/Zoom occurrence before running the Google Docs worker. It drains the
notification outbox and advances `Next date` only after successful delivery.
The booking status, actual booked start, and Zoom URL are written back to
Notion. Keep the source template immutable, preserve the original cadence
anchor when an occurrence moves, and retry the same occurrence after any
Calendar, Zoom, Docs, or Slack failure.
