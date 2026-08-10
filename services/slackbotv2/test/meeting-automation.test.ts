import { describe, expect, test } from 'bun:test'
import type { Message } from 'chat'
import {
  dispatchMeetingAutomationCommand,
  isWorldFoundationSlackDm,
  parseMeetingAutomationCommand
} from '../src/meeting-automation'
import { WORLD_FOUNDATION_SLACK_TEAM_ID } from '../src/session-api'
import type { SlackbotV2Options } from '../src/types'

const BOT_USER_ID = 'UBOT'
const USER_ID = 'UREQUESTER'
const DM_CHANNEL_ID = 'DREQUESTER'

function slackMessage(
  text: string,
  overrides: Record<string, unknown> = {}
): Message {
  return {
    attachments: [],
    author: {
      fullName: 'Requester',
      isBot: false,
      isMe: false,
      userId: USER_ID,
      userName: 'requester'
    },
    id: '1710000000.000100',
    isMention: true,
    links: [],
    metadata: { dateSent: new Date('2026-08-10T00:00:00.000Z') },
    raw: {
      channel: DM_CHANNEL_ID,
      team: WORLD_FOUNDATION_SLACK_TEAM_ID,
      team_id: WORLD_FOUNDATION_SLACK_TEAM_ID,
      text,
      ts: '1710000000.000100',
      user: USER_ID
    },
    text,
    threadId: `slack:${DM_CHANNEL_ID}:1710000000.000100`,
    ...overrides
  } as unknown as Message
}

describe('meeting automation command parsing', () => {
  test.each([
    ['run cadence weekly team sync', 'weekly team sync'],
    ['run meeting automation "Leadership 1:1"', 'Leadership 1:1'],
    ['meeting ops private cadence', 'private cadence'],
    [`<@${BOT_USER_ID}|orbie> run cadence  weekly team sync  `, 'weekly team sync'],
    [
      'run cadence Piotr Meeting Ops Demo\n\nSent using @ChatGPT',
      'Piotr Meeting Ops Demo'
    ],
    [
      'run cadence "Piotr Meeting Ops Demo" Sent using @ChatGPT',
      'Piotr Meeting Ops Demo'
    ]
  ])('parses %s', (text, cadenceQuery) => {
    expect(parseMeetingAutomationCommand(text, BOT_USER_ID)).toEqual({ cadenceQuery })
  })

  test('requires a non-empty query and strips only the configured bot mention', () => {
    expect(parseMeetingAutomationCommand(`<@${BOT_USER_ID}> run cadence`, BOT_USER_ID)).toBeNull()
    expect(parseMeetingAutomationCommand('<@UOTHER> run cadence weekly', BOT_USER_ID)).toBeNull()
    expect(parseMeetingAutomationCommand('run cadence   ')).toBeNull()
  })
})

describe('meeting automation dispatch', () => {
  test('only accepts World direct messages', () => {
    expect(isWorldFoundationSlackDm(slackMessage('run cadence weekly'))).toBe(true)
    expect(
      isWorldFoundationSlackDm(
        slackMessage('run cadence weekly', {
          raw: { channel: 'CCHANNEL', team: WORLD_FOUNDATION_SLACK_TEAM_ID, user: USER_ID }
        })
      )
    ).toBe(false)
    expect(
      isWorldFoundationSlackDm(
        slackMessage('run cadence weekly', {
          raw: { channel: DM_CHANNEL_ID, team: 'TOTHER', user: USER_ID }
        })
      )
    ).toBe(false)
  })

  test('posts the trusted requester and existing DM channel to the broker', async () => {
    const requests: Array<{ body: unknown; headers: Headers; url: string }> = []
    const options: SlackbotV2Options = {
      apiKey: 'broker-key',
      apiUrl: 'https://api.example.test',
      botToken: 'xoxb-test',
      fetch: async (input, init) => {
        requests.push({
          body: init?.body ? JSON.parse(String(init.body)) : undefined,
          headers: new Headers(init?.headers),
          url: String(input)
        })
        return Response.json({
          created: true,
          ok: true,
          run_id: 'run-123',
          status: 'queued',
          task_id: 'task-123'
        })
      },
      signingSecret: 'secret'
    }

    const result = await dispatchMeetingAutomationCommand(
      options,
      slackMessage(`<@${BOT_USER_ID}> run cadence weekly team sync`),
      { cadenceQuery: 'weekly team sync' }
    )

    expect(result?.response).toMatchObject({ run_id: 'run-123', status: 'queued' })
    expect(requests).toHaveLength(1)
    expect(requests[0]?.url).toBe('https://api.example.test/api/slack/meeting-automation/runs')
    expect(requests[0]?.headers.get('authorization')).toBe('Bearer broker-key')
    expect(requests[0]?.body).toEqual({
      cadence_query: 'weekly team sync',
      requester_slack_team_id: WORLD_FOUNDATION_SLACK_TEAM_ID,
      requester_slack_user_id: USER_ID,
      slack_channel_id: DM_CHANNEL_ID,
      request_message_id: '1710000000.000100'
    })
  })

  test('does not call the broker for a channel or another team', async () => {
    let calls = 0
    const options: SlackbotV2Options = {
      apiUrl: 'https://api.example.test',
      botToken: 'xoxb-test',
      fetch: async () => {
        calls += 1
        return Response.json({ ok: true })
      },
      signingSecret: 'secret'
    }

    expect(
      await dispatchMeetingAutomationCommand(
        options,
        slackMessage('run cadence weekly', {
          raw: { channel: 'CCHANNEL', team: WORLD_FOUNDATION_SLACK_TEAM_ID, user: USER_ID }
        }),
        { cadenceQuery: 'weekly' }
      )
    ).toBeNull()
    expect(
      await dispatchMeetingAutomationCommand(
        options,
        slackMessage('run cadence weekly', {
          raw: { channel: DM_CHANNEL_ID, team: 'TOTHER', user: USER_ID }
        }),
        { cadenceQuery: 'weekly' }
      )
    ).toBeNull()
    expect(calls).toBe(0)
  })
})
