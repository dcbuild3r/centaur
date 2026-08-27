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

The scheduled workflow also polls ended booked occurrences until both Zoom's
processed summary and cloud-recording transcript are ready. It publishes the
summary and bounded transcript to the cadence's
existing Notion page, using an `ORBiE_ZOOM_SUMMARY:<occurrence_key>` marker so
retries cannot append duplicates. It then DMs attendee emails that resolve to
active World Slack users. Public cadences additionally announce the canonical
Notion page in their configured channel; private cadence access is never
broadened. Ad-hoc meetings receive the bounded transcript excerpt in Slack
because they have no cadence page. Delivery is marked complete only after all
required publication and Slack sends succeed. Missing or still-processing Zoom
artifacts remain retryable, and unresolved attendee emails are reported rather
than sent to a broader audience.

Client credentials and token material must not appear in a cadence, skill,
Slack message, repository, Terraform state, or runtime environment variable.
Live activation also requires the Calendar free/busy/event scopes, the
`orbie-automation@world.org` free/busy shares, writable shares for the
calendars of approved manual proposers, and an explicit organizer alias for
automated cadences.
