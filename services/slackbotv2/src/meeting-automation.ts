import type { Message } from 'chat'
import {
  postSlackMeetingAutomationRun,
  resolveSlackMeetingAutomationRequester,
  serializeMessage,
  WORLD_FOUNDATION_SLACK_TEAM_ID,
  type SlackMeetingAutomationRunRequest
} from './session-api'
import type { JsonObject, SlackbotV2Options } from './types'
import { isJsonObject, stringValue } from './utils'

export type MeetingAutomationCommand = {
  cadenceQuery: string
}

export type MeetingAutomationDispatchResult = {
  request: SlackMeetingAutomationRunRequest
  response: JsonObject
}

const MEETING_AUTOMATION_COMMAND = /^(?:run\s+cadence|run\s+meeting\s+automation|meeting\s+ops)\s+(.+)$/is

export function parseMeetingAutomationCommand(
  text: string,
  botUserId?: string
): MeetingAutomationCommand | null {
  const commandText = stripLeadingBotMention(text, botUserId).trim()
  const match = MEETING_AUTOMATION_COMMAND.exec(commandText)
  const cadenceQuery = unquoteCadenceQuery(match?.[1]?.trim())
  return cadenceQuery ? { cadenceQuery } : null
}

function unquoteCadenceQuery(value: string | undefined): string | undefined {
  if (!value || value.length < 2) return value
  const first = value[0]
  const last = value[value.length - 1]
  return (first === last && (first === '"' || first === "'"))
    ? value.slice(1, -1).trim()
    : value
}

export function isWorldFoundationSlackDm(message: Message): boolean {
  const teamId = rawSlackField(message.raw, 'team_id') ?? rawSlackField(message.raw, 'team')
  const channelId = rawSlackField(message.raw, 'channel')
  return teamId === WORLD_FOUNDATION_SLACK_TEAM_ID && channelId?.startsWith('D') === true
}

export async function dispatchMeetingAutomationCommand(
  options: SlackbotV2Options,
  message: Message,
  command: MeetingAutomationCommand
): Promise<MeetingAutomationDispatchResult | null> {
  if (
    !isWorldFoundationSlackDm(message)
    || message.author.isMe
    || message.author.isBot === true
  ) {
    return null
  }

  const serialized = await serializeMessage(message, options)
  const requester = await resolveSlackMeetingAutomationRequester(options, serialized)
  if (!requester) return null

  const request: SlackMeetingAutomationRunRequest = {
    cadence_query: command.cadenceQuery,
    requester_slack_team_id: requester.slackTeamId,
    requester_slack_user_id: requester.slackUserId,
    slack_channel_id: requester.slackChannelId,
    request_message_id: message.id,
    ...(requester.slackEmail ? { requester_slack_email: requester.slackEmail } : {})
  }
  const response = await postSlackMeetingAutomationRun(options, request)
  return { request, response }
}

function stripLeadingBotMention(text: string, botUserId?: string): string {
  const mention = botUserId
    ? new RegExp(`^\\s*<@${escapeRegExp(botUserId)}(?:\\|[^>]*)?>\\s*`, 'i')
    : /^\s*<@[A-Z0-9]+(?:\|[^>]*)?>\s*/i
  return text.replace(mention, '')
}

function rawSlackField(raw: unknown, key: string): string | undefined {
  for (const record of rawSlackRecords(raw)) {
    const value = stringValue(record[key])
    if (value) return value
    if (key === 'team_id' && isJsonObject(record.team)) {
      const teamId = stringValue(record.team.id)
      if (teamId) return teamId
    }
  }
  return undefined
}

function rawSlackRecords(raw: unknown): JsonObject[] {
  const records: JsonObject[] = []
  const seen = new Set<JsonObject>()
  const add = (value: unknown): void => {
    if (!isJsonObject(value) || seen.has(value)) return
    records.push(value)
    seen.add(value)
  }
  add(raw)
  if (isJsonObject(raw)) {
    add(raw.event)
    add(raw.message)
    if (isJsonObject(raw.event)) add(raw.event.message)
  }
  return records
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
