const { expect, test } = require('bun:test')

class FakeElement {
  constructor(text, type = 'PARAGRAPH') {
    this.text = text
    this.type = type
  }

  clone() {
    return new FakeElement(this.text, this.type)
  }

  getText() {
    return this.text
  }

  getType() {
    return this.type
  }

  asParagraph() {
    if (this.type !== 'PARAGRAPH') throw new Error('not a paragraph')
    return this
  }

  setText(text) {
    this.text = text
  }
}

class FakeBody {
  constructor(elements = []) {
    this.children = elements.map((element) => (
      element instanceof FakeElement ? element : new FakeElement(element)
    ))
  }

  clone() {
    return new FakeBody(this.children.map((child) => child.clone()))
  }

  getNumChildren() {
    return this.children.length
  }

  getChild(index) {
    return this.children[index]
  }

  insertParagraph(index, text) {
    this.children.splice(index, 0, new FakeElement(text))
  }

  replaceText(pattern, replacement) {
    const expression = new RegExp(pattern, 'g')
    this.children.forEach((child) => {
      child.text = child.text.replace(expression, replacement)
    })
  }
}

class FakeTab {
  constructor(title, elements = [], children = []) {
    this.title = title
    this.body = new FakeBody(elements)
    this.children = children
  }

  clone() {
    return new FakeTab(
      this.title,
      this.body.children.map((child) => child.clone()),
      this.children.map((child) => child.clone()),
    )
  }

  getTitle() {
    return this.title
  }

  asDocumentTab() {
    return this
  }

  getBody() {
    return this.body
  }

  getChildTabs() {
    return this.children
  }
}

class FakeDocument {
  constructor(tabs) {
    this.tabs = tabs
    this.saved = false
  }

  clone() {
    return new FakeDocument(this.tabs.map((tab) => tab.clone()))
  }

  getTabs() {
    return this.tabs
  }

  saveAndClose() {
    this.saved = true
  }
}

class FakeFile {
  constructor(id, name = id) {
    this.id = id
    this.name = name
    this.trashed = false
    this.folderId = null
    this.editors = []
  }

  getId() {
    return this.id
  }

  getUrl() {
    return `https://docs.example/${this.id}`
  }

  makeCopy(name, folder) {
    const copyId = `${this.id}-copy-${files.size}`
    documents.set(copyId, documents.get(this.id).clone())
    const copy = new FakeFile(copyId, name)
    copy.folderId = folder && folder.id
    files.set(copyId, copy)
    return files.get(copyId)
  }

  getMimeType() {
    return 'application/vnd.google-apps.document'
  }

  isTrashed() {
    return this.trashed
  }

  setTrashed(trashed) {
    this.trashed = trashed
  }

  getName() {
    return this.name
  }

  setName(name) {
    this.name = name
  }

  addEditors(emails) {
    this.editors = [...new Set(this.editors.concat(emails))]
  }

  getEditors() {
    return this.editors.map((email) => ({ getEmail: () => email }))
  }
}

const documents = new Map()
const files = new Map()

global.DocumentApp = {
  ElementType: {
    PARAGRAPH: 'PARAGRAPH',
  },
  openById(id) {
    return documents.get(id)
  },
}

global.DriveApp = {
  getFileById(id) {
    return files.get(id)
  },
  getFolderById(id) {
    return {
      id,
      getFilesByName(name) {
        const matches = [...files.values()].filter((file) => (
          file.folderId === id && file.name === name && !file.trashed
        ))
        let index = 0
        return {
          hasNext() {
            return index < matches.length
          },
          next() {
            return matches[index++]
          },
        }
      },
    }
  },
}

global.Utilities = {
  formatDate(date, _timeZone, format) {
    if (format === 'MMM d, yyyy') return 'Aug 10, 2026'
    return date.toISOString().slice(0, 10)
  },
}

global.MeetingOpsPure = {
  dateKey(date) {
    return date.toISOString().slice(0, 10)
  },
  escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  },
  isWithinAgendaWindow(now, occurrence, leadMin, staleWindowMin) {
    return now >= new Date(occurrence.getTime() - leadMin * 60_000) &&
      now <= new Date(occurrence.getTime() + staleWindowMin * 60_000)
  },
  normalizeCustomInstructions(value) {
    if (typeof value !== 'string') return ''
    return value
      .replace(/\r\n?/g, '\n')
      .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '')
      .trim()
      .slice(0, 2000)
      .trim()
  },
  resolveDocName(template, date, timeZone) {
    return String(template).replace('{YYYY-MM-DD}', this.dateKey(date, timeZone))
  },
  nextWeeklyOccurrence(occurrence) {
    return new Date(occurrence.getTime() + 7 * 24 * 60 * 60 * 1000)
  },
  normalizeCadence(cadenceValue) {
    return {
      ...cadenceValue,
      visibility: cadenceValue.visibility || 'public',
      notificationMode: cadenceValue.notificationMode || 'orbie',
      cadence: cadenceValue.cadence || 'weekly',
      notificationRecipients: cadenceValue.notificationRecipients || [],
      accessSlackUserIds: cadenceValue.accessSlackUserIds || [],
    }
  },
  shouldPost(now, occurrence, delayMin) {
    return now >= new Date(occurrence.getTime() + delayMin * 60_000)
  },
  isCadenceAuthorized(cadenceValue, requesterSlackUserId) {
    return [cadenceValue.ownerSlackUserId]
      .concat(cadenceValue.accessSlackUserIds || [])
      .includes(requesterSlackUserId)
  },
  notificationRecipients(cadenceValue, requesterSlackUserId, scheduled) {
    if (cadenceValue.visibility !== 'private') return [null]
    return scheduled
      ? cadenceValue.notificationRecipients
      : [requesterSlackUserId]
  },
  notificationKey(cadenceId, occurrence, timeZone, kind, recipientSlackUserId) {
    const key = `${kind}:${cadenceId}:${this.dateKey(occurrence, timeZone)}`
    return recipientSlackUserId ? `${key}:${recipientSlackUserId}` : key
  },
  wasNotificationDelivered(record, kind, requesterSlackUserId) {
    return (record[`${kind}NotifiedRecipients`] || []).includes(requesterSlackUserId)
  },
  markNotificationDelivered(record, kind, requesterSlackUserId) {
    record[`${kind}NotifiedRecipients`] = [requesterSlackUserId]
    return record
  },
}

const {
  assertTemplateCopyReady_,
  createDocumentFromTemplate_,
  findCurrentAgendaOccurrence_,
  processAgenda_,
  prepareTemplateCopy_,
  runCadenceJob,
  runScheduledCadenceJob,
  runScheduledNotificationsJob,
  setMeetingDate_,
} = require('../src/meeting_ops.js')

function weeklyTemplate() {
  return new FakeDocument([
    new FakeTab('Meeting Notes', [
      'Jul 20, 2026',
      'Question TBC',
      new FakeElement('Progress table', 'TABLE'),
      new FakeElement('Feedback table', 'TABLE'),
    ]),
    new FakeTab('Format', ['Meeting format', 'Aim: Keep the Foundation aligned']),
  ])
}

function cadence(overrides = {}) {
  return {
    sourceDocId: 'weekly-template',
    outputFolderId: 'output-folder',
    templateTabName: 'Format',
    notesTabName: 'Meeting Notes',
    timeZone: 'Europe/Prague',
    attendees: [],
    ...overrides,
  }
}

let executionProperties

function installExecutionFakes() {
  executionProperties = new Map()
  const properties = {
    getProperty(key) {
      return executionProperties.has(key) ? executionProperties.get(key) : null
    },
    setProperty(key, value) {
      executionProperties.set(key, String(value))
    },
    deleteProperty(key) {
      executionProperties.delete(key)
    },
    getProperties() {
      return Object.fromEntries(executionProperties.entries())
    },
  }
  global.PropertiesService = {
    getScriptProperties() {
      return properties
    },
  }
  global.LockService = {
    getScriptLock() {
      return {
        waitLock() {},
        releaseLock() {},
      }
    },
  }
  global.MimeType = { GOOGLE_DOCS: 'application/vnd.google-apps.document' }
  global.getMeetingConfig_ = () => [manualCadence()]
  global.formatAttendees_ = (attendees) => attendees.join(', ')
}

function executionProperty(key) {
  return executionProperties.get(key) || null
}

function manualCadence(overrides = {}) {
  return cadence({
    id: 'manual-cadence',
    title: 'Manual Meeting',
    sourceDocId: 'manual-template',
    visibility: 'private',
    ownerSlackUserId: 'U1',
    notificationRecipients: ['U1'],
    notificationMode: 'orbie',
    cadence: 'weekly',
    nextOccurrenceAt: '2026-08-17T12:00:00Z',
    docNameTemplate: 'Manual Meeting — {YYYY-MM-DD}',
    notifyLeadMin: 60,
    staleWindowMin: 12 * 60,
    ...overrides,
  })
}

function prepareManualTemplate() {
  documents.clear()
  files.clear()
  documents.set('manual-template', weeklyTemplate())
  files.set('manual-template', new FakeFile('manual-template'))
  installExecutionFakes()
}

function manualRequest(now, customInstructions) {
  return {
    cadenceId: 'manual-cadence',
    requesterSlackUserId: 'U1',
    requesterSlackTeamId: 'TL1HM8UUU',
    now,
    ...(customInstructions === undefined ? {} : { customInstructions }),
  }
}

test('creates the new document as a full native copy of the weekly template', () => {
  documents.set('weekly-template', weeklyTemplate())
  files.set('weekly-template', new FakeFile('weekly-template'))

  const copiedFile = createDocumentFromTemplate_(
    cadence(),
    'Weekly Sync — 2026-08-10',
    new Date('2026-08-10T14:00:00Z'),
  )
  const copy = documents.get(copiedFile.getId())

  expect(copy.getTabs().map((tab) => tab.getTitle())).toEqual([
    'Meeting Notes',
    'Format',
  ])
  expect(copy.getTabs()[0].getBody().children.map((child) => child.getText()))
    .toEqual(['Aug 10, 2026', 'Question TBC', 'Progress table', 'Feedback table'])
  expect(copy.getTabs()[0].getBody().children.map((child) => child.getType()))
    .toEqual(['PARAGRAPH', 'PARAGRAPH', 'TABLE', 'TABLE'])
  expect(copy.getTabs()[1].getBody().children.map((child) => child.getText()))
    .toEqual(['Meeting format', 'Aim: Keep the Foundation aligned'])
  expect(copy.saved).toBe(true)
})

test('preserves nested tab topology from the source template', () => {
  const source = weeklyTemplate()
  source.tabs[0].children.push(new FakeTab('Team updates', ['Updates']))
  documents.set('weekly-template', source)
  documents.set('nested-copy', source.clone())

  expect(() => assertTemplateCopyReady_('nested-copy', cadence())).not.toThrow()
})

test('fails closed when the generated document does not preserve the template tabs', () => {
  documents.set('weekly-template', weeklyTemplate())
  documents.set('wrong-copy', new FakeDocument([
    new FakeTab('Format', ['Meeting format']),
    new FakeTab('Meeting notes', ['Meeting date: 2026-08-10']),
  ]))

  expect(() => assertTemplateCopyReady_('wrong-copy', cadence()))
    .toThrow('does not preserve the source template tab tree')
})

test('initial preparation preserves template content beyond the date paragraph', () => {
  documents.set('weekly-template', new FakeDocument([
    new FakeTab('Meeting Notes', ['Jul 20, 2026', 'Attendees: {attendees}']),
    new FakeTab('Format', ['Previous: {prev_meeting_link}']),
  ]))
  documents.set('placeholder-copy', documents.get('weekly-template').clone())

  prepareTemplateCopy_(
    'placeholder-copy',
    cadence({ attendees: ['A', 'B'], previousMeetingLink: 'previous-link' }),
    new Date('2026-08-10T14:00:00Z'),
  )

  const copy = documents.get('placeholder-copy')
  expect(copy.tabs[0].body.children.map((child) => child.getText()))
    .toEqual(['Aug 10, 2026', 'Attendees: {attendees}'])
  expect(copy.tabs[1].body.children.map((child) => child.getText()))
    .toEqual(['Previous: {prev_meeting_link}'])
})

test('retry validation does not modify attendee notes', () => {
  documents.set('weekly-template', weeklyTemplate())
  const copy = weeklyTemplate()
  copy.tabs[0].body.children.push(new FakeElement('Attendee note with {date}'))
  documents.set('existing-copy', copy)

  assertTemplateCopyReady_('existing-copy', cadence())

  expect(copy.tabs[0].body.children.at(-1).getText()).toBe('Attendee note with {date}')
})

test('retry validation rejects a named tab that lost the cloned notes structure', () => {
  documents.set('weekly-template', weeklyTemplate())
  documents.set('malformed-copy', new FakeDocument([
    new FakeTab('Meeting Notes', ['', 'Smoke-test attendee note']),
    new FakeTab('Format', ['Meeting format', 'Aim: Keep the Foundation aligned']),
  ]))

  expect(() => assertTemplateCopyReady_(
    'malformed-copy',
    cadence(),
    false,
  )).toThrow('Meeting Notes tab has lost source template structure')
})

test('meeting date replacement fails closed when notes do not start with text', () => {
  const body = new FakeBody([new FakeElement('Native table', 'TABLE')])

  expect(() => setMeetingDate_(
    body,
    new Date('2026-08-10T14:00:00Z'),
    'Europe/Prague',
  )).toThrow('does not start with a date paragraph')

  expect(body.children.map((child) => child.getText())).toEqual(['Native table'])
})

test('meeting date replaces a copied native date chip exposed as empty text', () => {
  const body = new FakeBody(['', 'Question TBC'])

  setMeetingDate_(body, new Date('2026-08-10T14:00:00Z'), 'Europe/Prague')

  expect(body.children.map((child) => child.getText()))
    .toEqual(['Aug 10, 2026', 'Question TBC'])
})

test('meeting date replacement fails closed on an unexpected first paragraph', () => {
  const body = new FakeBody(['Weekly Sync'])

  expect(() => setMeetingDate_(
    body,
    new Date('2026-08-10T14:00:00Z'),
    'Europe/Prague',
  )).toThrow('starts with an unrecognized date')
  expect(body.children[0].getText()).toBe('Weekly Sync')
})

test('retry validation allows attendee-added tabs while retaining required tabs', () => {
  documents.set('weekly-template', weeklyTemplate())
  const copy = weeklyTemplate()
  copy.tabs.push(new FakeTab('Attendee scratchpad', ['Notes']))
  documents.set('extended-copy', copy)

  expect(() => assertTemplateCopyReady_(
    'extended-copy',
    cadence(),
    false,
  )).not.toThrow()
})

test('a public cadence can reuse the current occurrence for repair retries', () => {
  global.PropertiesService = {
    getScriptProperties() {
      return {
        getProperties() {
          return {
            'AGENDA_RECORD:public-cadence:2026-08-10': JSON.stringify({
              occurrenceAt: '2026-08-10T14:00:00.000Z',
              agendaNotified: true,
            }),
          }
        },
      }
    },
  }

  expect(findCurrentAgendaOccurrence_(
    { id: 'public-cadence', visibility: 'public' },
    new Date('2026-08-10T14:30:00Z'),
    60,
    720,
    null,
  ).toISOString()).toBe('2026-08-10T14:00:00.000Z')
})

test('manual runs use the request date when the scheduled occurrence is outside the window', () => {
  prepareManualTemplate()

  const result = runCadenceJob(manualRequest('2026-08-10T14:00:00Z'))

  expect(result.occurrenceAt).toBe('2026-08-10T14:00:00.000Z')
  expect(result.docId).toBeTruthy()
  expect(executionProperty('NEXT_OCCURRENCE:manual-cadence')).toBeNull()
})

test('manual public runs by an owner do not require a channel allowlist', () => {
  prepareManualTemplate()
  global.getMeetingConfig_ = () => [manualCadence({
    visibility: 'public',
    notifyChannel: 'C069VHQEJEQ',
    notifyChannelName: '#wf-all',
    notificationRecipients: [],
  })]

  const result = runCadenceJob(manualRequest('2026-08-10T14:00:00Z'))

  expect(result.docId).toBeTruthy()
  expect(executionProperty('ALLOWED_WF_CHANNEL_IDS')).toBeNull()
})

test('manual public runs replace a trashed agenda and queue its notification again', () => {
  prepareManualTemplate()
  global.getMeetingConfig_ = () => [manualCadence({
    visibility: 'public',
    notifyChannel: 'C069VHQEJEQ',
    notifyChannelName: '#wf-all',
    notificationRecipients: [],
  })]
  const request = manualRequest('2026-08-10T14:00:00Z')

  const first = runCadenceJob(request)
  files.get(first.docId).setTrashed(true)
  executionProperties.delete('ORBIE_OUTBOX:agenda:manual-cadence:2026-08-10')

  const replacement = runCadenceJob(request)

  expect(replacement.docId).not.toBe(first.docId)
  expect(files.get(first.docId).isTrashed()).toBe(true)
  expect(files.get(replacement.docId).isTrashed()).toBe(false)
  const notification = JSON.parse(
    executionProperty('ORBIE_OUTBOX:agenda:manual-cadence:2026-08-10'),
  )
  expect(notification.channelId).toBe('C069VHQEJEQ')
  expect(notification.docId).toBe(replacement.docId)
})

test('manual public runs replace an agenda whose saved title is stale', () => {
  prepareManualTemplate()
  global.getMeetingConfig_ = () => [manualCadence({
    visibility: 'public',
    notifyChannel: 'C069VHQEJEQ',
    notifyChannelName: '#wf-all',
    notificationRecipients: [],
  })]
  const request = manualRequest('2026-08-10T14:00:00Z')

  const first = runCadenceJob(request)
  files.get(first.docId).setName('Manual Meeting — {calendar_week}')
  executionProperties.delete('ORBIE_OUTBOX:agenda:manual-cadence:2026-08-10')

  const replacement = runCadenceJob(request)

  expect(replacement.docId).not.toBe(first.docId)
  expect(files.get(first.docId).getName()).toContain('superseded malformed copy')
  expect(files.get(replacement.docId).getName()).toBe('Manual Meeting — 2026-08-10')
  const notification = JSON.parse(
    executionProperty('ORBIE_OUTBOX:agenda:manual-cadence:2026-08-10'),
  )
  expect(notification.channelId).toBe('C069VHQEJEQ')
  expect(notification.docId).toBe(replacement.docId)
})

test('manual runs reject callers who are not cadence owners', () => {
  prepareManualTemplate()
  const request = manualRequest('2026-08-10T14:00:00Z')
  request.requesterSlackUserId = 'U-NOT-OWNER'

  expect(() => runCadenceJob(request)).toThrow('Cadence is not authorized')
  expect([...documents.keys()]).toEqual(['manual-template'])
})

test('manual runs do not use a future next occurrence or advance the schedule', () => {
  prepareManualTemplate()
  const scheduledNext = '2026-08-17T12:00:00.000Z'
  executionProperties.set('NEXT_OCCURRENCE:manual-cadence', scheduledNext)

  const result = runCadenceJob(manualRequest('2026-08-10T14:00:00Z'))

  expect(result.occurrenceAt).toBe('2026-08-10T14:00:00.000Z')
  expect(executionProperty('NEXT_OCCURRENCE:manual-cadence')).toBe(scheduledNext)
})

test('direct scheduled processing still rejects a future occurrence', () => {
  prepareManualTemplate()

  expect(processAgenda_(
    manualCadence(),
    new Date('2026-08-10T14:00:00Z'),
    'U1',
  )).toBeUndefined()
  expect([...documents.keys()]).toEqual(['manual-template'])
})

test('scheduled entrypoint creates the requested occurrence and queues recipient delivery', () => {
  prepareManualTemplate()

  const result = runScheduledCadenceJob({
    scheduledByOrbie: true,
    requesterSlackTeamId: 'TL1HM8UUU',
    cadence: manualCadence(),
    occurrenceAt: '2026-08-14T12:00:00Z',
    now: '2026-08-14T07:15:00Z',
  })

  expect(result.docUrl).toContain('https://docs.example/manual-template-copy-')
  expect(Object.keys(Object.fromEntries(executionProperties.entries())).filter((key) => (
    key.startsWith('ORBIE_OUTBOX:')
  ))).toEqual(['ORBIE_OUTBOX:agenda:manual-cadence:2026-08-14:U1'])
})

test('owner-triggered Notion cadence bypasses scheduled channel allowlist', () => {
  prepareManualTemplate()
  const result = runScheduledCadenceJob({
    scheduledByOrbie: true,
    manualByOwner: true,
    requesterSlackUserId: 'U1',
    requesterSlackTeamId: 'TL1HM8UUU',
    cadence: {
      ...manualCadence(),
      visibility: 'public',
      notifyChannel: 'C069VHQEJEQ',
      notifyChannelName: '#wf-all',
      notificationRecipients: [],
    },
    occurrenceAt: '2026-08-31T14:00:00Z',
    now: '2026-08-26T20:00:00Z',
  })

  expect(result.docId).toBeTruthy()
  expect(executionProperty('ALLOWED_WF_CHANNEL_IDS')).toBeNull()
})

test('owner-triggered Notion cadence rejects a non-owner before copying', () => {
  prepareManualTemplate()
  expect(() => runScheduledCadenceJob({
    scheduledByOrbie: true,
    manualByOwner: true,
    requesterSlackUserId: 'U-NOT-OWNER',
    requesterSlackTeamId: 'TL1HM8UUU',
    cadence: manualCadence(),
    occurrenceAt: '2026-08-31T14:00:00Z',
    now: '2026-08-26T20:00:00Z',
  })).toThrow('Cadence is not authorized')
  expect([...documents.keys()]).toEqual(['manual-template'])
})

test('document editors are granted on the copied document, never the source', () => {
  prepareManualTemplate()
  const result = runScheduledCadenceJob({
    scheduledByOrbie: true,
    requesterSlackTeamId: 'TL1HM8UUU',
    cadence: { ...manualCadence(), documentEditorEmails: ['piotr.piwowarczyk@world.org'] },
    occurrenceAt: '2026-08-14T12:00:00Z',
    now: '2026-08-14T07:15:00Z',
  })

  expect(files.get('manual-template').editors).toEqual([])
  expect(files.get(result.docId).editors).toEqual(['piotr.piwowarczyk@world.org'])
})

test('scheduled notifications entrypoint queues notes after the configured delay', () => {
  prepareManualTemplate()
  runScheduledCadenceJob({
    scheduledByOrbie: true,
    requesterSlackTeamId: 'TL1HM8UUU',
    cadence: manualCadence(),
    occurrenceAt: '2026-08-14T12:00:00Z',
    now: '2026-08-14T07:15:00Z',
  })
  const result = runScheduledNotificationsJob({
    scheduledByOrbie: true,
    requesterSlackTeamId: 'TL1HM8UUU',
    cadence: manualCadence(),
    now: '2026-08-14T13:00:00Z',
  })

  expect(result).toEqual({
    status: 'notifications-processed',
    meetingId: 'manual-cadence',
  })
  expect(executionProperty('ORBIE_OUTBOX:notes:manual-cadence:2026-08-14:U1'))
    .toBeTruthy()
})

test('manual retries reuse the same document and notification and insert instructions once', () => {
  prepareManualTemplate()
  const first = runCadenceJob(manualRequest(
    '2026-08-10T14:00:00Z',
    '  Bring the decision log.\u0000\r\nKeep it short.  ',
  ))
  const second = runCadenceJob(manualRequest(
    '2026-08-10T14:00:00Z',
    '  Bring the decision log.\u0000\r\nKeep it short.  ',
  ))

  expect(second.docId).toBe(first.docId)
  expect(second.customInstructions).toBe('Bring the decision log.\nKeep it short.')
  expect(Object.keys(Object.fromEntries(executionProperties.entries())).filter((key) => (
    key.startsWith('ORBIE_OUTBOX:')
  ))).toHaveLength(1)

  const copy = documents.get(first.docId)
  expect(copy.tabs[0].body.children.map((child) => child.getText())).toEqual([
    'Aug 10, 2026',
    'Bring the decision log.\nKeep it short.',
    'Question TBC',
    'Progress table',
    'Feedback table',
  ])
  expect(documents.get('manual-template').tabs[0].body.children.map((child) => child.getText()))
    .toEqual(['Jul 20, 2026', 'Question TBC', 'Progress table', 'Feedback table'])
})
