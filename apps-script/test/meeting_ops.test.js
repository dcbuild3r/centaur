const { expect, test } = require('bun:test')

class FakeElement {
  constructor(text, type = 'PARAGRAPH') {
    this.text = text
    this.type = type
  }

  copy() {
    return new FakeElement(this.text)
  }

  getText() {
    return this.text
  }

  getType() {
    return this.type
  }
}

class FakeBody {
  constructor(texts = []) {
    this.children = texts.map((text) => new FakeElement(text))
  }

  clear() {
    this.children = []
  }

  getNumChildren() {
    return this.children.length
  }

  getChild(index) {
    return this.children[index]
  }

  getText() {
    return this.children.map((child) => child.getText()).join('\n')
  }

  appendParagraph(element) {
    this.children.push(element)
  }

  replaceText(pattern, replacement) {
    const expression = new RegExp(pattern, 'g')
    this.children.forEach((child) => {
      child.text = child.text.replace(expression, replacement)
    })
  }

  insertParagraph(index, text) {
    this.children.splice(index, 0, new FakeElement(text))
  }
}

class FakeTab {
  constructor(title, texts = [], id = title.toLowerCase().replaceAll(' ', '-')) {
    this.title = title
    this.body = new FakeBody(texts)
    this.id = id
  }

  getTitle() {
    return this.title
  }

  getId() {
    return this.id
  }

  asDocumentTab() {
    return this
  }

  getBody() {
    return this.body
  }

  getChildTabs() {
    return []
  }
}

class FakeDocument {
  constructor(tabs) {
    this.tabs = tabs
  }

  getTabs() {
    return this.tabs
  }

  saveAndClose() {}

}

const documents = new Map()

global.DocumentApp = {
  ElementType: {
    PARAGRAPH: 'PARAGRAPH',
    LIST_ITEM: 'LIST_ITEM',
    TABLE: 'TABLE',
    PAGE_BREAK: 'PAGE_BREAK',
    HORIZONTAL_RULE: 'HORIZONTAL_RULE',
    INLINE_IMAGE: 'INLINE_IMAGE',
  },
  openById(id) {
    return documents.get(id)
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

global.Docs = {
  Documents: {
    batchUpdate(payload, documentId) {
    const document = documents.get(documentId)
      payload.requests.forEach((request) => {
      if (request.addDocumentTab) {
        document.tabs.push(new FakeTab(request.addDocumentTab.tabProperties.title))
      }
      if (request.updateDocumentTabProperties) {
        const properties = request.updateDocumentTabProperties.tabProperties
        document.tabs.find((tab) => tab.getId() === properties.tabId).title = properties.title
      }
    })
    },
  },
}

const {
  ensureMeetingNotesTab_,
  findCurrentAgendaOccurrence_,
  replacePlaceholdersInFormatTab_,
} = require('../src/meeting_ops.js')

test('creates one Meeting notes tab from the format with the date at the top', () => {
  const document = new FakeDocument([
    new FakeTab('Meeting format', ['Agenda', 'Decisions', 'Actions']),
  ])
  documents.set('doc-1', document)

  ensureMeetingNotesTab_(
    'doc-1',
    'Meeting format',
    new Date('2026-08-10T14:00:00Z'),
    'Europe/Prague',
  )

  expect(document.getTabs().map((tab) => tab.getTitle())).toEqual([
    'Meeting format',
    'Meeting notes',
  ])
  expect(document.getTabs()[1].getBody().children.map((element) => element.getText()))
    .toEqual(['Meeting date: 2026-08-10', 'Agenda', 'Decisions', 'Actions'])
})

test('an immediate retry keeps existing notes and creates no duplicate tab or date', () => {
  const document = new FakeDocument([
    new FakeTab('Meeting format', ['Agenda']),
    new FakeTab('Meeting notes', ['Meeting date: 2026-08-10', 'Agenda', 'User note']),
  ])
  documents.set('doc-2', document)

  ensureMeetingNotesTab_(
    'doc-2',
    'Meeting format',
    new Date('2026-08-10T14:00:00Z'),
    'Europe/Prague',
  )

  expect(document.getTabs()).toHaveLength(2)
  expect(document.getTabs()[1].getBody().children.map((element) => element.getText()))
    .toEqual(['Meeting date: 2026-08-10', 'Agenda', 'User note'])
})

test('repairs an existing document when its preserved format title differs from config', () => {
  const document = new FakeDocument([
    new FakeTab('Meeting format', ['Agenda']),
    new FakeTab('Meeting notes', ['Agenda', 'Existing note']),
  ])
  documents.set('doc-3', document)

  ensureMeetingNotesTab_(
    'doc-3',
    'Format',
    new Date('2026-08-10T14:00:00Z'),
    'Europe/Prague',
  )

  expect(document.getTabs()).toHaveLength(2)
  expect(document.getTabs()[1].getBody().children.map((element) => element.getText()))
    .toEqual(['Meeting date: 2026-08-10', 'Agenda', 'Existing note'])
})

test('repairs a date-only Meeting notes tab left by an interrupted setup', () => {
  const document = new FakeDocument([
    new FakeTab('Format', ['Agenda', 'Decisions']),
    new FakeTab('Meeting notes', ['Meeting date: 2026-08-10']),
  ])
  documents.set('doc-4', document)

  ensureMeetingNotesTab_(
    'doc-4',
    'Format',
    new Date('2026-08-10T14:00:00Z'),
    'Europe/Prague',
  )

  expect(document.getTabs()[1].getBody().children.map((element) => element.getText()))
    .toEqual(['Meeting date: 2026-08-10', 'Agenda', 'Decisions'])
})

test('does not treat non-text partial content as an empty interrupted setup', () => {
  const notesTab = new FakeTab('Meeting notes', ['Meeting date: 2026-08-10'])
  notesTab.getBody().children.push(new FakeElement('', 'INLINE_IMAGE'))
  const document = new FakeDocument([
    new FakeTab('Format', ['Agenda']),
    notesTab,
  ])
  documents.set('doc-5', document)

  ensureMeetingNotesTab_(
    'doc-5',
    'Format',
    new Date('2026-08-10T14:00:00Z'),
    'Europe/Prague',
  )

  expect(notesTab.getBody().children).toHaveLength(2)
  expect(notesTab.getBody().children[1].getType()).toBe('INLINE_IMAGE')
})

test('fails closed when a missing format title has multiple candidates', () => {
  const document = new FakeDocument([
    new FakeTab('Legacy format', ['Agenda']),
    new FakeTab('Attendee scratchpad', ['Note']),
    new FakeTab('Meeting notes', ['Meeting date: 2026-08-10']),
  ])
  documents.set('doc-6', document)

  expect(() => ensureMeetingNotesTab_(
    'doc-6',
    'Format',
    new Date('2026-08-10T14:00:00Z'),
    'Europe/Prague',
  )).toThrow('multiple tabs and no Format format tab')
})

test('placeholder resolution changes only the immutable format tab', () => {
  const document = new FakeDocument([
    new FakeTab('Format', ['Agenda for {date}', 'Attendees: {attendees}']),
    new FakeTab('Meeting notes', [
      'Meeting date: 2026-08-10',
      'Attendee typed literal {date} and {attendees}',
    ]),
  ])
  documents.set('doc-7', document)

  replacePlaceholdersInFormatTab_(
    'doc-7',
    { attendees: ['A', 'B'], timeZone: 'Europe/Prague' },
    new Date('2026-08-10T14:00:00Z'),
    'Format',
  )

  expect(document.getTabs()[0].getBody().children.map((element) => element.getText()))
    .toEqual(['Agenda for 2026-08-10', 'Attendees: A, B'])
  expect(document.getTabs()[1].getBody().children.map((element) => element.getText()))
    .toEqual([
      'Meeting date: 2026-08-10',
      'Attendee typed literal {date} and {attendees}',
    ])
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
