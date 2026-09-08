# Meeting Scheduler

This is the narrow, workflow-owned Calendar + Zoom capability for Orbie. It
must not be exposed to user-facing Slack or Console principals; the public
skill submits through the durable `meeting_automation` scheduling broker.
It returns free/busy-derived slots only and writes to a managed organizer alias
for both automated cadences and ad-hoc private meetings. Manual Slack requests
authenticate the requester and supply attendee email addresses, but do not
turn the requester or an attendee into the event organizer. Every write is
keyed by a stable occurrence identity and is recorded in
`orbie_meeting_occurrences` before provider work begins.

Production Zoom access is expected to be a brokered `ZOOM_ACCESS_TOKEN` issued
for the World Foundation Server-to-Server OAuth app and licensed host. The
account/client credentials and token rotation belong in the managed secret
system; do not put them in a cadence, skill, Slack message, or repository.
Live activation also requires the Calendar free/busy/event scopes, the
`orbie-automation@world.org` organizer/free-busy access, free/busy shares for
approved attendee calendars, and an explicit organizer alias for automated
cadences and ad-hoc private meetings.
