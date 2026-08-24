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

Treat this as an intent-first interactive command with four stages:

1. Understand the requested ritual and extract only values the user explicitly
   supplied.
2. Resolve safe defaults and internal identities without asking the user for
   implementation details.
3. Show one concise, human-readable proposal and wait for one explicit
   confirmation. This proposal must not write to Notion, Calendar, Slack, or
   Google Docs.
4. After confirmation, create exactly one Notion Draft.

The first response should ask only for missing safety-critical information. Do
not present a technical checklist and do not ask for Automation IDs, Slack
channel IDs, Notion emails, purpose, participant emails, or document-name
templates unless the user explicitly asks to control one of them.

Resolve values in this order:

1. Explicit user values.
2. A known World Foundation convention.
3. Safe workspace defaults.
4. One grouped follow-up for a value that is genuinely required but cannot be
   inferred.

For the known weekly all-hands convention, infer `Weekly`, Europe/Prague,
Monday at `16:00`, preparation/notification on Friday at `09:00`, `#wf-all`,
and the internal document template `CW{week} <ritual>`. Other weekly cadences
use the safe `10:00` meeting and `09:15` preparation defaults unless the user
provides different values. Monthly and quarterly cadences require an explicit
first occurrence when one cannot be inferred.

Resolve Slack destinations with the Slack channel resolver. Accept a channel
name, `#channel`, `<#CHANNEL_ID|channel>` mention, or the current Slack
conversation. Keep the resolved ID and membership check internal, and pass
both the resolved ID and display name to Notion. Prefer an explicit reference,
then current conversation, then the known convention. Never substitute a
similarly named channel after an ambiguous lookup.

Resolve the Slack requester through the existing bounded Slack/Notion address
book and use that identity as `Owner / DRI`. Resolve notification recipients
from Slack mentions, names, or existing context. Keep raw emails and Notion
person IDs internal; never repeat them in the Slack response.

`purpose` is optional. Participants are optional for Docs-only cadences. For
`Calendar booking: Auto-book`, require participants that resolve to exact
verified World identities, a positive duration, the managed organizer calendar,
and a positive booking window. Ask for participant names or Slack mentions,
not email addresses, when resolution is missing. New cadences remain Draft.

Generate document names automatically. `{YYYY-MM-DD}` remains supported and
`{week}` expands to the two-digit ISO week (`01` through `53`). Show only the
resolved document name in the proposal. Do not show the raw template.

The proposal should use human language and include only:

- ritual title;
- frequency, first occurrence, meeting time, and timezone;
- notification time and preparation day;
- resolved Slack channel, if any;
- resolved document name; and
- whether Calendar booking is off or auto-booked.

End it with: `Reply 'confirm' to create this as a Draft.` Do not create the
Draft until the user confirms. On confirmation, call the Notion tool's
`create_cadence` operation (or the bundled `notion create-cadence` command)
with the resolved internal values.

Before the first write in a workspace, ensure the Cadences database has the
Calendar booking fields (`Calendar booking`, `Organizer calendar`, `Booking
window (business days)`, `Booking status`, `Booked start`, and `Booked meeting
URL`). The Notion client exposes this as `ensure_cadence_booking_schema` and
`create_cadence` performs the idempotent schema update as well.

1. Resolve the creator and every Notion profile to a Notion person before
   writing. Email recipients are stored in `Notification emails` and are also
   resolved to a Notion person when the workspace has a unique matching
   profile; an email-only recipient remains valid for Slack matching. This is
   an internal resolution step, not a user-facing input requirement.
2. Store resolved people in `Owner / DRI` and `Notification recipients`; preserve
   every raw email fallback in `Notification emails`.
3. Set `Auto-created` to true, `Notification mode` to `Orbie`, and
   `Automation status` to `Draft`. Set `Document access` to `Cadence members`
   for private rows and `All World members` for public rows.
4. Use the generated stable internal ID as the idempotency key. Explicit
   legacy IDs remain accepted for compatibility. A retry or Slack redelivery
   must return the existing row rather than creating a duplicate in that target
   database.
5. Report only the ritual title, Draft status, page link, and next step: a
   responsible owner must review and change the row to `Published` before
   scheduled execution. Never relay Automation ID, Slack channel ID, Notion
   email, raw template, or internal error details.

Before rollout, verify that one proposal has no side effects, one confirmation
creates one Draft, and a repeated confirmation returns that Draft. Also run a
fresh session-creation smoke test and a cached/rate-limited Slack channel
resolution test. A 500 or duplicate request blocks rollout and is handled as a
separate reliability regression rather than hidden by the UX flow.

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
