# Private meeting notes plan

## Outcome

The meeting proposer explicitly chooses `public` or `private` while booking.
That classification is persisted with the occurrence and is never inferred
from attendees, title, channel, or Calendar visibility.

Every processed meeting has one canonical Notion page. Public meetings remain
in the shared Meeting Knowledge Repository. A private meeting's canonical page
is created only in a participant-restricted Notion parent and is indexed in
each participant's private Meeting Notes database without copying the
transcript or summary. Each private index row points at the canonical page, so
participant edits, attachments, and added notes remain on one shared page.

Notion pages have exactly one parent, so the same page cannot literally belong
to several databases. Per-user index rows are the only projection; they must
never become independent copies of the meeting content.

## Privacy invariants

1. `visibility` is an explicit, required booking choice (`public` or `private`)
   and is persisted through Calendar/Zoom creation and post-meeting processing.
   Existing callers default to `public` only during the migration window.
2. A private meeting must never use the public repository as its canonical
   parent. If a participant-only parent or verified participant ACL cannot be
   established, publication fails closed and no note link is sent.
3. Slack identity is established by the signed ingress broker. Caller-supplied
   user IDs or emails are not authorization.
4. Private recipients are derived from the persisted meeting attendee set,
   resolved to active workspace identities. Request payload recipients cannot
   broaden access after booking.
5. A user can query only the private database registered for their authenticated
   Slack user ID. Public notes are queryable separately.
6. Private publication uses the separate `notion-private-meetings` tool and
   `NOTION_PRIVATE_MEETINGS_API_KEY`. That tool exposes only `query_database`
   and `create_page`, is assigned only to `workflow-meeting-automation`, and is
   never assigned to Slack users, channels, or ordinary Orbie sessions. The
   existing generic Notion integration must not be invited to private meeting
   databases.
7. Private-database mappings are deployment configuration, not workflow input.
   Unknown users fail closed and receive no private projection.
8. Private index rows contain metadata and a canonical-page link only. They do
   not duplicate transcripts, summaries, action items, or user-added content.
9. Publication is idempotent by occurrence key in both the canonical repository
   and every private index database.
10. A private query returns bounded meeting metadata and canonical links from the
   authenticated caller's own index. It cannot select an arbitrary database.
11. Only resolved participants receive the private meeting Slack notification.
    Public meetings retain the existing notification behavior.

## Interfaces and seams

- **Publication seam:** `publish_notion_meeting_summary` creates/reuses the
  public canonical page. `publish_private_notion_meeting_summary` creates/reuses
  a canonical page beneath a participant-restricted parent only after access is
  verified. `publish_private_meeting_reference` creates/reuses an opaque
  per-user index row after the canonical page exists.
- **Authorization seam:** the signed Slack broker passes the authenticated user
  to `meeting_automation`; the workflow resolves that user against a server-side
  database mapping.
- **Query seam:** a purpose-bound workflow operation accepts a search string but
  derives the database from authenticated identity. It returns only the caller's
  private rows plus public rows.
- **Credential seam:** only the workflow principal holds the purpose-bound
  private-meeting Notion credential. Ordinary Orbie may retain generic Notion
  access for public workspace content, but that integration has no ACL to the
  private meeting databases.

## Rollout

1. Add a public/private choice to the booking interface and persist it on the
   occurrence. Add compatibility tests for existing public bookings.
2. Add strict parsing for `MEETING_PRIVATE_NOTION_DATABASES_JSON` and
   `MEETING_PRIVATE_NOTION_USER_IDS_JSON`, keyed by authenticated Slack user ID.
   The latter maps participants to Notion user IDs for the template's People
   property; neither mapping is accepted from a workflow request.
3. Add a participant-only canonical publication interface. Because Notion's
   public API cannot grant page access to individual users, enable private
   publication only where the deployment has a pre-provisioned restricted
   parent for the exact participant set or an approved sharing broker. Verify
   access before writing content or sending links.
4. Add idempotent private index publication and project the configured attendees
   after canonical publication.
5. Add the signed private-query broker operation and bounded result rendering.
6. Reconcile roles so only the workflow principal retains Notion access; add a
   deployment verifier for this invariant.
7. Publish a cloneable Meeting Notes database template containing at least
   `Meeting`, `Date`, `Occurrence Key`, `Visibility`, `Participants`, and
   `Canonical note`. Cloning is followed by a one-time authenticated enrollment
   that records the clone's database ID server-side and verifies the integration
   can write to it; a caller can never submit a database ID per request.
8. Provision one private Meeting Notes database for the initial user and place
   its mapping in managed deployment configuration only after an operator has
   confirmed that it lives under that user's Private pages, has no unintended
   guests, and exposes only the `Orbie Private Meetings` connection. Notion's
   API does not expose guest ACLs, so this approval is an operator assertion;
   API reachability and schema are verified separately.
9. Deploy to Dev and run a real private meeting through Zoom webhook, canonical
   publication, private index creation, caller-scoped query, and Slack delivery.
10. Enable additional users only after their private database is provisioned and
   the multi-member projection can be tested with their explicit participation.

## Initial limitation

The first rollout provisions only the requesting user's private database and a
private canonical parent accessible only to that user. Multi-participant private
meetings remain disabled until participant-only canonical access and at least
two independent private database projections can be proven. Unmapped
participants receive neither a private projection nor a private note link. This
is a deliberate fail-closed limitation, not a fallback to a shared database.
