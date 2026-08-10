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
  }

  getId() {
    return this.id
  }

  getUrl() {
    return `https://docs.example/${this.id}`
  }

  makeCopy(name) {
    const copyId = `${this.id}-copy`
    documents.set(copyId, documents.get(this.id).clone())
    files.set(copyId, new FakeFile(copyId, name))
    return files.get(copyId)
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
    return { id }
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
}

const {
  assertTemplateCopyReady_,
  createDocumentFromTemplate_,
  findCurrentAgendaOccurrence_,
  prepareTemplateCopy_,
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
