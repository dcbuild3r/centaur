# Meeting Scheduler

This is the narrow, workflow-owned Calendar + Zoom capability for Orbie. It
must not be exposed to user-facing Slack or Console principals; the public
skill submits through the durable `meeting_automation` scheduling broker.
It returns free/busy-derived slots only and writes to managed organizer
aliases. Manual meetings are always created on Orbie's managed calendar, with
the verified proposer included as an attendee. Orbie-created events allow
guests to modify event details and invite others, giving participants
event-level collaboration without requiring write access to an employee
calendar. Every write is keyed by a stable
occurrence identity and is recorded in `orbie_meeting_occurrences` before
provider work begins.

Production Zoom access is a `brokered_token` minted from the dedicated
User-managed General OAuth app. Centaur Console serializes refreshes and stores
each rotated refresh token; the scheduler receives only the current bearer.
All meetings are owned by the configured Orbie Zoom user. Orbie never uses
`schedule_for` or another user's identity to create a room. Zoom requests use
the OAuth identity-bound `/users/me` endpoint, so the authorizing Orbie account
is always the owner. When Zoom rejects a request, the raised error keeps the
HTTP status and a bounded, redacted copy of Zoom's `code`, `message`, and
field-level `errors`; headers, URLs, tokens, and email addresses are never
retained. Booking failures persist that reason in the occurrence's
`last_error`. For crash-recovery discovery, each room carries an opaque hash of
the occurrence identity in Zoom's free-form agenda. The scheduler intentionally
does not send Zoom `tracking_fields`, because those fields must first be
configured account-wide by a Zoom administrator and otherwise make meeting
creation fail with HTTP 400. Legacy tracking-field discovery remains supported
for rooms created before this marker was introduced. Every created room
requests cloud recording; `get_recording`
returns bounded transcript content and `get_summary`
returns the AI Companion summary after Zoom has finished processing, without
exposing signed provider URLs.

Because Zoom ownership remains with Orbie, attendees cannot end a live room for
everyone. The confirmation-gated `end_meeting` operation lets an authorized
requester ask Orbie to end its own Zoom meeting through the provider status API.
It only accepts a recorded Orbie occurrence and deliberately keeps the Calendar
event intact so recording processing and post-meeting follow-up retain their
source metadata.

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
