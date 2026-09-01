# Meeting Scheduler

This is the narrow, workflow-owned Calendar + Zoom capability for Orbie. It
must not be exposed to user-facing Slack or Console principals; the public
skill submits through the durable `meeting_automation` scheduling broker.
It returns free/busy-derived slots only and writes to managed organizer
aliases. Manual meetings are always created on Orbie's managed calendar, with
the verified proposer included as an attendee; the scheduler never requires or
uses write access to an employee calendar. Every write is keyed by a stable
occurrence identity and is recorded in `orbie_meeting_occurrences` before
provider work begins.

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
Live activation also requires the Calendar read/event scopes, organization-wide
event-detail visibility for availability and day-agenda queries, and explicit
organizer aliases for Orbie-owned manual meetings and automated cadences.
