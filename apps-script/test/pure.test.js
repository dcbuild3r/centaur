const { expect, test } = require('bun:test')
const fs = require('node:fs')
const path = require('node:path')
const pure = require('../src/pure.js')

global.Utilities = {
  formatDate(date, timeZone, format) {
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
      timeZone,
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }).formatToParts(date).map(({ type, value }) => [type, value]))
    if (format === 'yyyy-MM-dd') return `${parts.year}-${parts.month}-${parts.day}`
    if (format === 'HH:mm:ss') return `${parts.hour === '24' ? '00' : parts.hour}:${parts.minute}:${parts.second}`
    if (format === 'Z') {
      const offset = new Intl.DateTimeFormat('en-US', {
        timeZone,
        timeZoneName: 'longOffset',
      }).formatToParts(date).find(({ type }) => type === 'timeZoneName')?.value || 'GMT'
      const match = offset.match(/^GMT([+-])(\d{2}):(\d{2})$/)
      if (!match) return '+0000'
      return `${match[1]}${match[2]}${match[3]}`
    }
    throw new Error(`unexpected format: ${format}`)
  },
}

test('resolves the date placeholder without changing other text', () => {
  expect(pure.resolveDocName('All Hands — {YYYY-MM-DD}', new Date('2026-08-03T10:00:00Z'), 'UTC'))
    .toBe('All Hands — 2026-08-03')
})

test('resolves the two-digit ISO week placeholder', () => {
  expect(pure.resolveDocName(
    'CW{week} World Foundation Weekly All Hands',
    new Date('2026-08-03T10:00:00Z'),
    'UTC',
  )).toBe('CW32 World Foundation Weekly All Hands')
})

test('ISO week placeholder follows year boundaries', () => {
  expect(pure.isoWeek(new Date('2026-12-31T10:00:00Z'), 'UTC')).toBe('53')
  expect(pure.isoWeek(new Date('2027-01-01T10:00:00Z'), 'UTC')).toBe('53')
  expect(pure.isoWeek(new Date('2027-01-04T10:00:00Z'), 'UTC')).toBe('01')
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

test('scheduled cadence recurrence supports bi-weekly, monthly, and quarterly periods', () => {
  const occurrence = new Date('2026-01-31T09:15:00Z')
  expect(pure.nextOccurrence(occurrence, 'bi-weekly', 'UTC').toISOString())
    .toBe('2026-02-14T09:15:00.000Z')
  expect(pure.nextOccurrence(occurrence, 'monthly', 'UTC').toISOString())
    .toBe('2026-02-28T09:15:00.000Z')
  expect(pure.nextOccurrence(
    pure.nextOccurrence(occurrence, 'monthly', 'UTC'),
    'monthly',
    'UTC',
  ).toISOString()).toBe('2026-03-31T09:15:00.000Z')
  expect(pure.nextOccurrence(occurrence, 'quarterly', 'UTC').toISOString())
    .toBe('2026-04-30T09:15:00.000Z')
  expect(pure.nextOccurrence(
    pure.nextOccurrence(occurrence, 'quarterly', 'UTC'),
    'quarterly',
    'UTC',
  ).toISOString()).toBe('2026-07-31T09:15:00.000Z')
})

test('scheduled recurrence preserves local meeting time across DST', () => {
  const occurrence = new Date('2026-03-22T09:00:00Z')
  const next = pure.nextOccurrence(occurrence, 'weekly', 'Europe/Prague')
  expect(next.toISOString()).toBe('2026-03-29T08:00:00.000Z')
})

test('notes notification waits for the configured delay', () => {
  const occurrence = new Date('2026-08-05T12:00:00Z')
  expect(pure.shouldPost(new Date('2026-08-05T12:59:59Z'), occurrence, 60)).toBe(false)
  expect(pure.shouldPost(new Date('2026-08-05T13:00:00Z'), occurrence, 60)).toBe(true)
})

test('custom instructions are normalized and bounded', () => {
  expect(pure.normalizeCustomInstructions('  First\r\nSecond\u0000  '))
    .toBe('First\nSecond')
  expect(pure.normalizeCustomInstructions('x'.repeat(4500))).toHaveLength(4000)
  expect(pure.normalizeCustomInstructions({ text: 'not instructions' })).toBe('')
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
    notesTabName: 'Meeting Notes',
  })
})

test('normalizes explicit Google Docs format and notes tab names', () => {
  const normalized = pure.normalizeCadence({
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
    notesTabName: 'Weekly Notes',
  })
  expect(normalized.templateTabName).toBe('Format')
  expect(normalized.notesTabName).toBe('Weekly Notes')
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

test('private channel cadences queue one channel notification', () => {
  expect(pure.notificationRecipients({
    visibility: 'private',
    notifyChannel: 'G123',
    notificationRecipients: ['UOWNER', 'UMANDY'],
  }, null, true)).toEqual([null])
})

test('scheduled private notifications use all resolved recipients', () => {
  expect(pure.notificationRecipients({
    visibility: 'private',
    notificationRecipients: ['UOWNER', 'UMANDY'],
  }, null, true)).toEqual(['UOWNER', 'UMANDY'])
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
    'runScheduledCadenceJob',
    'runScheduledNotificationsJob',
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
