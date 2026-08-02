import type { Logger, Message, ReactionEvent } from 'chat'
import { withSlackApiTimeout } from './session-api'
import type { SlackbotV2Options } from './types'
import { isJsonObject, splitEnvList, stringValue } from './utils'

export const DEFAULT_DELETE_REACTION = 'wastebasket'

/**
 * Whether the destructive reaction handler is configured at all.
 * An empty allowlist deliberately disables the feature.
 */
export function deleteOrbieMessageEnabled(options: SlackbotV2Options): boolean {
  return (
    configuredList(options.deleteAllowedUsers, 'SLACKBOTV2_DELETE_ALLOWED_USERS').length > 0 ||
    configuredList(options.deleteAllowedTeamIds, 'SLACKBOTV2_DELETE_ALLOWED_TEAM_IDS').length > 0
  )
}

/**
 * Delete a message only when a configured, authorized user reacts to a message
 * authored by this bot. Reaction events are deliberately silent for denied or
 * malformed requests so they cannot be used to probe policy.
 */
export async function handleDeleteOrbieReaction(
  event: ReactionEvent,
  options: SlackbotV2Options,
  logger: Logger
): Promise<void> {
  const configuredReaction =
    options.deleteReaction ?? process.env.SLACKBOTV2_DELETE_REACTION ?? DEFAULT_DELETE_REACTION
  if (!event.added || event.rawEmoji !== configuredReaction) return

  const channelId = reactionChannelId(event)
  const allowedChannels = configuredList(
    options.deleteAllowedChannels,
    'SLACKBOTV2_DELETE_ALLOWED_CHANNELS'
  )
  if (allowedChannels.length > 0 && (!channelId || !allowedChannels.includes(channelId))) {
    logDenied(logger, 'channel_not_allowlisted', event, channelId)
    return
  }

  const allowedUsers = configuredList(
    options.deleteAllowedUsers,
    'SLACKBOTV2_DELETE_ALLOWED_USERS'
  )
  if (allowedUsers.length > 0 && !allowedUsers.includes(event.user.userId)) {
    logDenied(logger, 'user_not_allowlisted', event, channelId)
    return
  }

  const allowedTeams = configuredList(
    options.deleteAllowedTeamIds,
    'SLACKBOTV2_DELETE_ALLOWED_TEAM_IDS'
  )
  if (
    allowedTeams.length > 0 &&
    !(await userBelongsToAllowedTeam(event.user.userId, allowedTeams, options, logger))
  ) {
    logDenied(logger, 'team_not_allowlisted', event, channelId)
    return
  }

  const target = await resolveTargetMessage(event, options, logger)
  if (!target?.author.isMe) {
    logDenied(logger, 'target_not_authored_by_orbie', event, channelId)
    return
  }

  try {
    await withSlackApiTimeout(options, 'Slack delete Orbie message', () =>
      event.adapter.deleteMessage(event.threadId, event.messageId)
    )
    logger.info('slackbotv2_orbie_message_deleted', {
      channel_id: channelId,
      message_id: event.messageId,
      requested_by: event.user.userId,
      reaction: configuredReaction
    })
  } catch (error) {
    logger.warn('slackbotv2_orbie_message_delete_failed', {
      channel_id: channelId,
      error: error instanceof Error ? error.message : String(error),
      message_id: event.messageId,
      requested_by: event.user.userId
    })
  }
}

function configuredList(
  configured: readonly string[] | undefined,
  envName: string
): string[] {
  return configured
    ? [...configured].map(value => value.trim()).filter(Boolean)
    : splitEnvList(process.env[envName])
}

async function resolveTargetMessage(
  event: ReactionEvent,
  options: SlackbotV2Options,
  logger: Logger
): Promise<Message | undefined> {
  const raw = isJsonObject(event.raw) ? event.raw : undefined
  const itemUser = raw && isJsonObject(raw.item) ? stringValue(raw.item_user) : undefined
  const botUserId = options.botUserId ?? event.adapter.botUserId
  if (itemUser && botUserId && itemUser === botUserId) {
    return event.message ?? ({ author: { isMe: true } } as Message)
  }

  if (event.message) return event.message
  if (!event.adapter.fetchMessage) return undefined

  try {
    return (
      (await withSlackApiTimeout(options, 'Slack fetch reacted message', () =>
        event.adapter.fetchMessage!(event.threadId, event.messageId)
      )) ?? undefined
    )
  } catch (error) {
    logger.warn('slackbotv2_orbie_message_lookup_failed', {
      error: error instanceof Error ? error.message : String(error),
      message_id: event.messageId
    })
    return undefined
  }
}

async function userBelongsToAllowedTeam(
  userId: string,
  allowedTeams: readonly string[],
  options: SlackbotV2Options,
  logger: Logger
): Promise<boolean> {
  try {
    const url = new URL('users.info', options.slackApiUrl ?? 'https://slack.com/api/')
    url.searchParams.set('user', userId)
    const response = await withSlackApiTimeout(options, 'Slack delete policy users.info', () =>
      (options.fetch ?? fetch)(url, {
        headers: { authorization: `Bearer ${options.botToken}` }
      })
    )
    const payload: unknown = await response.json()
    if (
      !response.ok ||
      !isJsonObject(payload) ||
      payload.ok === false ||
      !isJsonObject(payload.user)
    ) {
      return false
    }
    const user = payload.user
    if (user.is_stranger === true) return false
    const teamId = stringValue(user.team_id)
    return Boolean(teamId && allowedTeams.includes(teamId))
  } catch (error) {
    logger.warn('slackbotv2_orbie_delete_policy_user_lookup_failed', {
      error: error instanceof Error ? error.message : String(error),
      user_id: userId
    })
    return false
  }
}

function reactionChannelId(event: ReactionEvent): string | undefined {
  const raw = isJsonObject(event.raw) ? event.raw : undefined
  if (raw && isJsonObject(raw.item)) {
    const channel = stringValue(raw.item.channel)
    if (channel) return channel
  }
  try {
    return event.adapter.channelIdFromThreadId(event.threadId)
  } catch {
    return undefined
  }
}

function logDenied(
  logger: Logger,
  reason: string,
  event: ReactionEvent,
  channelId: string | undefined
): void {
  logger.info('slackbotv2_orbie_delete_reaction_ignored', {
    channel_id: channelId,
    message_id: event.messageId,
    reason,
    requested_by: event.user.userId
  })
}
