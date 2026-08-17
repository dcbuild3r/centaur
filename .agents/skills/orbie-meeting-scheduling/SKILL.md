---
name: orbie-meeting-scheduling
description: Find, book, reschedule, and cancel governed World Foundation meetings through Google free/busy, designated calendars, and World Foundation Zoom. Use for requests to find time, book a meeting, reschedule, cancel, or schedule an Auto-book cadence.
---

# Orbie Meeting Scheduling

Use the authenticated `meeting_automation` workflow broker for every operation;
the workflow is the only caller that receives the narrow `meeting-scheduler`
role. Never expose raw Google or Zoom credentials, generic Calendar writes,
private event details, or arbitrary calendar IDs to a Slack or Console user.

The broker accepts `find_availability`, `book_meeting`, `reschedule_meeting`,
`cancel_meeting`, and `get_or_reconcile_meeting` requests through the approved
Console scheduling route or the Slack scheduling ingress. Do not call the raw
provider tool from a user-facing session.

## Availability

1. Resolve every attendee to exactly one verified World identity and use its
   exact email address.
2. Ask for duration, date range, timezone, working hours, and the managed
   organizer-calendar alias.
3. Submit `find_availability` through the workflow broker. Present only
   free/busy-derived candidate start
   and end times, with timezone and attendee list; do not summarize conflicts.

## Ad-hoc booking or rescheduling

Show the selected slot, duration, timezone, organizer alias, attendees, and
the World Foundation Zoom requirement. Wait for an unambiguous confirmation in
the current conversation before calling `book_meeting` or `reschedule_meeting`.
Use a stable request/occurrence key and pass the confirmation token only after
the user has explicitly confirmed the exact slot. A stale reschedule version
must be re-read and presented again. Cancellation also requires explicit
confirmation.

## Cadences

Route cadence scheduling through the owner/authenticated `meeting_automation`
workflow. Only a Published cadence with `Calendar booking = Auto-book`, a
managed `Organizer calendar`, a positive booking window, a positive duration,
and cleanly resolved participants may book automatically. Existing `Off`
cadences remain Docs-only.

The workflow books or reconciles one occurrence, writes the booking status and
Zoom URL to Notion, runs the existing Docs worker with the actual booked time,
delivers Slack notifications, and advances `Next date` only after delivery.
Retries reuse the same occurrence and provider pair. A reschedule moves that
occurrence only; it never changes the recurrence anchor or creates a second
pair.

Fail closed when no common slot, organizer permission, Zoom link, Calendar
write, Docs run, or Slack acknowledgement is available. Leave `Next date`
unchanged and report the owner-facing retry state.
