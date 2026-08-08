# Meeting Ops

`meeting-ops` is the narrow Orbie-facing client for the Google Apps Script
Meeting Ops worker. It exposes only the three approved functions needed for
the Docs/Slack handoff:

- `run_cadence(cadence_id, now=None)` creates or reuses an agenda Doc.
- `pending_notifications()` reads the durable Apps Script outbox.
- `acknowledge_notification(notification_id)` removes an outbox item only
  after Orbie has confirmed Slack delivery.

The target Apps Script executable deployment ID is fixed by the
`MEETING_OPS_SCRIPT_ID` grant. Google names the REST path parameter `scriptId`,
but the Execution API requires the deployment ID returned by the deployment
resource. It is not a method argument, so a caller cannot execute another Apps
Script deployment.
`GOOGLE_TOKEN_JSON` remains behind iron-proxy; the sandbox receives only a
path placeholder and proxy-injected short-lived OAuth access token.

## CLI

```bash
meeting-ops run-cadence private-weekly --now 2026-08-07T12:00:00Z
meeting-ops notifications
meeting-ops acknowledge private-weekly:2026-08-07:agenda
```

Slack delivery remains Orbie's responsibility. An outbox item must not be
acknowledged until the Slack API confirms the corresponding message.
The outbox spans all configured cadences, so production grants must remain
exclusive to Orbie's automation principal rather than individual end users.
