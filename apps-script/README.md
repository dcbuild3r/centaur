# Meeting Ops Google Docs Worker

Apps Script is the Google-native worker for Meeting Ops. Orbie owns cadence
configuration, access checks, and Slack delivery; this project copies the
`Template` tab into a new Google Doc and exposes an idempotent notification
outbox for Orbie.

Cadences have two sources:

- Public cadences are published in the Notion **Cadences** page/database.
- Private cadences are created in an owner’s Orbie DM and carry explicit
  `ownerSlackUserId`, `accessSlackUserIds`, and `notificationRecipients`.

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
     Each cadence may set `templateTabName`; it defaults to `Template`.
   - `ALLOWED_WF_CHANNEL_IDS`: comma-separated Slack channel IDs approved for
     this project. This is a fail-closed allowlist; WF-TFH channels are not
     permitted.
4. Do not install Apps Script time-driven triggers. Orbie owns cadence
   scheduling and invokes the worker through the Execution API.

## Orbie handoff contract

Orbie invokes `runCadenceJob({ cadenceId, now })` through the Apps Script
Execution API. The worker returns the created document URL. Orbie then reads
`getPendingOrbieNotifications()`, posts each payload through its existing
Slack runtime, and calls `acknowledgeOrbieNotification(notificationId)` only
after Slack confirms delivery.

Those are the project's only public Execution API functions; all helpers use
Apps Script's trailing-underscore private naming convention. Re-running
`runCadenceJob` also checks whether the prior occurrence's delayed notes
notification is due.

Public notification payloads contain an allowlisted WF channel. Private
payloads contain recipient Slack user IDs and no channel; Orbie delivers those
as DMs after applying the owner/access policy.

The worker currently supports `weekly`; Notion can retain the future
`cadenceCron` value so Orbie can add timezone-aware recurrence later. Each
cadence starts from `nextOccurrenceAt` and advances by one week after the
agenda job is created.

## Idempotency and failure behavior

- A script lock serializes overlapping trigger executions.
- A document is looked up by output folder and resolved title before creation.
- Agenda and notes notifications are recorded in Script Properties per meeting
  and occurrence, so retries do not duplicate Slack posts.
- If template copying or placeholder replacement fails, the newly created file
  is trashed and the occurrence is not advanced.
- Orbie outbox entries are keyed by cadence, occurrence, and notification kind.
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
