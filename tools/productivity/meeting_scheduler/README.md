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

Production Zoom access is a `brokered_token` minted from the dedicated
User-managed General OAuth app. Centaur Console serializes refreshes and stores
each rotated refresh token; the scheduler receives only the current bearer.
Meetings are owned by the configured Orbie host unless an organizer key is
explicitly mapped through `MEETING_ZOOM_SCHEDULE_FOR_USERS` and that user has
granted Zoom scheduling privilege to Orbie. Every created room requests cloud
recording; `get_recording` returns bounded transcript content and `get_summary`
returns the AI Companion summary after Zoom has finished processing, without
exposing signed provider URLs.

Client credentials and token material must not appear in a cadence, skill,
Slack message, repository, Terraform state, or runtime environment variable.
Live activation also requires the Calendar free/busy/event scopes, the
`orbie-automation@world.org` free/busy shares, writable shares for the
calendars of approved manual proposers, and an explicit organizer alias for
automated cadences.
