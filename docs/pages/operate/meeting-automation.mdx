---
title: Meeting Automation
description: Run owner-scoped Google Docs meeting cadences from an Orbie Slack DM.
---

# Meeting Automation

World Foundation Slack users can run an authorized meeting cadence by sending
Orbie a direct message. No per-user Google identity, Centaur Console role, or
infrastructure grant is required.

Use one of these forms:

```text
run cadence <cadence id or title>
run meeting automation <cadence id or title>
meeting ops <cadence id or title>
```

Orbie acknowledges the durable run, creates or reuses the agenda document, and
posts the result back to the same DM. Replaying the same Slack message reuses
the workflow run and does not create another document or message.

## Access model

The Slack ingress supplies the caller identity and existing DM channel. The
broker accepts requests only from the World Foundation Slack workspace and
does not accept a caller, recipient, channel, document, or folder override from
the user or agent.

Public cadences are available to World Foundation Slack users. A private
cadence is visible only to its owner, `accessSlackUserIds`, and explicit
notification recipients. Unknown and unauthorized cadences return the same
user-facing outcome so private cadence names are not disclosed.

The durable `workflow-meeting-automation` principal is the only principal with
the `meeting_ops` role and Google OAuth grant. Individual Slack principals do
not receive the raw Google tool or shared outbox. Apps Script stores one private
notification per recipient; the workflow reads and acknowledges only the
requester's item, and only after Slack confirms delivery.

## Cadence source

Orbie normalizes public entries from the Notion **Cadences** database and
owner-scoped private definitions into `CADENCE_CONFIG_JSON` in Apps Script.
Apps Script remains a Google Docs worker: it does not receive Notion or Slack
credentials and does not decide who the Slack caller is.

## Deployment checks

After deployment, verify all of the following:

1. `meeting_automation` appears in workflow discovery and its workflow
   principal is registered.
2. Only `workflow-meeting-automation` resolves the `meeting_ops` role.
3. A World Slack DM can queue an authorized cadence.
4. An unrelated user cannot resolve a private cadence.
5. Slack delivery succeeds before acknowledgement.
6. Replaying the same Slack message produces no duplicate document or message.

Do not grant `meeting_ops` directly to Slack user, channel, or warm-pool
principals.
