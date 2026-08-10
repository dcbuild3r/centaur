const { expect, test } = require('bun:test')
const fs = require('node:fs')
const path = require('node:path')
const pure = require('../src/pure.js')

global.Utilities = {
  formatDate(date, _timeZone, format) {
    if (format !== 'yyyy-MM-dd') throw new Error(`unexpected format: ${format}`)
    return date.toISOString().slice(0, 10)
  },
}

test('resolves the date placeholder without changing other text', () => {
  expect(pure.resolveDocName('All Hands — {YYYY-MM-DD}', new Date('2026-08-03T10:00:00Z'), 'UTC'))
    .toBe('All Hands — 2026-08-03')
})

test('escapes regex metacharacters for Apps Script replaceText', () => {
  expect(pure.escapeRegExp('{date}')).toBe('\\{date\\}')
})

test('agenda window includes the lead boundary and bounded late retry', () => {
  const occurrence = new Date('2026-08-05T12:00:00Z')
  expect(pure.isWithinAgendaWindow(new Date('2026-08-05T11:00:00Z'), occurrence, 60, 720)).toBe(true)
  expect(pure.isWithinAgendaWindow(new Date('2026-08-06T00:01:00Z'), occurrence, 60, 720)).toBe(false)
})

test('weekly cadence advances exactly one week', () => {
  expect(pure.nextWeeklyOccurrence(new Date('2026-08-05T12:00:00Z')).toISOString())
    .toBe('2026-08-12T12:00:00.000Z')
})

test('notes notification waits for the configured delay', () => {
  const occurrence = new Date('2026-08-05T12:00:00Z')
  expect(pure.shouldPost(new Date('2026-08-05T12:59:59Z'), occurrence, 60)).toBe(false)
  expect(pure.shouldPost(new Date('2026-08-05T13:00:00Z'), occurrence, 60)).toBe(true)
})

test('normalizes a public Notion cadence for Orbie delivery', () => {
  expect(pure.normalizeCadence({
    id: 'cadence-1',
    title: 'AI Workstream Weekly',
    sourceDocId: 'doc-1',
    outputFolderId: 'folder-1',
    nextOccurrenceAt: '2026-08-05T12:00:00Z',
    docNameTemplate: 'AI Workstream — {YYYY-MM-DD}',
    attendees: ['dc.builder@world.org'],
    notifyChannel: 'C123',
    notifyChannelName: '#wf-ai-workstream',
  })).toMatchObject({
    id: 'cadence-1',
    visibility: 'public',
    notificationMode: 'orbie',
    cadence: 'weekly',
    templateTabName: 'Template',
  })
})

test('normalizes an explicit Google Docs template tab name', () => {
  expect(pure.normalizeCadence({
    id: 'private-format',
    title: 'Private format',
    sourceDocId: 'doc-1',
    outputFolderId: 'folder-1',
    nextOccurrenceAt: '2026-08-07T12:00:00Z',
    docNameTemplate: 'Private — {YYYY-MM-DD}',
    visibility: 'private',
    notificationMode: 'orbie',
    ownerSlackUserId: 'U123',
    notificationRecipients: ['U123'],
    templateTabName: 'Format',
  }).templateTabName).toBe('Format')
})

test('private cadences require an owner and DM recipients', () => {
  expect(() => pure.normalizeCadence({
    id: 'private-1',
    title: 'Private sync',
    sourceDocId: 'doc-1',
    outputFolderId: 'folder-1',
    nextOccurrenceAt: '2026-08-05T12:00:00Z',
    docNameTemplate: 'Private — {YYYY-MM-DD}',
    visibility: 'private',
  })).toThrow('private cadences require ownerSlackUserId')

  expect(pure.normalizeCadence({
    id: 'private-1',
    title: 'Private sync',
    sourceDocId: 'doc-1',
    outputFolderId: 'folder-1',
    nextOccurrenceAt: '2026-08-05T12:00:00Z',
    docNameTemplate: 'Private — {YYYY-MM-DD}',
    visibility: 'private',
    ownerSlackUserId: 'UOWNER',
    notificationRecipients: ['UOWNER'],
  }).notificationRecipients).toEqual(['UOWNER'])
})

test('private runs queue only the authenticated requester', () => {
  const cadence = {
    visibility: 'private',
    notificationRecipients: ['UOWNER', 'UCOLLABORATOR'],
  }

  expect(pure.notificationRecipients(cadence, 'UCOLLABORATOR')).toEqual([
    'UCOLLABORATOR',
  ])
  expect(() => pure.notificationRecipients(cadence, null)).toThrow(
    'private notification delivery requires a requester',
  )
})

test('private delivery is idempotent per requester', () => {
  const record = { agendaNotified: false }

  expect(pure.wasNotificationDelivered(record, 'agenda', 'UOWNER')).toBe(false)
  pure.markNotificationDelivered(record, 'agenda', 'UOWNER')
  expect(pure.wasNotificationDelivered(record, 'agenda', 'UOWNER')).toBe(true)
  expect(pure.wasNotificationDelivered(record, 'agenda', 'UCOLLABORATOR')).toBe(false)

  pure.markNotificationDelivered(record, 'agenda', 'UCOLLABORATOR')
  expect(record.agendaNotifiedRecipients).toEqual(['UOWNER', 'UCOLLABORATOR'])
})

test('legacy global delivery remains idempotent for every requester', () => {
  const record = { notesNotified: true }

  expect(pure.wasNotificationDelivered(record, 'notes', 'UOWNER')).toBe(true)
  expect(pure.wasNotificationDelivered(record, 'notes', 'UCOLLABORATOR')).toBe(true)
})

test('direct Apps Script Slack delivery is rejected', () => {
  expect(() => pure.normalizeCadence({
    visibility: 'public',
    notificationMode: 'apps-script',
  })).toThrow('notificationMode must be orbie')
})

test('only the approved Execution API entrypoints are public', () => {
  const srcDir = path.join(__dirname, '..', 'src')
  const publicFunctions = fs.readdirSync(srcDir)
    .filter((name) => name.endsWith('.js'))
    .flatMap((name) => {
      const source = fs.readFileSync(path.join(srcDir, name), 'utf8')
      return [...source.matchAll(/^function ([A-Za-z0-9_]+)\s*\(/gm)]
        .map((match) => match[1])
        .filter((functionName) => !functionName.endsWith('_'))
    })
    .sort()

  expect(publicFunctions).toEqual([
    'acknowledgeOrbieNotification',
    'acknowledgeOrbieNotificationForCaller',
    'getAuthorizedCadences',
    'getPendingOrbieNotifications',
    'getPendingOrbieNotificationsForCaller',
    'runCadenceJob',
  ])
})

test('outbox payload uses the client acknowledgement field name', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'meeting_ops.js'),
    'utf8',
  )
  expect(source).toContain('notificationId: notificationId')
  expect(source).not.toContain('\n    id: notificationId')
})

test('cadence execution requires caller validation before authorization', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'meeting_ops.js'),
    'utf8',
  )
  expect(source).toContain('var caller = parseCaller_(request);')
  expect(source).not.toContain('if (request.requesterSlackUserId)')
})

test('notification keys are stable per cadence occurrence and kind', () => {
  expect(pure.notificationKey('cadence-1', new Date('2026-08-05T12:00:00Z'), 'UTC', 'agenda'))
    .toBe('agenda:cadence-1:2026-08-05')
  expect(pure.notificationKey(
    'cadence-1',
    new Date('2026-08-05T12:00:00Z'),
    'UTC',
    'agenda',
    'U123',
  )).toBe('agenda:cadence-1:2026-08-05:U123')
})

test('authorized cadences include public and private owner/access/recipient entries only', () => {
  const cadences = [
    { id: 'public', visibility: 'public', status: 'active' },
    { id: 'owner', visibility: 'private', ownerSlackUserId: 'U123', status: 'active' },
    { id: 'access', visibility: 'private', accessSlackUserIds: ['U123'], status: 'active' },
    { id: 'recipient', visibility: 'private', notificationRecipients: ['U123'], status: 'active' },
    { id: 'other', visibility: 'private', ownerSlackUserId: 'U999', status: 'active' },
    { id: 'disabled', visibility: 'public', status: 'disabled' },
  ]
  expect(pure.authorizedCadences(cadences, 'U123').map((cadence) => cadence.id))
    .toEqual(['public', 'owner', 'access', 'recipient'])
  expect(pure.isCadenceAuthorized(cadences[5], 'U123')).toBe(false)
})
