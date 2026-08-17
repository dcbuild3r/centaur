# Meeting Ops

`meeting-ops` is the narrow Orbie-facing client for the Google Apps Script
Meeting Ops worker. It exposes caller-scoped functions for the Docs/Slack
handoff:

- `authorized_cadences(user_id, team_id)` lists public and permitted private
  cadences.
- `run_cadence(cadence_id, requester_slack_user_id=...,
  requester_slack_team_id=...)` creates or reuses a full native copy of the
  configured template, dates its `Meeting Notes` tab, preserves the separate
  `Format` tab and other native structures, and re-checks private access in
  Apps Script.
- `pending_notifications_for_caller(user_id, team_id)` reads only that user's
  private notifications, or a private-channel notification initiated by that
  caller.
- `acknowledge_notification(notification_id, requester_slack_user_id=...,
  requester_slack_team_id=...)` removes only that user's item after Orbie has
  confirmed Slack delivery.

The target Apps Script executable deployment ID is fixed by the
`MEETING_OPS_SCRIPT_ID` grant. Google names the REST path parameter `scriptId`,
but the Execution API requires the deployment ID returned by the deployment
resource. It is not a method argument, so a caller cannot execute another Apps
Script deployment.
`GOOGLE_TOKEN_JSON` remains behind iron-proxy; the sandbox receives only a
path placeholder and proxy-injected short-lived OAuth access token.

Calendar and Zoom booking do not belong to this tool. Apps Script remains a
Docs-only worker with its existing scopes; the durable `meeting_automation`
workflow calls the separately governed `meeting-scheduler` capability before
invoking `run_scheduled_cadence`.

## CLI

```bash
meeting-ops cadences --requester-slack-user-id U123 --requester-slack-team-id TL1HM8UUU
meeting-ops run-cadence private-weekly \
  --requester-slack-user-id U123 --requester-slack-team-id TL1HM8UUU \
  --now 2026-08-07T12:00:00Z
meeting-ops notifications \
  --requester-slack-user-id U123 --requester-slack-team-id TL1HM8UUU
meeting-ops acknowledge agenda:private-weekly:2026-08-07:U123 \
  --requester-slack-user-id U123 --requester-slack-team-id TL1HM8UUU
```

Slack delivery remains Orbie's responsibility. An outbox item must not be
acknowledged until the Slack API confirms the corresponding message.
Private DM outbox entries are created once per recipient; a private `G...`
channel notification is created once per channel request. Production grants
must remain exclusive to the Meeting Automation workflow principal rather than
individual end users. Public-channel notifications remain in the public
outbox and are intentionally not consumed by the caller-scoped worker.
An immediate retry must reuse the same Doc and must not duplicate the
notification or overwrite any attendee-entered notes.
