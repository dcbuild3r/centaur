import { createHash, randomUUID } from 'node:crypto'
import type { Message } from 'chat'
import {
  postSlackMeetingSchedulingRun,
  resolveSlackMeetingAutomationRequester,
  serializeMessage,
  type SlackMeetingSchedulingRunRequest
} from './session-api'
import type { JsonObject, SlackbotV2Options } from './types'

export type PendingMeetingBooking = {
  attendeeEmails: string[]
  durationMinutes: number
  expiresAtMs: number
  occurrenceKey: string
  organizerEmail: string
  start: string
  timeZone: string
  title: string
}

const BOOKING_TTL_MS = 30 * 60 * 1000
const EMAIL = /\b[A-Z0-9._%+-]+@world\.org\b/gi

export function isMeetingConfirmation(text: string): boolean {
  return /^(?:confirm|yes,?\s*(?:book|schedule)\s+it|book\s+it|schedule\s+it)[.!]?$/i.test(text.trim())
}

export function parseFixedTimeMeetingRequest(
  text: string,
  requesterEmail: string,
  now = new Date()
): PendingMeetingBooking | null {
  const clean = text.replace(/^\s*(?:<@[A-Z0-9]+(?:\|[^>]*)?>|@orbie)\s*/i, '').trim()
  if (!/^(?:schedule|book|create)\b/i.test(clean) || !/\bmeeting\b/i.test(clean)) return null

  const durationMatch = clean.match(/\b(\d{1,3})[- ]minute\b/i)
  const timeMatch = clean.match(/\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b/i)
  const titleMatch = clean.match(/\bcalled\s+["“]([^"”]{1,160})["”]/i)
  const zoneMatch = clean.match(/\b(Prague|UTC)\s+time\b/i)
  if (!durationMatch || !timeMatch || !titleMatch || !zoneMatch) return null

  const durationMinutes = Number(durationMatch[1])
  if (!Number.isInteger(durationMinutes) || durationMinutes < 5 || durationMinutes > 480) return null
  let hour = Number(timeMatch[1])
  const minute = Number(timeMatch[2] ?? '0')
  if (hour < 1 || hour > 12 || minute > 59) return null
  if (timeMatch[3]!.toLowerCase() === 'pm' && hour !== 12) hour += 12
  if (timeMatch[3]!.toLowerCase() === 'am' && hour === 12) hour = 0

  const timeZone = zoneMatch[1]!.toLowerCase() === 'prague' ? 'Europe/Prague' : 'UTC'
  const dayOffset = /\btomorrow\b/i.test(clean) ? 1 : /\btoday\b/i.test(clean) ? 0 : -1
  if (dayOffset < 0) return null
  const local = zonedParts(now, timeZone)
  const date = new Date(Date.UTC(local.year, local.month - 1, local.day + dayOffset, hour, minute))
  const start = zonedLocalToIso(date, timeZone)
  if (new Date(start).getTime() <= now.getTime()) return null

  const emails = Array.from(clean.matchAll(EMAIL), match => match[0].toLowerCase())
  const organizerEmail = requesterEmail.trim().toLowerCase()
  const attendeeEmails = Array.from(new Set([organizerEmail, ...emails]))
  if (!attendeeEmails.every(email => /^[^@\s]+@world\.org$/i.test(email))) return null
  return {
    attendeeEmails,
    durationMinutes,
    expiresAtMs: now.getTime() + BOOKING_TTL_MS,
    occurrenceKey: `slack:${randomUUID()}`,
    organizerEmail,
    start,
    timeZone,
    title: titleMatch[1]!.trim()
  }
}

export function meetingBookingPreview(booking: PendingMeetingBooking): string {
  return [
    'Please confirm this real meeting booking:',
    `• ${booking.title}`,
    `• ${booking.start} (${booking.timeZone}), ${booking.durationMinutes} minutes`,
    `• Owner: ${booking.organizerEmail}`,
    `• Attendees: ${booking.attendeeEmails.join(', ')}`,
    '• World Foundation Zoom with automatic cloud recording',
    '',
    'Reply `confirm` within 30 minutes to create the Calendar event and Zoom room.'
  ].join('\n')
}

export async function dispatchConfirmedMeetingBooking(
  options: SlackbotV2Options,
  message: Message,
  booking: PendingMeetingBooking
): Promise<JsonObject | null> {
  const serialized = await serializeMessage(message, options)
  const requester = await resolveSlackMeetingAutomationRequester(options, serialized)
  if (!requester || requester.slackEmail?.toLowerCase() !== booking.organizerEmail) return null
  const request: SlackMeetingSchedulingRunRequest = {
    operation: 'book_meeting',
    args: {
      attendee_emails: booking.attendeeEmails,
      confirmation_token: slotConfirmationToken(booking),
      duration_minutes: booking.durationMinutes,
      occurrence_key: booking.occurrenceKey,
      start: booking.start,
      time_zone: booking.timeZone,
      title: booking.title
    },
    requester_slack_team_id: requester.slackTeamId,
    requester_slack_user_id: requester.slackUserId,
    slack_channel_id: requester.slackChannelId,
    request_message_id: message.id,
    ...(requester.slackChannelId.startsWith('D') ? {} : { slack_thread_ts: message.id }),
    ...(requester.slackEmail ? { requester_slack_email: requester.slackEmail } : {})
  }
  return postSlackMeetingSchedulingRun(options, request)
}

function slotConfirmationToken(booking: PendingMeetingBooking): string {
  const payload = JSON.stringify({
    attendees: [...new Set(booking.attendeeEmails)].sort(),
    duration: booking.durationMinutes,
    organizer: booking.organizerEmail,
    start: booking.start,
    time_zone: booking.timeZone
  })
  return `slot-v1:${createHash('sha256').update(payload).digest('hex')}`
}

type ZonedParts = { day: number; hour: number; minute: number; month: number; second: number; year: number }

function zonedParts(date: Date, timeZone: string): ZonedParts {
  const parts = new Intl.DateTimeFormat('en-CA', {
    day: '2-digit', hour: '2-digit', hourCycle: 'h23', minute: '2-digit',
    month: '2-digit', second: '2-digit', timeZone, year: 'numeric'
  }).formatToParts(date)
  return Object.fromEntries(parts.filter(part => part.type !== 'literal').map(part => [part.type, Number(part.value)])) as ZonedParts
}

function zonedLocalToIso(localUtc: Date, timeZone: string): string {
  let guess = localUtc.getTime()
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const parts = zonedParts(new Date(guess), timeZone)
    const rendered = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second)
    guess += localUtc.getTime() - rendered
  }
  return new Date(guess).toISOString().replace('.000Z', 'Z')
}
