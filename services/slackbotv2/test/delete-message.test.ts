import { describe, expect, it } from 'bun:test'
import type { Logger, ReactionEvent } from 'chat'
import {
  deleteOrbieMessageEnabled,
  handleDeleteOrbieReaction
} from '../src/delete-message'
import type { SlackbotV2Options } from '../src/types'

const logger: Logger = {
  debug: () => {},
  info: () => {},
  warn: () => {},
  error: () => {},
  child: () => logger
}

function options(overrides: Partial<SlackbotV2Options> = {}): SlackbotV2Options {
  return {
    apiUrl: 'http://session.test/',
    botToken: 'xoxb-test',
    botUserId: 'UBOT',
    signingSecret: 'test',
    ...overrides
  }
}

function reactionEvent(overrides: Partial<ReactionEvent> = {}): ReactionEvent & {
  deleted: Array<{ threadId: string; messageId: string }>
} {
  const deleted: Array<{ threadId: string; messageId: string }> = []
  const adapter = {
    botUserId: 'UBOT',
    channelIdFromThreadId: (threadId: string) => threadId.split(':')[1] ?? '',
    deleteMessage: async (threadId: string, messageId: string) => {
      deleted.push({ threadId, messageId })
    },
    fetchMessage: async () => null
  }
  return {
    adapter,
    added: true,
    deleted,
    emoji: { name: 'wastebasket' } as ReactionEvent['emoji'],
    messageId: '1700000000.000002',
    raw: { item: { channel: 'CDELETE', ts: '1700000000.000002' }, item_user: 'UBOT' },
    rawEmoji: 'wastebasket',
    thread: {} as ReactionEvent['thread'],
    threadId: 'slack:CDELETE:1700000000.000001',
    user: {
      fullName: 'Allowed User',
      isBot: false,
      isMe: false,
      userId: 'UDELETE',
      userName: 'allowed'
    },
    ...overrides
  } as ReactionEvent & { deleted: Array<{ threadId: string; messageId: string }> }
}

describe('Orbie delete reaction policy', () => {
  it('is disabled when no user or team allowlist is configured', () => {
    expect(deleteOrbieMessageEnabled(options())).toBe(false)
    expect(deleteOrbieMessageEnabled(options({ deleteAllowedUsers: ['UDELETE'] }))).toBe(true)
    expect(deleteOrbieMessageEnabled(options({ deleteAllowedTeamIds: ['TWF'] }))).toBe(true)
  })

  it('deletes an Orbie-authored message for an allowlisted user', async () => {
    const event = reactionEvent()
    await handleDeleteOrbieReaction(
      event,
      options({ deleteAllowedUsers: ['UDELETE'] }),
      logger
    )
    expect(event.deleted).toEqual([
      { threadId: 'slack:CDELETE:1700000000.000001', messageId: '1700000000.000002' }
    ])
  })

  it('does not delete for an unallowlisted user or a removed reaction', async () => {
    const denied = reactionEvent()
    await handleDeleteOrbieReaction(denied, options({ deleteAllowedUsers: ['UOTHER'] }), logger)
    expect(denied.deleted).toHaveLength(0)

    const removed = reactionEvent({ added: false })
    await handleDeleteOrbieReaction(removed, options({ deleteAllowedUsers: ['UDELETE'] }), logger)
    expect(removed.deleted).toHaveLength(0)
  })

  it('does not delete a user-authored message', async () => {
    const event = reactionEvent({
      message: {
        author: { isMe: false }
      } as ReactionEvent['message']
    })
    await handleDeleteOrbieReaction(
      event,
      options({ deleteAllowedUsers: ['UDELETE'] }),
      logger
    )
    expect(event.deleted).toHaveLength(0)
  })

  it('can authorize all members of an explicitly configured team', async () => {
    const event = reactionEvent({
      user: {
        fullName: 'WF User',
        isBot: false,
        isMe: false,
        userId: 'UTEAM',
        userName: 'wf-user'
      }
    })
    const config = options({
      deleteAllowedTeamIds: ['TWF'],
      fetch: async () =>
        Response.json({ ok: true, user: { id: 'UTEAM', team_id: 'TWF', is_stranger: false } })
    })
    await handleDeleteOrbieReaction(event, config, logger)
    expect(event.deleted).toHaveLength(1)
  })

  it('honors an optional channel allowlist', async () => {
    const event = reactionEvent()
    await handleDeleteOrbieReaction(
      event,
      options({ deleteAllowedUsers: ['UDELETE'], deleteAllowedChannels: ['COTHER'] }),
      logger
    )
    expect(event.deleted).toHaveLength(0)
  })
})
