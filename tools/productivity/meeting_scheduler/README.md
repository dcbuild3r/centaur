# Meeting Scheduler

This is the narrow, workflow-owned Calendar + Zoom capability for Orbie. It
must not be exposed to user-facing Slack or Console principals; the public
skill submits through the durable `meeting_automation` scheduling broker.
It returns free/busy-derived slots only and writes to either a managed
organizer alias for an automated cadence or the verified proposer's exact
calendar email for a manual meeting. Manual writes require that calendar to be
visible with `writer` or `owner` access; they must never fall back to the Orbie
automation calendar. Every write is keyed by a stable occurrence identity and
is recorded in `orbie_meeting_occurrences` before provider work begins.

Production Zoom access is expected to be a brokered `ZOOM_ACCESS_TOKEN` issued
for the World Foundation Server-to-Server OAuth app and licensed host. The
account/client credentials and token rotation belong in the managed secret
system; do not put them in a cadence, skill, Slack message, or repository.
Live activation also requires the Calendar free/busy/event scopes, the
`orbie-automation@world.org` free/busy shares, writable shares for the
calendars of approved manual proposers, and an explicit organizer alias for
automated cadences.
