import { describe, expect, test } from 'bun:test'
import {
  isMeetingConfirmation,
  meetingBookingPreview,
  parseFixedTimeMeetingRequest
} from '../src/meeting-scheduling'

describe('fixed-time meeting scheduling ingress', () => {
  test('parses the reported Orbie DM into an exact confirmation proposal', () => {
    const booking = parseFixedTimeMeetingRequest(
      'Schedule a 10-minute meeting called "Orbie Zoom integration smoke test" for me today at 1:15 PM Prague time. Use my verified Google Calendar, create the Zoom room, and enable automatic cloud recording.',
      'dc.builder@world.org',
      new Date('2026-08-27T10:44:10Z'),
      'orbie'
    )

    expect(booking).toMatchObject({
      attendeeEmails: ['dc.builder@world.org'],
      durationMinutes: 10,
      organizerCalendarKey: 'orbie',
      organizerEmail: 'dc.builder@world.org',
      start: '2026-08-27T11:15:00Z',
      timeZone: 'Europe/Prague',
      title: 'Orbie Zoom integration smoke test'
    })
    expect(meetingBookingPreview(booking!)).toContain('Requested by: dc.builder@world.org')
    expect(meetingBookingPreview(booking!)).toContain('Reply `confirm`')
  })

  test('requires an explicit supported date, time, duration, title, and timezone', () => {
    expect(parseFixedTimeMeetingRequest('Schedule a meeting tomorrow', 'dc.builder@world.org')).toBeNull()
    expect(parseFixedTimeMeetingRequest(
      'Schedule a 10-minute meeting called "Past" for me today at 1:15 PM Prague time',
      'dc.builder@world.org',
      new Date('2026-08-27T13:00:00Z')
    )).toBeNull()
  })

  test('recognizes only unambiguous booking confirmations', () => {
    expect(isMeetingConfirmation('confirm')).toBeTrue()
    expect(isMeetingConfirmation('confirm\n\nSent using @ChatGPT')).toBeTrue()
    expect(isMeetingConfirmation('yes, book it')).toBeTrue()
    expect(isMeetingConfirmation('looks good')).toBeFalse()
  })
})
