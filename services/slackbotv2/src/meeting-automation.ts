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
  customInstructions?: string
}

export type MeetingAutomationDispatchResult = {
  request: SlackMeetingAutomationRunRequest
  response: JsonObject
}

const MEETING_AUTOMATION_COMMAND = /^(?:(?:@?orbie)\s+)?(?:run\s+cadence|cadence\s+run|run\s+meeting\s+automation|meeting\s+ops)\s+(.+)$/is
export const MAX_CUSTOM_INSTRUCTIONS_CHARS = 4000

export function parseMeetingAutomationCommand(
  text: string,
  botUserId?: string
): MeetingAutomationCommand | null {
  const commandText = stripLeadingBotMention(text, botUserId).trim()
  const match = MEETING_AUTOMATION_COMMAND.exec(commandText)
  const commandBody = stripTrailingChatGptAttribution(match?.[1])
  const { cadenceQuery, customInstructions } = splitCustomInstructions(commandBody)
  if (!cadenceQuery) return null
  if (customInstructions !== undefined && !isValidCustomInstructions(customInstructions)) {
    return null
  }
  return {
    cadenceQuery,
    ...(customInstructions ? { customInstructions } : {})
  }
}

function stripTrailingChatGptAttribution(value: string | undefined): string | undefined {
  return value?.replace(/\s*Sent using @ChatGPT\s*$/i, '').trim()
}

function unquoteCadenceQuery(value: string | undefined): string | undefined {
  if (!value || value.length < 2) return value
  const first = value[0]
  const last = value[value.length - 1]
  return (first === last && (first === '"' || first === "'"))
    ? value.slice(1, -1).trim()
    : value
}

function splitCustomInstructions(value: string | undefined): {
  cadenceQuery?: string
  customInstructions?: string
} {
  if (!value) return {}
  const suffix = value.match(/(?:\s+with\s+instructions\s*:|\r?\n\s*instructions\s*:)([\s\S]*)$/i)
  if (!suffix || suffix.index === undefined) {
    return { cadenceQuery: unquoteCadenceQuery(value) }
  }
  const cadenceQuery = unquoteCadenceQuery(value.slice(0, suffix.index).trim())
  const customInstructions = suffix[1]?.trim() ?? ''
  return { cadenceQuery, customInstructions }
}

function isValidCustomInstructions(value: string): boolean {
  return (
    Array.from(value).length <= MAX_CUSTOM_INSTRUCTIONS_CHARS
    && !Array.from(value).some(character =>
      /\p{Cc}/u.test(character) && !['\n', '\r', '\t'].includes(character)
    )
  )
}

export function isWorldFoundationMeetingAutomationSurface(
  message: Message
): boolean {
  const teamId = rawSlackField(message.raw, 'team_id') ?? rawSlackField(message.raw, 'team')
  const channelId = rawSlackField(message.raw, 'channel')
  if (teamId !== WORLD_FOUNDATION_SLACK_TEAM_ID || !channelId) return false
  return /^[CGD][A-Z0-9]+$/.test(channelId)
}

export async function dispatchMeetingAutomationCommand(
  options: SlackbotV2Options,
  message: Message,
  command: MeetingAutomationCommand
): Promise<MeetingAutomationDispatchResult | null> {
  if (
    !isWorldFoundationMeetingAutomationSurface(message)
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
    ...(requester.slackChannelId.startsWith('D')
      ? {}
      : { slack_thread_ts: rawSlackField(message.raw, 'thread_ts') ?? message.id }),
    ...(command.customInstructions
      ? { custom_instructions: command.customInstructions }
      : {}),
    ...(requester.slackEmail ? { requester_slack_email: requester.slackEmail } : {})
  }
  const response = await postSlackMeetingAutomationRun(options, request)
  return { request, response }
}

function stripLeadingBotMention(text: string, botUserId?: string): string {
  const mention = botUserId
    ? new RegExp(`^\\s*<@${escapeRegExp(botUserId)}(?:\\|[^>]*)?>\\s*`, 'i')
    : /^\s*<@[A-Z0-9]+(?:\|[^>]*)?>\s*/i
  const stripped = text.replace(mention, '')
  if (stripped !== text) return stripped

  // Slack's Chat SDK can render a leading user mention as a visible @name
  // instead of preserving the raw <@USER> token. In a DM the command parser
  // is already scoped to the bot's conversation, so accept that rendered form.
  return botUserId
    ? stripped.replace(/^\s*@[A-Z0-9_.-]+\b\s*/i, '')
    : stripped
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
