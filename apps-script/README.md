# Meeting Ops Google Docs Worker

Apps Script is the Google-native worker for Meeting Ops. Orbie owns cadence
configuration, access checks, and Slack delivery; this project makes a full
native copy of the configured Google Docs template, preserves its tab tree and
native structures, replaces the date at the top of `Meeting Notes`, keeps the
separate `Format` tab, and exposes an idempotent notification outbox for Orbie.

Cadences have two sources:

- Public cadences are published in the Notion **Cadences** page/database.
- Private cadences are created in a copy of the **Orbie Private Cadence
  Template** kept in the owner's private World Foundation pages. The owner
  invites `orbie-automation@world.org` to that database, and Orbie normalizes
  its Notion row into the worker contract with the explicit
  `ownerSlackUserId` and `notificationRecipients` required for private
  delivery. The worker contract also accepts optional `accessSlackUserIds`
  for future private team-cadence sources.

The worker never receives Notion or Slack credentials in a cadence payload.

## Setup

1. Create an Apps Script project owned by the service identity that can read
   the pilot source Docs and write to the output folders.
2. Copy `.clasp.example.json` to the ignored `.clasp.json`, replace its
   `scriptId`, then run `clasp push` from this directory. The script is not
   deployable until the pilot IDs are supplied.
3. In Apps Script **Project Settings → Script properties**, set:
   - `CADENCE_CONFIG_JSON`: the normalized cadence array supplied by Orbie.
     `MEETING_CONFIG_JSON` remains a backwards-compatible fallback.
     Each cadence may set `templateTabName` for the preserved format tab and
     `notesTabName` for the dated notes layout; they default to `Template` and
     `Meeting Notes`, respectively. Document names support `{YYYY-MM-DD}` and
     the two-digit ISO week placeholder `{week}`.
   - `ALLOWED_WF_CHANNEL_IDS`: comma-separated Slack channel IDs approved for
     this project. This is a fail-closed allowlist; WF-TFH channels are not
     permitted.
4. Do not install Apps Script time-driven triggers. Orbie owns cadence
   scheduling and invokes the worker through the Execution API.

## Orbie handoff contract

Orbie invokes `runCadenceJob({ cadenceId, requesterSlackUserId, now,
customInstructions? })` through the Apps Script Execution API. `now` is the
manual request time, and `customInstructions` is optional plain text bounded to
4,000 characters after control-character removal and whitespace normalization.
`getAuthorizedCadences({
requesterSlackUserId, requesterSlackTeamId })` returns only active public
cadences and private cadences where the caller is the owner, has access, or is
an explicit notification recipient. The worker returns the created document
URL.

The Meeting Automation workflow reads
`getPendingOrbieNotificationsForCaller({ requesterSlackUserId,
requesterSlackTeamId })`, posts only those private payloads to the trusted DM,
and calls `acknowledgeOrbieNotificationForCaller({ notificationId,
requesterSlackUserId, requesterSlackTeamId })` only after Slack confirms
delivery. Public cadences are reported directly to the caller's DM; their
allowlisted public-channel outbox entry is not consumed by that workflow.

The legacy unscoped `getPendingOrbieNotifications()` and
`acknowledgeOrbieNotification()` functions remain for the existing operator
handoff, but are not used by the caller-facing workflow.

Those are the project's only public Execution API functions; all helpers use
Apps Script's trailing-underscore private naming convention. Re-running
`runCadenceJob` also checks whether the prior occurrence's delayed notes
notification is due.

Public notification payloads contain an allowlisted WF channel. Private
payloads are stored once per recipient and contain one `recipientSlackUserId`
with no channel. Every run requires Orbie's authenticated Slack caller context
and queues only that caller's payload. Orbie delivers it to the trusted DM after
applying the owner/access policy. A caller-scoped acknowledgement cannot consume
another recipient's entry.

The worker currently supports `weekly`; Notion can retain the future
`cadenceCron` value so Orbie can add timezone-aware recurrence later. A manual
run reuses an existing eligible occurrence; otherwise it uses the request time
as a one-off occurrence, even when `nextOccurrenceAt` is future-dated or the
scheduled occurrence is stale. One-off manual runs do not advance
`NEXT_OCCURRENCE`. The default `processAgenda_` helper remains
scheduled-windowed for any scheduled caller.

## Idempotency and failure behavior

- A script lock serializes overlapping trigger executions.
- A document is looked up by output folder and resolved title before creation.
- Agenda and notes notifications are recorded in Script Properties per meeting,
  occurrence, and private requester, so each authorized user can validate the
  same document once while retries from that user remain duplicate-free.
- The generated document is a full native copy of the source template. For the
  Weekly Sync template, `Meeting Notes` retains its prompts, progress sections,
  decisions, and feedback table while `Format` remains a separate tab.
- When supplied, custom instructions are inserted as plain text immediately
  after the date in a newly created `Meeting Notes` tab. Retries never insert
  them into an existing copy, and attendee-entered notes are not overwritten.
- Retries reuse the recorded occurrence document and verify only that its
  required tabs remain available. They do not compare its body with the
  evolving source template, replace attendee-edited content, or reset a
  human-edited Drive title. A missing required tab fails closed without
  creating another document; only an explicitly trashed occurrence document
  is replaced.
- If template copying, tab validation, or safe date replacement fails, the
  newly created file is trashed and the occurrence is not advanced.
- Public outbox entries are keyed by cadence, occurrence, and notification
  kind. Private entries add the recipient Slack user ID to the key.
- Apps Script holds no Slack credential and cannot deliver Slack messages
  directly.

## Local validation

From the repository root:

```sh
bun test apps-script/test/pure.test.js
```

Live pilot validation still requires the real Google identity, an authenticated
Apps Script Execution API caller using the executable deployment ID, the Notion
Cadences schema, and Orbie’s live Slack delivery. A green local test does not
prove the user-visible end-to-end surface.
